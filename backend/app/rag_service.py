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
        if self._embeddings is None:
            # Try Ollama First (ONLY if not on Render/Live)
            # Render doesn't have Ollama, so we check quickly
            try:
                from langchain_community.embeddings import OllamaEmbeddings
                import httpx
                
                # Check if Ollama is even reachable with a 5-second timeout
                with httpx.Client() as client:
                    try:
                        client.get("http://localhost:11434", timeout=5.0)
                        logger.info("Ollama is reachable. Initializing embeddings...")
                        self._embeddings = OllamaEmbeddings(model="all-minilm")
                        return self._embeddings
                    except:
                        logger.info("Ollama not reachable. Switching to Cloud Embeddings...")
            except Exception as e:
                logger.info(f"Ollama setup skipped: {e}")

            # Cloud Fallback (Hugging Face Inference API)
            if self.hf_token and len(self.hf_token) > 10:
                try:
                    from langchain_huggingface import HuggingFaceEndpointEmbeddings
                    logger.info(f"📡 Attempting Cloud Embeddings with token: {self.hf_token[:5]}***")
                    self._embeddings = HuggingFaceEndpointEmbeddings(
                        model="sentence-transformers/all-MiniLM-L6-v2",
                        huggingfacehub_api_token=self.hf_token
                    )
                    # Test it
                    self._embeddings.embed_query("ping")
                    logger.info("✅ Cloud Embeddings ACTIVE.")
                except Exception as e:
                    logger.error(f"❌ Cloud Embedding Test FAILED: {e}")
                    if "403" in str(e) or "Unauthorized" in str(e):
                        logger.error("👉 REASON: Your HF_TOKEN is invalid or missing 'Inference API' permissions.")
                    self._embeddings = None
            else:
                logger.error("❌ HF_TOKEN is missing or too short in Environment Variables.")
            
            if self._embeddings is None:
                logger.error("NO EMBEDDING ENGINE AVAILABLE. Indexing will fail.")
                raise RuntimeError("No valid embedding engine found. Please check HF_TOKEN.")
        return self._embeddings

    @property
    def vector_db(self):
        if self._vector_db is None:
            from langchain_chroma import Chroma
            
            # Use Local Chroma by default if running locally (not on Render)
            # This makes local development MUCH faster
            is_render = os.getenv("RENDER") is not None
            
            if is_render and self.chroma_api_key and "placeholder" not in self.chroma_api_key.lower():
                try:
                    logger.info(f"🌐 Connecting to Chroma Cloud...")
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
                    logger.info("✅ Connected to Chroma Cloud.")
                except Exception as e:
                    logger.warning(f"⚠️ Chroma Cloud connection failed: {e}. Falling back to Local.")
            
            if self._vector_db is None:
                try:
                    logger.info(f"🏠 Initializing Local Chroma at: {self.persist_directory}")
                    self._vector_db = Chroma(
                        persist_directory=self.persist_directory,
                        collection_name="contextiq_v1",
                        embedding_function=self.embeddings
                    )
                    logger.info("✅ Local Chroma initialized.")
                except Exception as e:
                    logger.error(f"❌ Critical Failure: {e}", exc_info=True)
        return self._vector_db

    def add_documents(self, documents: List[Document], user_id: int):
        """Add documents in small batches to prevent timeouts on Render/Cloud"""
        if not documents:
            logger.warning("No documents to add.")
            return
        
        filename = "unknown"
        for doc in documents:
            doc.metadata["user_id"] = user_id
            if "source" in doc.metadata:
                fn = os.path.basename(doc.metadata["source"])
                doc.metadata["source"] = fn
                filename = fn
        
        logger.info(f"🚀 Starting Cloud Indexing for {filename} ({len(documents)} chunks)...")
        
        if self.vector_db is None:
            raise Exception("Vector Store connection failed.")

        # Batching: Process 10 chunks at a time to stay within Render/HF limits
        batch_size = 10
        total = len(documents)
        for i in range(0, total, batch_size):
            batch = documents[i:i + batch_size]
            current_batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            logger.info(f"📤 Uploading batch {current_batch_num}/{total_batches}...")
            try:
                self.vector_db.add_documents(batch)
            except Exception as e:
                logger.error(f"❌ Batch {current_batch_num} failed: {e}")
                raise
        
        logger.info(f"✅ SUCCESSFULLY INDEXED {total} chunks for {filename}.")

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