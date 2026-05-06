import os
from langchain_community.document_loaders import PyMuPDFLoader, TextLoader, UnstructuredURLLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from typing import List

class DocumentService:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=150,
            add_start_index=True
        )

    def process_pdf(self, file_path: str) -> List[Document]:
        loader = PyMuPDFLoader(file_path)
        docs = loader.load()
        return self.text_splitter.split_documents(docs)

    def process_text(self, file_path: str) -> List[Document]:
        loader = TextLoader(file_path)
        docs = loader.load()
        return self.text_splitter.split_documents(docs)

    def process_url(self, url: str) -> List[Document]:
        loader = UnstructuredURLLoader(urls=[url])
        docs = loader.load()
        return self.text_splitter.split_documents(docs)

    def process_docx(self, file_path: str) -> List[Document]:
        loader = Docx2txtLoader(file_path)
        docs = loader.load()
        return self.text_splitter.split_documents(docs)

    def process_markdown(self, file_path: str) -> List[Document]:
        # Markdown can be loaded with TextLoader
        loader = TextLoader(file_path)
        docs = loader.load()
        return self.text_splitter.split_documents(docs)
 