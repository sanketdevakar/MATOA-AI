"""Notes MCP Tool — write sitrep reports"""
import httpx
import uuid
from config import get_settings

settings = get_settings()


def write_note(title: str, body: str, tags: list[str] = None) -> str:
    """
    Write a note to the Notes MCP.
    Returns the note ID (or mock ID on fallback).
    """
    payload = {
        "title": title,
        "content": body,
        "tags": tags or [],
        "pinned": True,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{settings.notes_mcp_url}/tools/create_note",
                json={"parameters": payload},
                headers={"Authorization": f"Bearer {settings.commander_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("id") or f"note_{uuid.uuid4().hex[:8]}"

    except Exception as e:
        print(f"[NotesMCP] Fallback to mock (error: {e})")
        return f"MOCK-NOTE-{uuid.uuid4().hex[:8]}"
