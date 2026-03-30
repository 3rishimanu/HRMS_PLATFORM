import uuid
import os
from fastapi import UploadFile


async def upload_file(file: UploadFile, folder: str = "documents") -> str:
    """Store uploaded files locally and return a public URL path."""
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", folder)
    os.makedirs(upload_dir, exist_ok=True)
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ""
    filename = f"{uuid.uuid4().hex}{file_ext}"
    filepath = os.path.join(upload_dir, filename)
    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)
    return f"/uploads/{folder}/{filename}"
