
import os
from supabase import create_client, Client
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.bucket = os.getenv("SUPABASE_BUCKET", "documents")
        
        if self.url and self.key:
            try:
                self.client: Client = create_client(self.url, self.key)
                logger.info("  Supabase Storage client initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                self.client = None
        else:
            logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY missing. Local storage will be used as fallback.")
            self.client = None

    def upload_file(self, local_path, remote_path):
        if not self.client:
            logger.error("Supabase client not initialized.")
            return False
        
        try:
            with open(local_path, 'rb') as f:
                # remote_path should be like 'user_3/knowledge.pdf'
                self.client.storage.from_(self.bucket).upload(
                    path=remote_path,
                    file=f,
                    file_options={"upsert": "true"}
                )
            logger.info(f"  Uploaded {local_path} to Supabase as {remote_path}")
            return True
        except Exception as e:
            logger.error(f"  Supabase Upload Failed: {e}")
            return False

    def download_file(self, remote_path, local_path):
        if not self.client:
            return False
        
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            res = self.client.storage.from_(self.bucket).download(remote_path)
            with open(local_path, 'wb') as f:
                f.write(res)
            logger.info(f"  Downloaded {remote_path} from Supabase to {local_path}")
            return True
        except Exception as e:
            logger.error(f"  Supabase Download Failed: {e}")
            return False

    def delete_file(self, remote_path):
        if not self.client:
            return False
        
        try:
            self.client.storage.from_(self.bucket).remove([remote_path])
            logger.info(f"  Deleted {remote_path} from Supabase.")
            return True
        except Exception as e:
            logger.error(f"  Supabase Deletion Failed: {e}")
            return False
