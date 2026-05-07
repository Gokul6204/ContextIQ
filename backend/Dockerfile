# Use Python 3.11 stable
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000

WORKDIR /app

# Install basic system dependencies for Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (for better caching)
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY app/ ./app/

# Create the data directory for local file storage fallback
RUN mkdir -p data/uploads

# Start the application
# We use 'app.main:app' because we are running from the /app folder
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
