"""Task Manager MCP Tool — create duty assignments"""
import httpx
import uuid
from datetime import datetime, timedelta
from config import get_settings

settings = get_settings()


def create_task(
    title: str,
    description: str,
    priority: str = "medium",
    due_offset_hours: int = 2,
) -> str:
    """
    Create a task via Task Manager MCP.
    Returns the task ID (or mock ID on fallback).
    """
    due_at = (datetime.utcnow() + timedelta(hours=due_offset_hours)).isoformat()

    payload = {
        "title": title,
        "notes": description,
        "due": due_at,
        "priority": priority,
        "status": "needsAction",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{settings.tasks_mcp_url}/tools/create_task",
                json={"parameters": payload},
                headers={"Authorization": f"Bearer {settings.commander_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("id") or f"task_{uuid.uuid4().hex[:8]}"

    except Exception as e:
        print(f"[TasksMCP] Fallback to mock (error: {e})")
        return f"MOCK-TASK-{uuid.uuid4().hex[:8]}"
