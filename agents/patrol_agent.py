"""
Patrol Agent — BigQuery + Cloud Logging version
Fix 7: Structured logging replaces all print() calls.
"""
import json
from datetime import datetime, timedelta, timezone
from db import bigquery_client as bq
from mcp_tools.calendar_tool import create_patrol_event
from config import get_settings
from utils.logger import get_logger
from google import genai
from google.genai import types

settings = get_settings()
client = genai.Client(
    vertexai=True,
    project=settings.gcp_project_id,
    location=settings.gcp_location,
)
log = get_logger("patrol_agent")

SYSTEM_PROMPT = """You are the Patrol Agent for SENTINEL, an Indian Army surveillance system.
Based on a threat assessment, decide whether to modify patrol schedules.

ALWAYS respond with valid JSON only. Schema:
{
  "action_required": <true|false>,
  "action_type": "<reschedule_patrol|add_patrol|cancel_patrol|no_change>",
  "unit_to_assign": "<unit name>",
  "patrol_start_offset_hours": <integer>,
  "patrol_duration_hours": <integer>,
  "route_notes": "<brief instructions>",
  "description": "<one sentence summary for commander>"
}
Rules: score 1-4 → no_change. score 5-7 → reschedule. score 8+ → add_patrol immediately."""


def propose(alert: dict, assessment: dict) -> dict | None:
    log.info("Proposing patrol action",
             alert_id=alert["id"], sector=alert["sector"],
             threat_score=assessment["threat_score"])

    user_msg = f"""
THREAT ASSESSMENT:
  Sector       : {alert['sector']}
  Threat score : {assessment['threat_score']}/10
  Severity     : {assessment['severity']}
  Reasoning    : {assessment['reasoning']}
  Recommended  : {assessment['recommended_response']}
Current time UTC: {datetime.now(timezone.utc).isoformat()}
Propose a patrol scheduling action.
"""
    try:
        resp = client.models.generate_content(
        model=settings.gemini_model,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=1500,
            temperature=0.2,
    ),
)
        text = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        proposal = json.loads(text)
    except Exception as e:
        log.error("Patrol proposal failed",
                  alert_id=alert["id"], sector=alert["sector"], error=str(e))
        bq.insert_audit_log(actor="patrol_agent", action="proposal_failed",
                             detail=str(e), alert_id=alert["id"], success=False)
        return None

    if not proposal.get("action_required"):
        log.info("No patrol change required",
                 alert_id=alert["id"], sector=alert["sector"],
                 threat_score=assessment["threat_score"])
        bq.insert_audit_log(actor="patrol_agent", action="no_change_required",
                             detail="Score below patrol threshold.", alert_id=alert["id"])
        return None

    start_dt = datetime.now(timezone.utc) + timedelta(hours=proposal.get("patrol_start_offset_hours", 1))
    end_dt   = start_dt + timedelta(hours=proposal.get("patrol_duration_hours", 2))

    mcp_payload = {
        "sector":      alert["sector"],
        "unit":        proposal["unit_to_assign"],
        "start_iso":   start_dt.isoformat(),
        "end_iso":     end_dt.isoformat(),
        "route_notes": proposal["route_notes"],
        "alert_id":    alert["id"],
    }

    action = bq.insert_pending_action(
        alert_id=alert["id"],
        agent_name="patrol_agent",
        action_type=proposal["action_type"],
        description=proposal["description"],
        payload=mcp_payload,
    )
    bq.insert_audit_log(actor="patrol_agent", action="pending_action_created",
                         detail=proposal["description"], alert_id=alert["id"])

    log.info("Pending action created",
             alert_id=alert["id"], sector=alert["sector"],
             action_type=proposal["action_type"],
             action_id=action["id"])
    return action


def execute_approved_action(action: dict) -> bool:
    log.info("Executing approved patrol action",
             action_id=action["id"], alert_id=action.get("alert_id"))
    try:
        payload  = json.loads(action["payload"]) if isinstance(action["payload"], str) else action["payload"]
        event_id = create_patrol_event(
            sector=payload["sector"], unit=payload["unit"],
            start_iso=payload["start_iso"], end_iso=payload["end_iso"],
            route_notes=payload.get("route_notes", ""),
        )
        bq.insert_patrol_log(
            alert_id=action["alert_id"], sector=payload["sector"],
            patrol_start=payload["start_iso"], patrol_end=payload["end_iso"],
            unit_assigned=payload["unit"], route_notes=payload.get("route_notes", ""),
            calendar_event_id=event_id,
        )
        bq.mark_action_executed(action["id"])
        bq.insert_audit_log(actor="patrol_agent", action="calendar_event_created",
                             detail=f"Event ID: {event_id}", alert_id=action["alert_id"])
        log.info("Calendar event created",
                 action_id=action["id"], calendar_event_id=event_id)
        return True
    except Exception as e:
        bq.mark_action_failed(action["id"])
        bq.insert_audit_log(actor="patrol_agent", action="execution_failed",
                             detail=str(e), alert_id=action["alert_id"], success=False)
        log.error("Patrol execution failed",
                  action_id=action["id"], error=str(e))
        return False
