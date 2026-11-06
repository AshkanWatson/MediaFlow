"""ASGI entrypoint:  uvicorn app:app --host 127.0.0.1 --port 8000"""
from core.api import create_app

app = create_app()
