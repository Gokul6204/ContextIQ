import uvicorn
import os
import sys
import socket
import logging
import subprocess

# Setup basic logging for the runner
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BackendRunner")

# Get the absolute path of the directory containing this script (app directory)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (backend directory)
backend_dir = os.path.dirname(current_dir)

if backend_dir not in sys.path:
    sys.path.append(backend_dir)

def kill_port_owner(port):
    """Attempt to kill the process listening on a specific port (Windows only)"""
    try:
        # Find PID using netstat
        output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode()
        for line in output.strip().split('\n'):
            if "LISTENING" in line:
                pid = line.strip().split()[-1]
                if pid != "0":
                    logger.info(f"Killing process {pid} on port {port}...")
                    subprocess.run(f"taskkill /F /PID {pid} /T", shell=True, capture_output=True)
                    return True
    except Exception:
        pass
    return False

def check_db_connection():
    """Test the Supabase connection before starting uvicorn"""
    try:
        from app.models import engine
        from sqlalchemy import text
        logger.info("Testing Database connection...")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database connection successful.")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        if "getaddrinfo failed" in str(e):
            logger.error("   TIP: This usually means your machine cannot resolve the database hostname.")
            logger.error("   Check your internet connection or DNS settings.")
        return False

if __name__ == "__main__":
    logger.info("--- ContextIQ Backend Diagnostics ---")
    
    # 1. Clear the port if it's stuck
    port = int(os.environ.get("PORT", 8000))
    if kill_port_owner(port):
        logger.info(f"Port {port} cleared.")

    # 2. Check DB
    if not check_db_connection():
        logger.error("Startup aborted due to Database failure.")
        sys.exit(1)

    # 3. Start Uvicorn
    logger.info(f"Starting Uvicorn on 0.0.0.0:{port}...")
    try:
        uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
    except Exception as e:
        logger.error(f"Uvicorn failed to start: {e}")
        sys.exit(1)
