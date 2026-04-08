"""
SENTINEL — Entry Point
Run locally : python main.py
Cloud Run   : uvicorn api.main:app --host 0.0.0.0 --port 8080
"""
import os
import uvicorn
from api.main import app  # noqa: F401

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    reload = os.environ.get("APP_ENV", "development") == "development"

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
        log_level="info",
    )
