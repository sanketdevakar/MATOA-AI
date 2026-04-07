"""
SENTINEL — Entry Point
Run with: python main.py
Or:        uvicorn main:app --reload --port 8000
"""
import uvicorn
from api.main import app   # noqa: F401  (imported for uvicorn)

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
