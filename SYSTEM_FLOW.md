# PDF Upload and RAG Processing Flow

## Complete System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                         │
│                                                                  │
│  1. User clicks "+" button                                      │
│  2. Selects PDF file                                            │
│  3. handleFileUpload() creates FormData                         │
│  4. POST to http://localhost:8000/upload                        │
│  5. Shows progress bar (0% → 90% → 100%)                        │
│  6. Displays success/error message in chat                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    HTTP POST /upload
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND (FastAPI) - main.py                   │
│                                                                  │
│  1. Receive UploadFile                                          │
│     LOG: "Received upload request for file: {filename}"         │
│                                                                  │
│  2. Save to disk                                                │
│     Path: E:\GoogleNoteboolm\backend\data\uploads\{filename}    │
│     LOG: "Saving file to: {file_path}"                          │
│     LOG: "File saved successfully"                              │
│                                                                  │
│  3. Process document (DocumentService)                          │
│     LOG: "Processing PDF: {filename}"                           │
│     ↓                                                            │
│     ┌─────────────────────────────────────────────────┐        │
│     │      DocumentService.process_pdf()              │        │
│     │                                                  │        │
│     │  - PyMuPDFLoader loads PDF                      │        │
│     │  - RecursiveCharacterTextSplitter splits text   │        │
│     │    • chunk_size: 1000 chars                     │        │
│     │    • chunk_overlap: 100 chars                   │        │
│     │  - Returns List[Document]                       │        │
│     └─────────────────────────────────────────────────┘        │
│     ↓                                                            │
│     LOG: "Document processed into {N} chunks"                   │
│                                                                  │
│  4. Add to RAG system (RAGService)                              │
│     LOG: "Documents added to RAG system successfully"           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   RAGService.add_documents()                     │
│                                                                  │
│  LOG: "Adding {N} documents to Chroma Cloud"                    │
│                                                                  │
│  1. Generate embeddings (Ollama / Fallback)                      │
│     ┌─────────────────────────────────────────────────┐        │
│     │      OllamaEmbeddings / HF Fallback              │        │
│     │      model: "all-minilm"                         │        │
│     │                                                  │        │
│     │  For each chunk:                                │        │
│     │    text → embedding vector (384 dimensions)     │        │
│     └─────────────────────────────────────────────────┘        │
│                                                                  │
│  2. Store in Chroma Cloud                                       │
│     LOG: "Connecting to Chroma Cloud collection"                │
│     LOG: "Successfully indexed {filename} in Chroma"            │
└─────────────────────────────────────────────────────────────────┘
│     OR                                                           │
│     LOG: "Adding to existing FAISS index"                       │
│                                                                  │
│  3. Persist to disk                                             │
│     Path: E:\GoogleNoteboolm\backend\faiss_index\               │
│     LOG: "Saving FAISS index to {path}"                         │
│     LOG: "FAISS index saved successfully"                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    Return success response
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                         │
│                                                                  │
│  1. Receives response:                                          │
│     {                                                            │
│       "message": "Successfully uploaded and indexed...",        │
│       "chunks": 45,                                             │
│       "file_path": "E:\GoogleNoteboolm\backend\..."            │
│     }                                                            │
│                                                                  │
│  2. Updates UI:                                                 │
│     - Progress bar → 100%                                       │
│     - Adds to sources list                                      │
│     - Shows success message in chat                             │
│       "✅ Successfully uploaded and indexed knowledge.pdf       │
│        (45 chunks created)"                                     │
└─────────────────────────────────────────────────────────────────┘
```

## Query Flow (After Upload)

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                         │
│                                                                  │
│  1. User types question                                         │
│  2. handleSend() sends POST to /query                           │
│     Body: { "prompt": "What is...?" }                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND - main.py /query                      │
│                                                                  │
│  1. RAGService.query(prompt)                                    │
│     ┌─────────────────────────────────────────────────┐        │
│     │  Chroma Cloud similarity search                  │        │
│     │  - Convert query to embedding                    │        │
│     │  - Find top 10 most similar chunks               │        │
│     │  - Return List[Document]                         │        │
│     └─────────────────────────────────────────────────┘        │
│                                                                  │
│  2. Build context from retrieved documents                      │
│     context = "\n\n".join([doc.page_content for doc in docs])   │
│                                                                  │
│  3. LLMService.generate_response(prompt, context)               │
│     ┌─────────────────────────────────────────────────┐        │
│     │  Groq LLM (Llama-3)                              │        │
│     │                                                  │        │
│     │  Prompt Template:                                │        │
│     │  "You are an AI research assistant...           │        │
│     │   Context: {context}                             │        │
│     │   Question: {question}                           │        │
│     │   Answer:"                                       │        │
│     │                                                  │        │
│     │  → Generated answer                              │        │
│     └─────────────────────────────────────────────────┘        │
│                                                                  │
│  4. Return QueryResponse                                        │
│     {                                                            │
│       "answer": "Based on the documents...",                    │
│       "sources": ["knowledge.pdf"]                              │
│     }                                                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                         │
│                                                                  │
│  1. Displays AI response in chat                                │
│  2. Shows source badges below answer                            │
└─────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Document Processing
1. **Upload Phase**:
   - User uploads file via Frontend.
   - Backend saves file to **Supabase Storage** (Bucket: `documents`).
   - Metadata is recorded in **Supabase Postgres**.

2.  **Indexing Phase (Background)**:
   - Worker downloads file from Supabase.
   - Text is extracted and chunked (800 chars).
   - Embeddings generated via **Ollama** (`all-minilm`).
   - Vectors stored in **Chroma Cloud**.
   - DB record marked as `indexed = True`.

3.  **Query Phase**:
   - User sends message.
   - Query embedded and searched in **Chroma Cloud**.
   - Context + Message sent to **Groq LLM** (Llama-3).

### 2. Embeddings
- **Model**: all-minilm (via Ollama)
- **Purpose**: Convert text to vector representations
- **Dimension**: 384-dimensional
### 3. Vector Storage
- **Chroma Cloud**: Hosted vector database
- **Collection**: `contextiq_v1`
- **Purpose**: High-dimensional vector search for context retrieval

### 4. LLM
- **Model**: Llama-3 (via Groq Cloud)
- **Temperature**: 0.1 (low for factual responses)
- **Max tokens**: 2048
- **Purpose**: Generate answers based on context

## Error Handling

### Upload Errors
1. **File save fails** → HTTP 500 with detailed error
2. **Unsupported file type** → HTTP 400 "Please upload PDF or TXT"
3. **PDF processing fails** → HTTP 500 with PyMuPDF error
4. **Embedding fails** → HTTP 500 with Ollama error
5. **Chroma save fails** → HTTP 500 with Cloud API error

All errors are:
- Logged to backend console with stack traces
- Returned to frontend with detailed messages
- Displayed in chat UI with ❌ emoji

### Query Errors
1. **No documents indexed** → Returns empty context
2. **Groq API Down** → Connection error fallback
3. **Ollama not running** → Connection error (for embeddings)

## Logging Levels

### INFO logs show:
- Upload directory path
- FAISS index directory path
- File received and saved
- Processing steps
- Chunk counts
- FAISS operations
- HTTP requests

### ERROR logs show:
- Exception details
- Stack traces
- Failed operations

## File Structure

```
E:\GoogleNoteboolm\
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI endpoints
│   │   ├── document_service.py  # PDF/text processing
│   │   ├── rag_service.py       # Vector DB operations
│   │   ├── llm_service.py       # LLM interactions
│   │   └── storage_service.py   # Supabase Storage logic
│   └── requirements.txt
├── frontend/
│   └── src/
│       └── App.jsx              # React UI
└── run_backend.py               # Server launcher
```
