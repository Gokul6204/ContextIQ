from langchain_chroma import Chroma
# Removed top-level HuggingFaceEmbeddings to save memory/disk space on Render

import chromadb
from langchain_core.documents import Document
from typing import List
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

class RAGService:
    def __init__(self):
        self._embeddings = None
        self._vector_db = None
        
        # HuggingFace API Token
        self.hf_token = os.getenv("HF_TOKEN")
        
        # Chroma Cloud credentials
        self.chroma_api_key = os.getenv("CHROMA_API_KEY")
        self.chroma_tenant = os.getenv("CHROMA_TENANT")
        self.chroma_database = os.getenv("CHROMA_DATABASE")
        
        # Paths for local fallback
        self.persist_directory = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chroma_db")
        os.makedirs(self.persist_directory, exist_ok=True)

    @property
    def embeddings(self):
        """Force Cloud Embeddings via Hugging Face if token is available"""
        if self._embeddings is None:
            # 1. ALWAYS Try Hugging Face Cloud FIRST (Inference API)
            if self.hf_token and len(self.hf_token) > 5:
                try:
                    from langchain_huggingface import HuggingFaceEndpointEmbeddings
                    logger.info("📡 [CLOUD] Initializing Hugging Face Endpoint Embeddings...")
                    self._embeddings = HuggingFaceEndpointEmbeddings(
                        model="sentence-transformers/all-MiniLM-L6-v2",
                        huggingfacehub_api_token=self.hf_token
                    )
                    logger.info("✅ [CLOUD] Hugging Face Embeddings ACTIVE.")
                    return self._embeddings
                except Exception as e:
                    logger.error(f"❌ [CLOUD] Hugging Face Init FAILED: {e}")
            
            # 2. Local Fallback (Ollama) - Only if Cloud fails or Token is missing
            try:
                from langchain_community.embeddings import OllamaEmbeddings
                import httpx
                with httpx.Client() as client:
                    client.get("http://localhost:11434", timeout=2.0)
                    logger.info("🏠 [LOCAL] Falling back to Local Ollama.")
                    self._embeddings = OllamaEmbeddings(model="all-minilm")
            except Exception:
                logger.error("CRITICAL: No cloud token found and local Ollama is unreachable.")
                raise RuntimeError("No valid embedding engine found. Please provide HF_TOKEN for Cloud.")
                
        return self._embeddings

    @property
    def vector_db(self):
        """Force Cloud Chroma DB if API key is available"""
        if self._vector_db is None:
            from langchain_chroma import Chroma
            
            # 1. ALWAYS Try Chroma Cloud FIRST
            if self.chroma_api_key and "placeholder" not in self.chroma_api_key.lower():
                try:
                    logger.info(f"🌐 [CLOUD] Connecting to Chroma Cloud ({self.chroma_database})...")
                    client = chromadb.CloudClient(
                        api_key=self.chroma_api_key,
                        tenant=self.chroma_tenant,
                        database=self.chroma_database
                    )
                    self._vector_db = Chroma(
                        client=client,
                        collection_name="contextiq_v1",
                        embedding_function=self.embeddings
                    )
                    logger.info("✅ [CLOUD] Successfully linked to Chroma Cloud.")
                    return self._vector_db
                except Exception as e:
                    logger.warning(f"⚠️ [CLOUD] Chroma Cloud connection failed: {e}")
            
            # 2. Local Fallback - Only if Cloud keys are missing or connection fails
            try:
                logger.info(f"🏠 [LOCAL] Initializing Local Chroma at: {self.persist_directory}")
                self._vector_db = Chroma(
                    persist_directory=self.persist_directory,
                    collection_name="contextiq_v1",
                    embedding_function=self.embeddings
                )
                logger.info("✅ [LOCAL] Local Chroma initialized.")
            except Exception as e:
                logger.error(f"❌ [CRITICAL] Vector Store Failure: {e}", exc_info=True)
                raise
        return self._vector_db

    def add_documents(self, documents: List[Document], user_id: int):
        """Add documents in small batches to prevent timeouts on Render/Cloud"""
        if not documents:
            logger.warning("No documents to add.")
            return
        
        # --- DEBUG LOGGING ---
        # Look inside the langchain wrapper to see the real client type
        internal_client = self.vector_db._client if hasattr(self.vector_db, '_client') else self.vector_db
        db_type = "CLOUD 🌐" if "CloudClient" in str(type(internal_client)) else "LOCAL 🏠"
        logger.info(f"🛠️ [DEBUG] Vector Store Type: {db_type}")
        if db_type == "CLOUD 🌐":
            logger.info(f"🛠️ [DEBUG] Target: Tenant={self.chroma_tenant}, DB={self.chroma_database}")
        # --------------------

        filename = "unknown"
        for doc in documents:
            doc.metadata["user_id"] = user_id
            if "source" in doc.metadata:
                fn = os.path.basename(doc.metadata["source"])
                doc.metadata["source"] = fn
                filename = fn
        
        logger.info(f"🚀 [INDEXING] Starting for {filename} ({len(documents)} chunks) to {db_type}...")
        
        if self.vector_db is None:
            raise Exception("Vector Store connection failed.")

        # Batching: Process 10 chunks at a time to stay within Render/HF limits
        batch_size = 10
        total = len(documents)
        for i in range(0, total, batch_size):
            batch = documents[i:i + batch_size]
            current_batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            logger.info(f"📤 [UPLOAD] Batch {current_batch_num}/{total_batches} to {db_type}...")
            try:
                self.vector_db.add_documents(batch)
            except Exception as e:
                error_msg = str(e)
                if "403" in error_msg or "Forbidden" in error_msg:
                    logger.error("❌ [HF ERROR] Your HF_TOKEN does not have 'Inference' permissions.")
                    logger.error("👉 Please create a new WRITE token at: https://huggingface.co/settings/tokens")
                logger.error(f"❌ [FAILED] Batch {current_batch_num}: {e}")
                raise
        
        logger.info(f"✅ [SUCCESS] Indexed {total} chunks for {filename} in {db_type}.")

    def delete_document(self, file_path: str, user_id: int):
        """Delete all vectors associated with a specific file and user"""
        if self.vector_db is None:
            return False
            
        try:
            filename = os.path.basename(file_path)
            logger.info(f"Purging existing vectors for: {filename} (User: {user_id})")
            
            # Robust search: Try both filename AND full path (for legacy cleanup)
            # Use .get() to find IDs
            results = self.vector_db.get(where={
                "$and": [
                    {"user_id": {"$eq": user_id}},
                    {"$or": [
                        {"source": {"$eq": filename}},
                        {"source": {"$eq": file_path}}
                    ]}
                ]
            })
            
            if results and results.get('ids'):
                ids_to_delete = results['ids']
                logger.info(f"Deleting {len(ids_to_delete)} existing chunks.")
                self.vector_db.delete(ids=ids_to_delete)
                return True
            
            logger.info(f"No existing vectors found for {filename}. Clean start.")
            return False
        except Exception as e:
            logger.error(f"Error during deletion from Chroma: {str(e)}")
            return False

    def query(self, query_text: str, user_id: int, k: int = 5) -> List[Document]:
        """Query the vector store with user-level isolation"""
        if self.vector_db is None:
            logger.warning("Query attempted but vector_db is not initialized.")
            raise Exception("ContextIQ Vector Engine is currently offline or uninitialized.")
            
        try:
            # Filter results to ONLY include documents belonging to this user
            return self.vector_db.similarity_search(
                query_text, 
                k=k,
                filter={"user_id": user_id}
            )
        except Exception as e:
            logger.error(f"Error during Chroma query for user {user_id}: {str(e)}")
            return []

    def get_retriever(self, k: int = 5):
        if self.vector_db is None:
            return None
        return self.vector_db.as_retriever(search_kwargs={"k": k})