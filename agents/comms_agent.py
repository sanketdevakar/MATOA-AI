"""
Comms Agent — BigQuery + Cloud Logging version
Fix 7: Structured logging replaces all print() calls.
"""
import json
from db import bigquery_client as bq
from mcp_tools.notes_tool import write_note
from mcp_tools.tasks_tool import create_task
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
log   = get_logger("comms_agent")

SYSTEM_PROMPT = """You are the Comms Agent for SENTINEL, an Indian Army surveillance system.
Write situation reports in professional Indian Army style.

ALWAYS respond with valid JSON only. Schema:
{
  "sitrep_title": "<short title>",
  "summary": "<3-4 sentences: what, where, when, assessment>",
  "recommended_actions": "<2-3 bullet points>",
  "duty_officer_task": "<one sentence: immediate action for duty officer>",
  "classification": "<ROUTINE|PRIORITY|IMMEDIATE|FLASH>"
}
FLASH=score>=9, IMMEDIATE=7-8, PRIORITY=5-6, ROUTINE=1-4."""


def propose(alert: dict, assessment: dict) -> dict | None:
    log.info("Drafting sitrep",
             alert_id=alert["id"], sector=alert["sector"],
             threat_score=assessment["threat_score"])

    user_msg = f"""
ALERT:
  ID     : {alert['id']}
  Type   : {alert['alert_type']}
  Sector : {alert['sector']}
  Time   : {alert['created_at']}
INTEL:
  Score  : {assessment['threat_score']}/10
  Sev    : {assessment['severity']}
  Reason : {assessment['reasoning']}
  History: {assessment.get('historical_context', 'N/A')}
Draft sitrep now.
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
        sitrep = json.loads(text)
        # Normalize in case Gemini returns a list instead of string
        if isinstance(sitrep.get("recommended_actions"), list):
            sitrep["recommended_actions"] = "\n".join(sitrep["recommended_actions"])
    except Exception as e:
        log.error("Sitrep draft failed",
                  alert_id=alert["id"], sector=alert["sector"], error=str(e))
        sitrep = {
            "sitrep_title": f"SITREP - {alert['sector']} - ERROR",
            "summary": f"Comms Agent error: {e}. Manual sitrep required.",
            "recommended_actions": "Manual review required.",
            "duty_officer_task": "Generate manual sitrep immediately.",
            "classification": "PRIORITY",
        }

    draft_id = bq.insert_sitrep_draft(
        alert_id=alert["id"], sector=alert["sector"],
        threat_score=assessment["threat_score"],
        summary=sitrep["summary"],
        recommended_actions=sitrep["recommended_actions"],
    )
    log.info("Sitrep draft saved",
             alert_id=alert["id"], draft_id=draft_id,
             classification=sitrep["classification"])

    if assessment["threat_score"] <= 4:
        _publish_directly(draft_id, sitrep, alert)
        return None

    mcp_payload = {
        "draft_id":          draft_id,
        "title":             sitrep["sitrep_title"],
        "body":              sitrep["summary"] + "\n\n" + sitrep["recommended_actions"],
        "classification":    sitrep["classification"],
        "duty_officer_task": sitrep["duty_officer_task"],
        "alert_id":          alert["id"],
    }
    action = bq.insert_pending_action(
        alert_id=alert["id"], agent_name="comms_agent",
        action_type="publish_sitrep",
        description=f"Publish {sitrep['classification']} sitrep: {sitrep['sitrep_title']}",
        payload=mcp_payload,
    )
    bq.insert_audit_log(actor="comms_agent", action="sitrep_drafted",
                         detail=f"Classification: {sitrep['classification']}",
                         alert_id=alert["id"])
    log.info("Sitrep pending HITL approval",
             alert_id=alert["id"], action_id=action["id"],
             classification=sitrep["classification"])
    return action


def execute_approved_action(action: dict) -> bool:
    log.info("Publishing approved sitrep",
             action_id=action["id"], alert_id=action.get("alert_id"))
    try:
        payload = json.loads(action["payload"]) if isinstance(action["payload"], str) else action["payload"]
        note_id = write_note(
            title=payload["title"], body=payload["body"],
            tags=["sitrep", payload["classification"].lower()],
        )
        task_id = create_task(
            title=f"ACTION REQUIRED: {payload['title']}",
            description=payload["duty_officer_task"],
            priority="high" if payload["classification"] in ("IMMEDIATE", "FLASH") else "medium",
        )
        bq.update_sitrep_notes_id(payload["draft_id"], note_id)
        bq.mark_action_executed(action["id"])
        bq.insert_audit_log(actor="comms_agent", action="sitrep_published",
                             detail=f"Note={note_id} Task={task_id}",
                             alert_id=action["alert_id"])
        log.info("Sitrep published",
                 action_id=action["id"], note_id=note_id, task_id=task_id)
        return True
    except Exception as e:
        bq.mark_action_failed(action["id"])
        bq.insert_audit_log(actor="comms_agent", action="publish_failed",
                             detail=str(e), alert_id=action["alert_id"], success=False)
        log.error("Sitrep publish failed",
                  action_id=action["id"], error=str(e))
        return False


def _publish_directly(draft_id, sitrep, alert):
    try:
        note_id = write_note(
            title=sitrep["sitrep_title"], body=sitrep["summary"],
            tags=["sitrep", "routine", alert["sector"]],
        )
        bq.update_sitrep_notes_id(draft_id, note_id)
        bq.insert_audit_log(actor="comms_agent", action="routine_sitrep_published",
                             detail=f"Direct publish (score<=4). Note={note_id}",
                             alert_id=alert["id"])
        log.info("Routine sitrep published directly",
                 alert_id=alert["id"], draft_id=draft_id, note_id=note_id)
    except Exception as e:
        bq.insert_audit_log(actor="comms_agent", action="routine_publish_failed",
                             detail=str(e), alert_id=alert["id"], success=False)
        log.error("Routine sitrep publish failed",
                  alert_id=alert["id"], draft_id=draft_id, error=str(e))
        

