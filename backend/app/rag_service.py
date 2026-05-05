from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
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
            if self.hf_token:
                from langchain_huggingface import HuggingFaceEndpointEmbeddings
                logger.info("Initializing HuggingFace Inference API Embeddings...")
                self._embeddings = HuggingFaceEndpointEmbeddings(
                    model="BAAI/bge-small-en-v1.5",
                    huggingfacehub_api_token=self.hf_token
                )
            else:
                from langchain_huggingface import HuggingFaceEmbeddings
                logger.info("Lazily initializing local HuggingFace embeddings (No HF_TOKEN found)...")
                self._embeddings = HuggingFaceEmbeddings(
                    model_name="BAAI/bge-small-en-v1.5",
                    model_kwargs={"device": "cpu"},
                    encode_kwargs={"normalize_embeddings": True},
                )
        return self._embeddings

    @property
    def vector_db(self):
        if self._vector_db is None:
            from langchain_chroma import Chroma
            logger.info("Lazily initializing ContextIQ Vector Engine...")
            
            # Try Cloud First
            if self.chroma_api_key and "placeholder" not in self.chroma_api_key.lower():
                try:
                    logger.info(f"Connecting to Chroma Cloud (Database: {self.chroma_database})...")
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
                    logger.info("Successfully connected to Chroma Cloud.")
                except Exception as e:
                    logger.warning(f"Chroma Cloud connection failed: {e}. Falling back to Local Engine.")
            
            if self._vector_db is None:
                # Fallback to Local
                try:
                    logger.info(f"Initializing Local Chroma Engine at: {self.persist_directory}")
                    self._vector_db = Chroma(
                        persist_directory=self.persist_directory,
                        collection_name="contextiq_v1",
                        embedding_function=self.embeddings
                    )
                    logger.info("Local Chroma Engine initialized successfully.")
                except Exception as e:
                    logger.error(f"Critical Failure: Could not initialize any Vector Engine: {str(e)}", exc_info=True)
        return self._vector_db

    def add_documents(self, documents: List[Document], user_id: int):
        """Add documents to the vector store with user isolation"""
        if not documents:
            logger.warning("No documents to add.")
            return
        
        # Add user_id to metadata for each document
        for doc in documents:
            doc.metadata["user_id"] = user_id
        
        if self.vector_db is None:
            logger.error("Cannot add documents: Vector DB is not initialized.")
            raise Exception("ContextIQ Vector Engine is currently offline or uninitialized.")

        logger.info(f"Adding {len(documents)} chunks to Chroma...")
        try:
            self.vector_db.add_documents(documents)
            logger.info("Successfully added documents to Chroma.")
        except Exception as e:
            logger.error(f"Error adding documents to Chroma: {str(e)}", exc_info=True)

    def delete_document(self, file_path: str, user_id: int):
        """Delete all vectors associated with a specific file and user"""
        if self.vector_db is None:
            return False
            
        try:
            logger.info(f"Purging vectors for user {user_id} file: {file_path}")
            
            # Use .get() with metadata filter to find IDs
            try:
                # Search for documents with the given source AND user_id
                results = self.vector_db.get(where={
                    "$and": [
                        {"source": {"$eq": file_path}},
                        {"user_id": {"$eq": user_id}}
                    ]
                })
                if results and results.get('ids'):
                    ids_to_delete = results['ids']
                    logger.info(f"Deleting {len(ids_to_delete)} chunks from Chroma.")
                    self.vector_db.delete(ids=ids_to_delete)
                    return True
                else:
                    logger.warning(f"No documents found for source: {file_path}")
            except Exception as e:
                logger.error(f"Error during .get() and delete: {e}")
                
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