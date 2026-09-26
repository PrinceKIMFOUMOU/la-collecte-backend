import os
from dotenv import load_dotenv # type: ignore
from supabase import create_client, Client # type: ignore

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    raise RuntimeError("Configuration Supabase absente du fichier .env")

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)