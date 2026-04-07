"""
Vision Agent — GCS + Cloud Logging version
--------------------------------------------
Fix 2: Uploads images to GCS, stores gs:// URI in BigQuery (not base64).
Fix 7: Uses structured Cloud Logging instead of print().
Updated: Switched from Anthropic to Gemini via Vertex AI.
"""
import base64
import json
from datetime import datetime, timezone

from google import genai
from google.genai import types

from db import bigquery_client as bq
from mcp_tools.geo_tool import fetch_sector_image, overlay_waypoints
from mcp_tools.gcs_tool import upload_image
from config import get_settings
from utils.logger import get_logger

settings = get_settings()
client   = genai.Client(
    vertexai=True,
    project=settings.gcp_project_id,
    location=settings.gcp_location,
)
log = get_logger("vision_agent")

SYSTEM_PROMPT = """You are the Vision Intelligence Agent for SENTINEL, an Indian Army border surveillance system.
Analyse satellite or map imagery for security threats.

Look for: unusual vehicle concentrations, human gatherings near borders,
disturbed terrain, temporary structures, equipment caches, anything suspicious.

ALWAYS respond with valid JSON only. Schema:
{
  "anomalies_detected": <true|false>,
  "anomaly_count": <integer>,
  "threat_indicators": [
    {"type": "<vehicle_movement|human_gathering|terrain_disturbance|structure|equipment|other>",
     "location_description": "<quadrant in image>",
     "confidence": <0.0-1.0>,
     "description": "<1-2 sentences>"}
  ],
  "overall_assessment": "<2-3 sentences>",
  "recommended_action": "<none|patrol_verification|immediate_alert|request_higher_resolution>",
  "image_quality": "<good|partial|poor>",
  "coverage_notes": "<obscured areas>"
}"""


def scan_sector(sector: str, alert_id: str = None, zoom: int = 14) -> dict:
    log.info("Starting sector scan", sector=sector, alert_id=alert_id, zoom=zoom)
    # FIX: timezone-aware UTC
    scan_start = datetime.now(timezone.utc)

    geo_data  = fetch_sector_image(sector=sector, zoom=zoom)
    image_b64 = geo_data["base64"]

    try:
        # Decode base64 to bytes for Gemini
        image_bytes = base64.b64decode(image_b64)

        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                types.Part.from_text(text=(
                    f"Sector: {sector}\nSource: {geo_data['source']}\n"
                    f"Coords: {geo_data['lat']:.4f}N {geo_data['lon']:.4f}E\n"
                    f"Time: {scan_start.isoformat()} UTC\nProvide assessment JSON."
                )),
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=2000,
                temperature=0.2,
            ),
        )
        text = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        assessment = json.loads(text)
    except Exception as e:
        log.error("Vision analysis failed", sector=sector, alert_id=alert_id, error=str(e))
        assessment = _fallback(str(e))

    # Annotate image with markers if anomalies found
    annotated_b64 = image_b64
    if assessment.get("anomalies_detected") and assessment.get("threat_indicators"):
        waypoints = _indicators_to_waypoints(
            assessment["threat_indicators"], geo_data["lat"], geo_data["lon"])
        annotated_b64 = overlay_waypoints(
            image_b64, waypoints, geo_data["lat"], geo_data["lon"], zoom)

    # ── Upload to GCS, store URI instead of base64 ─────────────────────────
    scan_id = f"scan-{scan_start.strftime('%Y%m%d%H%M%S')}-{sector.replace('-', '')}"

    raw_uri       = upload_image(image_b64,     scan_id, annotated=False)
    annotated_uri = upload_image(annotated_b64, scan_id, annotated=True)

    # BigQuery stores the URI — API endpoint will generate signed URL on demand
    stored_uri = annotated_uri or raw_uri or ""

    bq_scan_id = bq.insert_vision_scan(
        sector=sector, scanned_at=scan_start.isoformat(),
        image_source=geo_data["source"],
        image_lat=geo_data["lat"], image_lon=geo_data["lon"],
        zoom_level=zoom,
        anomalies_detected=assessment.get("anomalies_detected", False),
        anomaly_count=assessment.get("anomaly_count", 0),
        threat_indicators=assessment.get("threat_indicators", []),
        overall_assessment=assessment.get("overall_assessment", ""),
        recommended_action=assessment.get("recommended_action", "none"),
        image_quality=assessment.get("image_quality", "unknown"),
        annotated_image_uri=stored_uri,
        alert_id=alert_id,
    )
    bq.insert_audit_log(
        actor="vision_agent", action="sector_scan_complete",
        detail=(
            f"sector={sector} anomalies={assessment.get('anomaly_count', 0)} "
            f"source={geo_data['source']} gcs_uri={stored_uri}"
        ),
        alert_id=alert_id,
    )

    triggered_alert_id = None
    if assessment.get("anomalies_detected") and assessment.get("recommended_action") != "none":
        triggered_alert_id = _trigger_alert(sector, assessment, geo_data)

    assessment["scan_id"]         = bq_scan_id
    assessment["image_source"]    = geo_data["source"]
    assessment["triggered_alert"] = triggered_alert_id
    assessment["annotated_image"] = annotated_b64  # returned in-memory for API
    assessment["gcs_uri"]         = stored_uri

    log.info("Scan complete", sector=sector, alert_id=alert_id,
             anomalies=assessment.get("anomaly_count", 0),
             action=assessment.get("recommended_action"), gcs_uri=stored_uri)
    return assessment


def _trigger_alert(sector, assessment, geo_data) -> str:
    from agents import command_agent
    payload = {
        "source":             "vision_agent",
        "anomaly_count":      assessment.get("anomaly_count", 0),
        "threat_indicators":  assessment.get("threat_indicators", []),
        "overall_assessment": assessment.get("overall_assessment"),
    }
    action     = assessment.get("recommended_action", "none")
    alert_type = "perimeter_breach" if action == "immediate_alert" else "drone_sighting"
    alert = bq.insert_alert(
        alert_type=alert_type, sector=sector,
        latitude=geo_data["lat"], longitude=geo_data["lon"],
        raw_payload=json.dumps(payload),
    )
    command_agent.process_alert(alert)
    log.info("Auto-triggered alert from vision", sector=sector, alert_id=alert["id"])
    return alert["id"]


def _indicators_to_waypoints(indicators, center_lat, center_lon):
    OFFSET = 0.004
    dir_map = {
        "north":      (OFFSET, 0),       "south":      (-OFFSET, 0),
        "east":       (0, OFFSET),        "west":       (0, -OFFSET),
        "north-east": (OFFSET, OFFSET),   "north-west": (OFFSET, -OFFSET),
        "south-east": (-OFFSET, OFFSET),  "south-west": (-OFFSET, -OFFSET),
        "centre":     (0, 0),             "center":     (0, 0),
    }
    color_map = {
        "vehicle_movement":    "red",
        "human_gathering":     "orange",
        "terrain_disturbance": "yellow",
        "structure":           "magenta",
        "equipment":           "blue",
        "other":               "white",
    }
    wps = []
    for i, ind in enumerate(indicators):
        desc = ind.get("location_description", "").lower()
        dlat, dlon = 0, 0
        for direction, (dl, dlo) in dir_map.items():
            if direction in desc:
                dlat, dlon = dl, dlo
                break
        wps.append({
            "lat":   center_lat + dlat,
            "lon":   center_lon + dlon,
            "label": f"T{i+1}",
            "color": color_map.get(ind.get("type", "other"), "white"),
        })
    return wps


def _fallback(error):
    return {
        "anomalies_detected": False,
        "anomaly_count":      0,
        "threat_indicators":  [],
        "overall_assessment": f"Vision scan failed: {error}",
        "recommended_action": "patrol_verification",
        "image_quality":      "poor",
        "coverage_notes":     "Scan failed.",
    }