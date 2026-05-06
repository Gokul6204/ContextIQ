# ContextIQ (Noteboolm) 🚀

ContextIQ is a premium, cloud-native AI research assistant that allows you to upload documents, generate summaries, and chat with your data using Retrieval-Augmented Generation (RAG).

## 🌟 Features

- **Cloud Document Storage**: Files are stored securely in **Supabase Storage**.
- **Persistent Vector Search**: Powered by **Chroma Cloud** for lightning-fast, high-dimensional search.
- **RAG-based Chat**: Get precise answers with citations from your documents using **Groq (Llama-3)**.
- **Smart Summarization**: Generate instant, structured summaries of any uploaded source.
- **Hybrid Embedding Engine**: Uses local **Ollama** (`all-minilm`) with automatic fallback to **Hugging Face** APIs.
- **Modern UI**: Sleek glassmorphism interface with real-time indexing status indicators.

## 🛠️ Tech Stack

- **Backend**: FastAPI, LangChain, SQLAlchemy (Postgres).
- **Storage**: Supabase Storage & Supabase Postgres.
- **Vector DB**: Chroma Cloud.
- **LLM & Embeddings**: Groq, Ollama, Hugging Face.
- **Frontend**: React, Vite, Vanilla CSS.

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.com/) (running `all-minilm` model).

### 2. Environment Setup

Create a `.env` file in the `backend` directory:

```env
# Database
DATABASE_URL=postgresql+psycopg://...

# API Keys
GROQ_API_KEY=your_groq_key
HF_TOKEN=your_huggingface_token

# Chroma Cloud
CHROMA_API_KEY=your_chroma_key
CHROMA_TENANT=your_tenant_id
CHROMA_DATABASE=your_db_name

# Supabase Storage
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_jwt_key
SUPABASE_BUCKET=documents
```

### 3. Installation

**Backend**:
```bash
cd backend/app
pip install -r requirements.txt
python main.py
```

**Frontend**:
```bash
cd frontend
npm install
npm run dev
```

## 🌍 Deployment

### Backend (Render)
1. Use the **Python** runtime.
2. Set the start command: `gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:$PORT`
3. Add all `.env` variables to Render Environment secrets.

### Frontend (Vercel)
1. Connect your GitHub repo.
2. Set `VITE_API_BASE_URL` to your Render backend URL.
3. Deploy!

## 📝 License
MIT
