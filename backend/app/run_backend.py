import uvicorn
import os
import sys

# Get the absolute path of the directory containing this script (app directory)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (backend directory)
backend_dir = os.path.dirname(current_dir)

# Add the backend directory to sys.path so we can import 'app'
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
