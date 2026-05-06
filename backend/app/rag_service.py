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
            # Try Ollama First
            try:
                from langchain_community.embeddings import OllamaEmbeddings
                logger.info("Checking for local Ollama Embedding Engine (all-minilm)...")
                ollama = OllamaEmbeddings(model="all-minilm")
                # ACTUAL CHECK: See if Ollama responds
                ollama.embed_query("test") 
                self._embeddings = ollama
                logger.info("  Using Ollama for embeddings (all-minilm).")
                return self._embeddings
            except Exception as e:
                logger.info(f"Ollama check failed: {e}. Trying Hugging Face...")

            if self.hf_token:
                try:
                    from langchain_huggingface import HuggingFaceEndpointEmbeddings
                    logger.info("Initializing HuggingFace Inference API Embeddings...")
                    self._embeddings = HuggingFaceEndpointEmbeddings(
                        model="sentence-transformers/all-MiniLM-L6-v2",
                        huggingfacehub_api_token=self.hf_token
                    )
                    self._embeddings.embed_query("test")
                    logger.info("  Using HuggingFace Inference API.")
                except Exception as e:
                    logger.warning(f"HuggingFace Inference API failed: {e}")
                    self._embeddings = None
            
            if self._embeddings is None:
                try:
                    from langchain_huggingface import HuggingFaceEmbeddings
                    logger.info("Initializing local HuggingFace embeddings (Fallback)...")
                    self._embeddings = HuggingFaceEmbeddings(
                        model_name="sentence-transformers/all-MiniLM-L6-v2",
                        model_kwargs={"device": "cpu"},
                        encode_kwargs={"normalize_embeddings": True},
                    )
                    logger.info("  Using Local HuggingFace Embeddings.")
                except Exception as e:
                    logger.error(f"Failed to initialize any embedding engine: {e}")
                    raise RuntimeError("No valid embedding engine found.")
        return self._embeddings

    @property
    def vector_db(self):
        if self._vector_db is None:
            from langchain_chroma import Chroma
            # Try Cloud First
            if self.chroma_api_key and "placeholder" not in self.chroma_api_key.lower():
                try:
                    logger.info(f"Connecting to Chroma Cloud...")
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
                    logger.info("  Connected to Chroma Cloud.")
                except Exception as e:
                    logger.warning(f"Chroma Cloud connection failed: {e}. Falling back to Local.")
            
            if self._vector_db is None:
                try:
                    logger.info(f"Initializing Local Chroma at: {self.persist_directory}")
                    self._vector_db = Chroma(
                        persist_directory=self.persist_directory,
                        collection_name="contextiq_v1",
                        embedding_function=self.embeddings
                    )
                    logger.info("  Local Chroma initialized.")
                except Exception as e:
                    logger.error(f"Critical Failure: {e}", exc_info=True)
        return self._vector_db

    def add_documents(self, documents: List[Document], user_id: int):
        """Add documents to the vector store with user isolation"""
        if not documents:
            logger.warning("No documents to add.")
            return
        
        filename = "unknown"
        for doc in documents:
            doc.metadata["user_id"] = user_id
            if "source" in doc.metadata:
                # Store only the filename in metadata for portability
                fn = os.path.basename(doc.metadata["source"])
                doc.metadata["source"] = fn
                filename = fn
        
        logger.info(f"Indexing {len(documents)} chunks for file: {filename} (User: {user_id})")
        
        if self.vector_db is None:
            raise Exception("Vector Engine is offline.")

        try:
            self.vector_db.add_documents(documents)
            logger.info(f"  Successfully indexed {filename} in Chroma.")
        except Exception as e:
            logger.error(f"  Failed to add documents to Chroma: {e}", exc_info=True)
            raise

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