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
from storage_service import StorageService
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
storage_service = StorageService()

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
    db = SessionLocal()
    local_temp_path = None
    try:
        logger.info(f"🚀 Starting background processing for {filename} (User: {user_id})")
        
        # If we're using cloud storage, we need to download it first
        # Heuristic: if file_path is NOT an absolute local path, it's a remote path
        if storage_service.client and not os.path.isabs(file_path):
            remote_path = file_path
            local_temp_path = os.path.join(UPLOAD_DIR, "temp", str(user_id), filename)
            os.makedirs(os.path.dirname(local_temp_path), exist_ok=True)
            
            logger.info(f"📥 Downloading {filename} from Supabase for processing...")
            success = storage_service.download_file(remote_path, local_temp_path)
            if not success:
                logger.error(f"  Failed to download {filename} from Supabase.")
                return
            working_path = local_temp_path
        else:
            logger.info(f"📁 Using local file for processing: {file_path}")
            working_path = file_path

        # --- STEP 1: PARSING ---
        logger.info(f"Parsing document: {filename}...")
        filename_lower = filename.lower()
        if filename_lower.endswith(".pdf"):
            docs = doc_service.process_pdf(working_path)
        elif filename_lower.endswith(".docx"):
            docs = doc_service.process_docx(working_path)
        elif filename_lower.endswith(".md"):
            docs = doc_service.process_markdown(working_path)
        elif filename_lower.endswith(".txt"):
            docs = doc_service.process_text(working_path)
        else:
            logger.error(f"Unsupported file type for processing: {filename}")
            return
            
        num_chunks = len(docs)
        if num_chunks == 0:
            logger.warning(f"⚠️ Document {filename} resulted in 0 chunks. Parsing might have failed.")
            return

        logger.info(f"{filename} split into {num_chunks} chunks.")
        
        # --- STEP 2: VECTORIZING ---
        # Clean up any existing vectors first
        rag_service.delete_document(filename, user_id)
        
        logger.info(f"Sending chunks to [CLOUD] Chroma DB for {filename}...")
        rag_service.add_documents(docs, user_id)
        
        # --- STEP 3: FINALIZING ---
        db_doc = db.query(UserDocument).filter(UserDocument.user_id == user_id, UserDocument.filename == filename).first()
        if db_doc:
            db_doc.indexed = True
            db.commit()
            logger.info(f"SUCCESSFULLY INDEXED: {filename} is now ready for search.")
        
    except Exception as e:
        logger.error(f"❌ Error in background processing for {filename}: {str(e)}", exc_info=True)
        # Mark as failed in DB if possible (we don't have a status field, so we'll just leave indexed=False)
        # But we must ensure the user knows it failed. 
        # For now, let's at least log it very clearly.
        db_doc = db.query(UserDocument).filter(UserDocument.user_id == user_id, UserDocument.filename == filename).first()
        if db_doc:
            # We don't have a 'failed' column, so we'll just log it. 
            # In a future update, we should add a 'status' column.
            logger.error(f"  Indexing aborted for {filename}.")
    finally:
        # Cleanup local temp file if it exists
        if local_temp_path and os.path.exists(local_temp_path):
            try:
                os.remove(local_temp_path)
            except: pass
        db.close()

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
        # 1. Temporary local save for upload to Supabase
        temp_dir = os.path.join(UPLOAD_DIR, "temp", str(user_id))
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, safe_filename)
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 2. Upload to Supabase if configured, otherwise stay local
        if storage_service.client:
            remote_path = f"user_{user_id}/{safe_filename}"
            success = storage_service.upload_file(temp_path, remote_path)
            if success:
                # Use remote_path for DB record
                final_path = remote_path
                # Cleanup local temp
                os.remove(temp_path)
            else:
                # Fallback to local if upload fails but directory exists
                final_path = temp_path
        else:
            # Traditional local storage
            user_upload_dir = os.path.join(UPLOAD_DIR, str(user_id))
            os.makedirs(user_upload_dir, exist_ok=True)
            final_path = os.path.join(user_upload_dir, safe_filename)
            shutil.move(temp_path, final_path)
            
        # Track in DB
        db_doc = db.query(UserDocument).filter(
            UserDocument.user_id == user_id, 
            UserDocument.filename == file.filename
        ).first()
        
        if not db_doc:
            db_doc = UserDocument(user_id=user_id, filename=file.filename, file_path=final_path, indexed=False)
            db.add(db_doc)
            db.commit()
        else:
            # If it already exists, update path and reset indexed status
            db_doc.file_path = final_path
            db_doc.indexed = False
            db.commit()
        
        # Add processing to background tasks
        background_tasks.add_task(process_and_index, final_path, file.filename, user_id)
        
        return {"message": f"Successfully uploaded {file.filename}. Processing in background.", "indexed": False}
        
    except Exception as e:
        logger.error(f"Error during upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
async def list_documents(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    docs = db.query(UserDocument).filter(UserDocument.user_id == user_id).all()
    return {"documents": [{"name": d.filename, "id": d.id, "indexed": d.indexed} for d in docs]}

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
        rag_service.delete_document(db_doc.filename, user_id)
        
        # 2. Delete from storage (Supabase or local)
        if storage_service.client and not os.path.isabs(db_doc.file_path):
            # If path is NOT absolute, it's a Supabase path
            storage_service.delete_file(db_doc.file_path)
        elif os.path.exists(db_doc.file_path):
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
async def summarize_document(
    file_name: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    # This is a robust summarization logic
    # We query for the most representative chunks
    logger.info(f"User {user_id} requesting summary for: {file_name}")
    
    prompt = f"Summarize the core contents and key takeaways of the document: {file_name}"
    try:
        from fastapi.concurrency import run_in_threadpool
        docs = await run_in_threadpool(rag_service.query, prompt, user_id, k=10)
    except Exception as e:
        logger.error(f"Error retrieving chunks for summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve document content for summarization")
        
    if not docs:
        return {"summary": "No content found for this document. Please ensure it is uploaded and indexed."}
        
    context = "\n\n".join([doc.page_content for doc in docs])
    
    summary_prompt = (
        f"You are a research assistant. Provide a comprehensive 3-paragraph summary of the following document content. "
        f"Focus on the main themes, key data points, and conclusions.\n\n"
        f"Context:\n{context}\n\n"
        f"Summary:"
    )
    
    try:
        summary = await llm_service.generate_response(summary_prompt, "")
        return {"summary": summary}
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate summary")

@app.get("/health")
async def health_check():
    from sqlalchemy import text
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
