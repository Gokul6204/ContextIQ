import os
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import shutil
import logging

from llm_service import LLMService
from rag_service import RAGService
from document_service import DocumentService
from models import User, Chat, Message, UserDocument, SessionLocal
from auth import get_password_hash, verify_password, create_access_token, get_current_user_id
from sqlalchemy.orm import Session
from fastapi import Depends, status
from fastapi.security import OAuth2PasswordRequestForm

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Google Noteboolm API")

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for production or add your Vercel URL here
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
llm_service = LLMService()
rag_service = RAGService()
doc_service = DocumentService()

# Use absolute path for uploads
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
logger.info(f"Upload directory: {UPLOAD_DIR}")

class QueryRequest(BaseModel):
    prompt: str

class QueryResponse(BaseModel):
    answer: str
    sources: List[str]
    new_title: Optional[str] = None

class UserCreate(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class ChatCreate(BaseModel):
    title: str

# Dependency for DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def process_and_index(file_path: str, filename: str, user_id: int):
    """Background task to process and index document"""
    try:
        logger.info(f"Starting background processing for {filename} (User: {user_id})")
        
        filename_lower = filename.lower()
        if filename_lower.endswith(".pdf"):
            docs = doc_service.process_pdf(file_path)
        elif filename_lower.endswith(".docx"):
            docs = doc_service.process_docx(file_path)
        elif filename_lower.endswith(".md"):
            docs = doc_service.process_markdown(file_path)
        elif filename_lower.endswith(".txt"):
            docs = doc_service.process_text(file_path)
        else:
            logger.error(f"Unsupported file type for processing: {filename}")
            return
            
        num_chunks = len(docs)
        logger.info(f"Document {filename} processed into {num_chunks} chunks.")
        
        # Clean up any existing vectors for this file first (prevents duplication)
        logger.info(f"Purging existing vectors for {filename} to prevent duplication...")
        rag_service.delete_document(file_path, user_id)
        
        # Add to vector store
        rag_service.add_documents(docs, user_id)
        logger.info(f"Completed processing and indexing for {filename}")
        
    except Exception as e:
        logger.error(f"Error in background processing for {filename}: {str(e)}", exc_info=True)

@app.post("/register")
async def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    new_user = User(email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully", "id": new_user.id}

@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    # Sanitize filename to prevent directory traversal
    safe_filename = os.path.basename(file.filename)
    logger.info(f"User {user_id} uploading file: {safe_filename}")
    
    try:
        # Create user-specific upload directory
        user_upload_dir = os.path.join(UPLOAD_DIR, str(user_id))
        os.makedirs(user_upload_dir, exist_ok=True)
        file_path = os.path.join(user_upload_dir, safe_filename)
        
        # Save file
        def save_file():
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        
        from fastapi.concurrency import run_in_threadpool
        await run_in_threadpool(save_file)
        
        # Track in DB
        db_doc = db.query(UserDocument).filter(
            UserDocument.user_id == user_id, 
            UserDocument.filename == file.filename
        ).first()
        
        if not db_doc:
            db_doc = UserDocument(user_id=user_id, filename=file.filename, file_path=file_path)
            db.add(db_doc)
            db.commit()
        
        # Add processing to background tasks
        background_tasks.add_task(process_and_index, file_path, file.filename, user_id)
        
        return {"message": f"Successfully uploaded {file.filename}. Processing in background."}
        
    except Exception as e:
        logger.error(f"Error during upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
async def list_documents(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    docs = db.query(UserDocument).filter(UserDocument.user_id == user_id).all()
    return {"documents": [{"name": d.filename, "id": d.id} for d in docs]}

@app.delete("/documents/{filename}")
async def delete_document(
    filename: str, 
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    try:
        db_doc = db.query(UserDocument).filter(
            UserDocument.user_id == user_id, 
            UserDocument.filename == filename
        ).first()
        
        if not db_doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # 1. Delete from vector store
        rag_service.delete_document(db_doc.file_path, user_id)
        
        # 2. Delete from filesystem
        if os.path.exists(db_doc.file_path):
            os.remove(db_doc.file_path)
        
        # 3. Delete from DB
        db.delete(db_doc)
        db.commit()
        
        return {"message": f"Successfully deleted {filename}"}
    except Exception as e:
        logger.error(f"Error during deletion: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/chats")
async def get_chats(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chats = db.query(Chat).filter(Chat.user_id == user_id).order_by(Chat.created_at.desc()).all()
    return {"chats": [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in chats]}

@app.post("/chats")
async def create_chat(chat: ChatCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    new_chat = Chat(user_id=user_id, title=chat.title)
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)
    return new_chat

@app.get("/chats/{chat_id}/messages")
async def get_messages(chat_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"messages": chat.messages}

@app.delete("/chats/{chat_id}")
async def delete_chat(chat_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.delete(chat)
    db.commit()
    return {"message": "Chat deleted"}

@app.patch("/chats/{chat_id}")
async def update_chat_title(chat_id: int, chat_update: ChatCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat.title = chat_update.title
    db.commit()
    return chat

@app.post("/query", response_model=QueryResponse)
async def query_notebook(
    request: QueryRequest, 
    chat_id: Optional[int] = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    logger.info(f"User {user_id} processing query: {request.prompt}")
    
    # Retrieve relevant context
    try:
        from fastapi.concurrency import run_in_threadpool
        docs = await run_in_threadpool(rag_service.query, request.prompt, user_id)
    except Exception as e:
        logger.error(f"Error in RAG query: {str(e)}")
        return QueryResponse(answer=f"Error retrieving context: {str(e)}", sources=[])
    
    context = "\n\n".join([doc.page_content for doc in docs])
    sources = list(set([doc.metadata.get("source", "unknown") for doc in docs]))
    
    # Generate answer
    try:
        answer = await llm_service.generate_response(request.prompt, context)
        
        # Silent Auto-titling if it's the first message
        new_title = None
        if chat_id:
            chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
            if chat:
                # Save messages
                user_msg = Message(chat_id=chat_id, role="user", content=request.prompt)
                assistant_msg = Message(chat_id=chat_id, role="assistant", content=answer, sources=sources)
                db.add(user_msg)
                db.add(assistant_msg)
                
                if chat.title == "New Chat":
                    title_prompt = f"Generate a 2-3 word title for this conversation based on this first message: '{request.prompt}'. Return ONLY the title text."
                    # Use the internal LLM object for a quick title generation
                    title_res = llm_service.llm.invoke([("human", title_prompt)])
                    new_title = title_res.content.replace('"', '').strip()
                    chat.title = new_title
                
                db.commit()
                
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        return QueryResponse(answer=f"Error generating response: {str(e)}", sources=sources)
    
    return QueryResponse(answer=answer, sources=sources, new_title=new_title)

@app.post("/summary")
async def summarize_document(file_name: str):
    # This is a placeholder for real summarization logic
    # In a real app, we would query the LLM with all chunks or a map-reduce approach
    prompt = f"Summarize the document: {file_name}"
    docs = rag_service.query(prompt, k=5)
    context = "\n\n".join([doc.page_content for doc in docs])
    summary = await llm_service.generate_response(f"Provide a 3 paragraph summary of this document.", context)
    return {"summary": summary}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
