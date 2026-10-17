
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "change-this-development-secret",
    )

    OLLAMA_BASE_URL = os.getenv(
        "OLLAMA_BASE_URL",
        "http://localhost:11434",
    ).rstrip("/")

    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
    OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))

    MAX_CONTENT_LENGTH = 12 * 1024 * 1024

    # Explicitly tell Flask where the project directories are.
    TEMPLATE_FOLDER = str(PROJECT_ROOT / "templates")
    STATIC_FOLDER = str(PROJECT_ROOT / "static")

    BUSINESS_DATA_DIRECTORY = PROJECT_ROOT / "data" / "business"
    RECORDS_DIRECTORY = PROJECT_ROOT / "data" / "records"
