# Use Python 3.11 stable
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000

# SET THE PYTHON PATH (This is the fix!)
# It tells the server to look inside the 'app' folder for your modules
ENV PYTHONPATH=/app/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first
COPY app/requirements.txt ./app/
RUN pip install --no-cache-dir -r ./app/requirements.txt

# Copy all code into the /app/app folder
COPY app/ ./app/

# Create data directory
RUN mkdir -p data/uploads

# Start the application using 'app.main:app'
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
