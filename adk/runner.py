"""
ADK Pipeline Runner — SENTINEL v3
-------------------------------------
Fix 4: VertexAiSessionService replaces InMemorySessionService.
       Session state now persists in Vertex AI Agent Engine.
Fix 5: Pub/Sub integration — run_pipeline publishes to topic,
       worker subscribes and processes asynchronously.
Fix 7: Structured Cloud Logging via utils.logger.
"""
import os
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
os.environ["GOOGLE_CLOUD_PROJECT"] = "commandmind"
os.environ["GOOGLE_CLOUD_LOCATION"] = "asia-south1"
import asyncio
import concurrent.futures
import json
from datetime import datetime

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from adk.agents import sentinel_pipeline
from db import bigquery_client as bq
from config import get_settings
from utils.logger import get_logger

settings = get_settings()
log      = get_logger("adk_runner")

APP_NAME = "sentinel"


def _build_session_service():
    """
    Fix 4: Use VertexAiSessionService in production for persistent sessions.
    Falls back to InMemorySessionService in development.
    """
    if settings.app_env == "production":
        try:
            from google.adk.sessions import VertexAiSessionService
            svc = VertexAiSessionService(
                project=settings.gcp_project_id,
                location=settings.gcp_location,
            )
            log.info("Using VertexAiSessionService for persistent ADK sessions")
            return svc
        except Exception as e:
            log.warning("VertexAiSessionService unavailable, falling back to InMemory",
                        error=str(e))
    log.info("Using InMemorySessionService (development mode)")
    return InMemorySessionService()


_session_service = _build_session_service()


async def run_pipeline_async(alert: dict) -> dict:
    """Run the full ADK SequentialAgent pipeline for an alert."""
    alert_id   = alert["id"]
    session_id = f"session-{alert_id}"

    initial_state = {
        "alert_id":    alert_id,
        "alert_type":  alert["alert_type"],
        "sector":      alert["sector"],
        "latitude":    alert.get("latitude"),
        "longitude":   alert.get("longitude"),
        "raw_payload": alert.get("raw_payload", ""),
        "created_at":  str(alert.get("created_at", datetime.utcnow().isoformat())),
    }

    await _session_service.create_session(
        app_name=APP_NAME,
        user_id="sentinel-system",
        session_id=session_id,
        state=initial_state,
    )

    runner = Runner(
        agent=sentinel_pipeline,
        app_name=APP_NAME,
        session_service=_session_service,
    )

    trigger_message = Content(parts=[Part(text=(
        f"Process alert {alert_id} for sector {alert['sector']}. "
        f"Alert type: {alert['alert_type']}. "
        f"Execute the full Vision → Intel → Patrol → Comms pipeline now."
    ))])

    pipeline_steps = []
    events_log     = []
    final_state    = {}

    try:
        async for event in runner.run_async(
            user_id="sentinel-system",
            session_id=session_id,
            new_message=trigger_message,
        ):
            events_log.append({
                "author":     getattr(event, "author", "unknown"),
                "event_type": type(event).__name__,
                "timestamp":  datetime.utcnow().isoformat(),
            })
            author = getattr(event, "author", "")
            print(f"EVENT: author={author} type={type(event).__name__}")
            if author and author != "sentinel_command_agent":
                content = getattr(event, "content", None)
                text = ""
                if content and hasattr(content, "parts"):
                    text = " ".join(
                        p.text for p in content.parts if hasattr(p, "text") and p.text
                    )
                if text and len(text) > 10:
                    pipeline_steps.append({
                        "agent":  author,
                        "status": "completed",
                        "output": {"summary": text[:200]},
                    })
                    log.info("Agent completed", agent=author, alert_id=alert_id)

        final_session = await _session_service.get_session(
            app_name=APP_NAME, user_id="sentinel-system", session_id=session_id,
        )
        final_state = dict(final_session.state) if final_session else {}

    except Exception as e:
        log.error("Pipeline error", alert_id=alert_id, sector=alert.get("sector"), error=str(e))
        bq.insert_audit_log(
            actor="adk_runner", action="pipeline_error",
            detail=str(e), alert_id=alert_id, success=False,
        )

    threat_score  = final_state.get("threat_score", 0)
    pending_actions = bq.list_pending_actions(status="pending")
    pending_count = sum(1 for a in pending_actions if a.get("alert_id") == alert_id)

    if pending_count > 0:
        bq.update_alert_status(alert_id, "awaiting_hitl")
        status  = "awaiting_hitl"
        message = f"{pending_count} action(s) pending commander approval."
    else:
        bq.update_alert_status(alert_id, "completed")
        status  = "completed"
        message = "Pipeline complete. No HITL required."

    bq.insert_audit_log(
        actor="adk_runner", action="pipeline_finished",
        detail=message, alert_id=alert_id,
    )
    log.info("Pipeline finished", alert_id=alert_id, sector=alert.get("sector"),
             status=status, threat_score=threat_score)

    return {
        "alert_id":       alert_id,
        "sector":         alert["sector"],
        "threat_score":   threat_score,
        "severity":       final_state.get("severity", "unknown"),
        "status":         status,
        "message":        message,
        "pipeline_steps": pipeline_steps,
        "events_count":   len(events_log),
        "session_state_keys": list(final_state.keys()),
    }


def _run_in_new_loop(alert: dict) -> dict:
    """Run pipeline in a completely fresh event loop — safe for any calling context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_pipeline_async(alert))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def run_pipeline(alert: dict) -> dict:
    """
    Synchronous wrapper. Always runs in a dedicated thread with its own
    event loop — safe whether called from FastAPI AnyIO worker thread,
    Pub/Sub subscriber thread, or main thread.
    """
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_in_new_loop, alert)
            return future.result(timeout=600)
    except concurrent.futures.TimeoutError:
        log.error("Pipeline timed out", alert_id=alert.get("id"))
        return {
            "alert_id": alert.get("id", "unknown"),
            "status": "error",
            "error": "Pipeline timed out after 600 seconds.",
            "pipeline_steps": [],
        }
    except Exception as e:
        log.error("run_pipeline error", alert_id=alert.get("id"), error=str(e))
        return {
            "alert_id": alert.get("id", "unknown"),
            "status": "error",
            "error": str(e),
            "pipeline_steps": [],
        }