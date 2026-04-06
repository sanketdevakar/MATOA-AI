"""
Intel Agent — BigQuery + Cloud Logging version
Uses Gemini via Vertex AI instead of Anthropic.
"""
import json
from google import genai
from google.genai import types
from db import bigquery_client as bq
from config import get_settings
from utils.logger import get_logger
#from db.bigquery_client import close_client

settings = get_settings()
log      = get_logger("intel_agent")

# ── Vertex AI Gemini client ───────────────────────────────────────────────────
client = genai.Client(
    vertexai=True,
    project=settings.gcp_project_id,
    location=settings.gcp_location,
)

SYSTEM_PROMPT = """You are the Intel Agent for SENTINEL, an Indian Army surveillance system.
Analyse an incoming alert alongside recent historical incidents and return a structured threat assessment.

ALWAYS respond with valid JSON only — no preamble, no markdown fences. Schema:
{
  "threat_score": <integer 1-10>,
  "severity": "<low|medium|high|critical>",
  "reasoning": "<2-3 sentences>",
  "recommended_response": "<one sentence>",
  "historical_context": "<one sentence>"
}
Scoring: 1-3=low, 4-5=medium, 6-7=high, 8-10=critical."""


def run(alert: dict) -> dict:
    sector = alert["sector"]
    log.info("Starting threat assessment", alert_id=alert["id"], sector=sector)

    history      = bq.get_sector_history(sector=sector, days=14, limit=20)
    history_text = _fmt(history)

    user_msg = f"""
INCOMING ALERT:
  Type    : {alert['alert_type']}
  Sector  : {sector}
  Time UTC: {alert['created_at']}
  Payload : {alert.get('raw_payload', 'N/A')}

HISTORICAL INCIDENTS (last 14 days in {sector}):
{history_text}

Provide threat assessment JSON now.
"""

    try:
        resp = client.models.generate_content(
        model=settings.gemini_model,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=2000,
            temperature=0.2,
    ),
)
    
    # strip markdown fences if model adds them
        text = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        assessment = json.loads(text)
    except Exception as e:
        log.error("LLM call failed — using default assessment",
        alert_id=alert["id"], sector=sector, error=str(e))
        assessment = {
            "threat_score": 5, "severity": "medium",
            "reasoning": f"Error: {e}. Defaulting to medium.",
            "recommended_response": "Proceed with standard patrol verification.",
            "historical_context": "Unable to retrieve context.",
        }

    bq.update_alert_threat(
        alert_id=alert["id"],
        threat_score=assessment["threat_score"],
        severity=assessment["severity"],
    )
    bq.insert_audit_log(
        actor="intel_agent", action="threat_assessment_complete",
        detail=json.dumps(assessment), alert_id=alert["id"],
    )

    log.info("Assessment complete",
             alert_id=alert["id"], sector=sector,
             threat_score=assessment["threat_score"],
             severity=assessment["severity"])
    return assessment


def _fmt(incidents: list) -> str:
    if not incidents:
        return "  No incidents in the past 14 days."
    lines = []
    for inc in incidents:
        ts       = str(inc.get("occurred_at", ""))[:16]
        resolved = "resolved" if inc.get("resolved") else "UNRESOLVED"
        lines.append(
            f"  • {ts} | {inc.get('incident_type')} | "
            f"{inc.get('severity','?').upper()} | {resolved}"
        )
    return "\n".join(lines)

