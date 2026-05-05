# 🚀 ContextIQ Deployment Guide

Follow these steps to deploy ContextIQ to production using **Render** for the backend and **Vercel** for the frontend.

---

## 1. Backend Deployment (Render)

Render is ideal for hosting the FastAPI backend.

### Prerequisites
- Create a [Render](https://render.com/) account.
- Push your code to a GitHub/GitLab repository.

### Steps
1. **Create a New Web Service**:
   - Connect your GitHub repository.
   - Set **Name**: `contextiq-backend`.
   - Set **Environment**: `Python 3`.
   - Set **Build Command**: `pip install -r backend/app/requirements.txt`.
   - Set **Start Command**: `gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.app.main:app`.

2. **Configure Environment Variables**:
   Add the following in the Render "Environment" tab:
   - `DATABASE_URL`: Your Supabase connection string.
   - `GROQ_API_KEY`: Your Groq API key.
   - `CHROMA_API_KEY`: Your Chroma Cloud API key.
   - `CHROMA_TENANT`: Your Chroma Tenant ID.
   - `CHROMA_DATABASE`: `GoogleNotebooklm`.
   - `SECRET_KEY`: A long, random string for JWT security.
   - `PYTHON_VERSION`: `3.10` (recommended).

3. **Deploy**: Render will automatically build and deploy your backend. Note down your backend URL (e.g., `https://contextiq-backend.onrender.com`).

---

## 2. Frontend Deployment (Vercel)

Vercel is the best platform for React/Vite applications.

### Prerequisites
- Create a [Vercel](https://vercel.com/) account.

### Steps
1. **Import Project**:
   - Connect your GitHub repository.
   - Select the root folder of the project.
   - Select **Framework Preset**: `Vite`.
   - **Root Directory**: `frontend`.

2. **Configure Environment Variables**:
   Add the following in the Vercel "Environment Variables" section:
   - `VITE_API_BASE_URL`: The URL of your Render backend (e.g., `https://contextiq-backend.onrender.com`).

3. **Deploy**: Click **Deploy**. Vercel will build your project and provide a production URL.

---

## 3. Post-Deployment Checks

1. **Update CORS in Backend**:
   - Go back to `backend/app/main.py`.
   - Ensure `allow_origins` includes your new Vercel URL.
   - Example:
     ```python
     allow_origins=[
         "https://contextiq.vercel.app",
         "http://localhost:5173"
     ]
     ```
   - Commit and push the change; Render will redeploy automatically.

2. **Test Auth**:
   - Visit your Vercel URL.
   - Try to Register and Login.
   - Verify that your chat history and documents are preserved across sessions.

---

## 🛠 Troubleshooting

- **Backend Logs**: If the backend fails to start, check the Render logs for missing dependencies or env var errors.
- **CORS Errors**: If you see "CORS error" in the browser console, double-check that the `VITE_API_BASE_URL` in Vercel exactly matches the URL in the backend's `allow_origins`.
- **Large Files**: Render's free tier has limits on RAM and disk. For very large PDF processing, consider upgrading or using a background worker.
