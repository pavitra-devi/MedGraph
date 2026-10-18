from pathlib import Path, PurePosixPath
from uuid import UUID

from app.config import settings

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".csv"}


def safe_original_filename(filename: str | None) -> str:
    basename = PurePosixPath((filename or "").replace("\\", "/")).name
    safe_name = "".join(
        character
        for character in basename
        if character.isprintable() and character not in "\r\n"
    )
    return safe_name or "medical-report"


def _attachment_path(attachment_id: str, filename: str) -> Path:
    canonical_id = str(UUID(attachment_id))
    suffix = Path(safe_original_filename(filename)).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported medical report file extension.")
    return settings.report_storage_dir / f"{canonical_id}{suffix}"


def save_attachment(attachment_id: str, filename: str, content: bytes) -> Path:
    destination = _attachment_path(attachment_id, filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def find_attachment(attachment_id: str, filename: str) -> Path:
    return _attachment_path(attachment_id, filename)


def remove_attachment(attachment_id: str, filename: str) -> None:
    path = _attachment_path(attachment_id, filename)
    if path.exists():
        path.unlink()
