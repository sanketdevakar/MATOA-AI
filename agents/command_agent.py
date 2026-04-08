"""
Primary Command Agent — BigQuery + Cloud Logging version

"""
from datetime import datetime
from db import bigquery_client as bq
from agents import intel_agent, patrol_agent, comms_agent
from config import get_settings
from utils.logger import get_logger

settings = get_settings()
log      = get_logger("command_agent")


def process_alert(alert: dict) -> dict:
    alert_id = alert["id"]
    result   = {
        "alert_id":       alert_id,
        "sector":         alert["sector"],
        "pipeline_steps": [],
    }

    log.info("Pipeline started",
             alert_id=alert_id, sector=alert["sector"],
             alert_type=alert["alert_type"])
    bq.update_alert_status(alert_id, "processing")

    # ── Intel Agent ─────────────────────────────────────────────────────────
    try:
        assessment = intel_agent.run(alert)
        result["threat_score"] = assessment["threat_score"]
        result["severity"]     = assessment["severity"]
        result["pipeline_steps"].append({
            "agent": "intel_agent", "status": "completed",
            "output": {
                "threat_score": assessment["threat_score"],
                "severity":     assessment["severity"],
                "reasoning":    assessment["reasoning"],
            },
        })
    except Exception as e:
        log.error("Intel agent failed", alert_id=alert_id, error=str(e))
        result["pipeline_steps"].append(
            {"agent": "intel_agent", "status": "failed", "error": str(e)})
        assessment = {
            "threat_score": 5, "severity": "medium",
            "reasoning": "Intel agent failed; defaulting to medium.",
            "recommended_response": "Proceed with standard verification.",
            "historical_context": "Unavailable.",
        }

    # ── Patrol Agent ─────────────────────────────────────────────────────────
    try:
        patrol_action = patrol_agent.propose(alert, assessment)
        result["pipeline_steps"].append({
            "agent": "patrol_agent", "status": "completed",
            "output": {
                "action_created": patrol_action is not None,
                "action_id":      patrol_action["id"] if patrol_action else None,
                "description":    patrol_action["description"] if patrol_action else "No change",
            },
        })
    except Exception as e:
        log.error("Patrol agent failed", alert_id=alert_id, error=str(e))
        result["pipeline_steps"].append(
            {"agent": "patrol_agent", "status": "failed", "error": str(e)})
        patrol_action = None

    # ── Comms Agent ──────────────────────────────────────────────────────────
    try:
        comms_action = comms_agent.propose(alert, assessment)
        result["pipeline_steps"].append({
            "agent": "comms_agent", "status": "completed",
            "output": {
                "action_created": comms_action is not None,
                "action_id":      comms_action["id"] if comms_action else None,
                "description":    comms_action["description"] if comms_action else "Routine sitrep published",
            },
        })
    except Exception as e:
        log.error("Comms agent failed", alert_id=alert_id, error=str(e))
        result["pipeline_steps"].append(
            {"agent": "comms_agent", "status": "failed", "error": str(e)})
        comms_action = None

    # ── Final status ─────────────────────────────────────────────────────────
    pending_count = sum(
        1 for step in result["pipeline_steps"]
        if step.get("output", {}).get("action_created")
    )

    if pending_count > 0:
        bq.update_alert_status(alert_id, "awaiting_hitl")
        result["status"]  = "awaiting_hitl"
        result["message"] = f"{pending_count} action(s) pending commander approval."
    else:
        bq.update_alert_status(alert_id, "completed")
        result["status"]  = "completed"
        result["message"] = "Pipeline complete. No HITL required."

    bq.insert_audit_log(actor="command_agent", action="pipeline_finished",
                         detail=result["message"], alert_id=alert_id)
    log.info("Pipeline finished",
             alert_id=alert_id, sector=alert["sector"],
             status=result["status"],
             threat_score=result.get("threat_score", "?"))
    return result
