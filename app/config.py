import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    falkordb_graph: str = os.getenv("FALKORDB_GRAPH", "MedGraph")
    falkordb_password: str | None = os.getenv("FALKORDB_PASSWORD") or None
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    report_storage_dir: Path = Path(
        os.getenv(
            "REPORT_STORAGE_DIR",
            str(Path(__file__).resolve().parent.parent / "uploads" / "reports"),
        )
    ).expanduser()
    api_base_url: str = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
    allowed_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(",")
        if origin.strip()
    )


settings = Settings()
