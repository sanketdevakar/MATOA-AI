"""
FastAPI Application — SENTINEL v3
------------------------------------

"""
import json
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from fastapi.responses import FileResponse
from config import get_settings
from agents import patrol_agent, comms_agent
from adk.runner import run_pipeline
from utils.logger import get_logger

settings = get_settings()
log      = get_logger("api")

app = FastAPI(
    title="SENTINEL — Indian Army Surveillance Agent System",
    description="Multi-agent AI with Google ADK, BigQuery, GCS, Pub/Sub, and Maps Platform.",
    version="3.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ── Lifecycle ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    # Start Pub/Sub subscriber worker (no-op if USE_PUBSUB=false)
    if settings.use_pubsub:
        from mcp_tools.pubsub_tool import start_subscriber_worker
        start_subscriber_worker(run_pipeline)
        log.info("Pub/Sub subscriber worker started")
    # Start daily scheduler
    from scheduler.daily_scan import start_scheduler
    start_scheduler()
    log.info("SENTINEL v3.0 online", app_env=settings.app_env,
             pubsub=settings.use_pubsub, gcs=settings.gcs_bucket_name)


@app.on_event("shutdown")
def shutdown():
    from scheduler.daily_scan import stop_scheduler
    stop_scheduler()


def verify_commander(x_api_key: str = Header(..., alias="x-api-key")):
    expected = (
        os.environ.get("COMMANDER_API_KEY", "") or settings.commander_api_key
    ).strip()  # 👈 guards against secret storage artifacts
    if not expected:
        raise HTTPException(status_code=500, detail="Commander key not configured.")
    if x_api_key.strip() != expected:  # 👈 strip incoming too
        raise HTTPException(status_code=401, detail="Invalid commander API key.")
    return x_api_key


class AlertPayload(BaseModel):
    alert_type: str
    sector: str
    latitude:    Optional[float] = None
    longitude:   Optional[float] = None
    raw_payload: Optional[str]   = None

class RejectPayload(BaseModel):
    reason: str

class ScanRequest(BaseModel):
    sector: str
    zoom: Optional[int] = 14


# ── Alert endpoints ────────────────────────────────────────────────────────────

@app.post("/api/v1/alert", status_code=202,
          summary="Ingest alert — async via Pub/Sub or sync fallback")
def ingest_alert(payload: AlertPayload):
    """
    Fix 5: If USE_PUBSUB=true, publishes to Pub/Sub and returns 202 immediately.
    Pub/Sub worker runs the full ADK pipeline in background.
    If USE_PUBSUB=false (development), runs pipeline synchronously.
    """
    from db import bigquery_client as bq
    alert = bq.insert_alert(
        alert_type=payload.alert_type,
        sector=payload.sector.upper(),
        latitude=payload.latitude,
        longitude=payload.longitude,
        raw_payload=payload.raw_payload,
    )
    log.info("Alert received", alert_id=alert["id"], sector=alert["sector"],
             alert_type=alert["alert_type"])

    # ── Pub/Sub async path ─────────────────────────────────────────────────
    if settings.use_pubsub:
        from mcp_tools.pubsub_tool import publish_alert
        message_id = publish_alert(alert)
        if message_id:
            return {
                "alert_id":    alert["id"],
                "received_at": alert["created_at"],
                "status":      "queued",
                "message":     "Alert queued for async processing via Pub/Sub.",
                "message_id":  message_id,
            }
        log.warning("Pub/Sub publish failed — falling back to sync",
                    alert_id=alert["id"])

    # ── Synchronous fallback (development or Pub/Sub failure) ──────────────
    result = run_pipeline(alert)
    return {
        "alert_id":      alert["id"],
        "received_at":   str(alert.get("created_at", "")),
        "pipeline_result": result,
    }


@app.get("/api/v1/status/{alert_id}")
def get_alert_status(alert_id: str):
    from db import bigquery_client as bq
    alert   = bq.get_alert(alert_id)
    pending = bq.list_pending_actions(status="pending")
    pending = [a for a in pending if a.get("alert_id") == alert_id]
    scans   = bq.get_sector_scan_history(alert.get("sector", ""), limit=5)
    scans   = [s for s in scans if s.get("alert_id") == alert_id]
    return {
        "alert_id":    alert["id"],
        "sector":      alert["sector"],
        "alert_type":  alert["alert_type"],
        "status":      alert["status"],
        "severity":    alert.get("severity"),
        "threat_score": alert.get("threat_score"),
        "created_at":  str(alert.get("created_at", "")),
        "vision_scans": [{"scan_id": s["id"], "anomalies": s["anomaly_count"],
                          "action": s["recommended_action"]} for s in scans],
        "pending_actions": [{"id": a["id"], "agent": a["agent_name"],
                             "description": a["description"], "status": a["status"]}
                            for a in pending],
    }


# ── HITL endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/v1/hitl/pending")
def list_pending(_=Depends(verify_commander)):
    from db import bigquery_client as bq
    actions = bq.list_pending_actions(status="pending")
    return {"count": len(actions), "actions": [
        {"id": a["id"], "alert_id": a["alert_id"], "agent": a["agent_name"],
         "action_type": a["action_type"], "description": a["description"],
         "created_at": str(a.get("created_at", "")),
         "payload_preview": json.loads(a["payload"]) if a.get("payload") else {}}
        for a in actions]}


@app.put("/api/v1/hitl/approve/{action_id}")
def approve_action(action_id: str, _=Depends(verify_commander)):
    from db import bigquery_client as bq
    action = bq.get_pending_action(action_id)
    if isinstance(action, list):
        action = action[0]
    if action["status"] != "pending":
        raise HTTPException(400, f"Action already {action['status']}.")
    bq.approve_pending_action(action_id)
    success = _dispatch_execution(action)
    bq.insert_audit_log(actor="commander", action="action_approved",
                         detail=f"Executed: {success}", alert_id=action["alert_id"],
                         success=success)
    log.info("Action approved", action_id=action_id, executed=success)
    return {"action_id": action_id, "approved": True, "executed": success}


@app.put("/api/v1/hitl/reject/{action_id}")
def reject_action(action_id: str, body: RejectPayload, _=Depends(verify_commander)):
    from db import bigquery_client as bq
    action = bq.get_pending_action(action_id)
    if isinstance(action, list):
        action = action[0]
    if action["status"] != "pending":
        raise HTTPException(400, f"Action already {action['status']}.")
    bq.reject_pending_action(action_id, reason=body.reason)
    bq.insert_audit_log(actor="commander", action="action_rejected",
                         detail=f"Reason: {body.reason}", alert_id=action["alert_id"])
    log.info("Action rejected", action_id=action_id, reason=body.reason)
    return {"action_id": action_id, "rejected": True, "reason": body.reason}


@app.get("/api/v1/audit/{alert_id}")
def get_audit(alert_id: str, _=Depends(verify_commander)):
    from db import bigquery_client as bq
    logs = bq.get_audit_trail(alert_id)
    return {"alert_id": alert_id, "events": [
        {"timestamp": str(l.get("timestamp", "")), "actor": l["actor"],
         "action": l["action"], "detail": l.get("detail", ""), "success": l.get("success", True)}
        for l in logs]}


# ── Vision / Geo endpoints ─────────────────────────────────────────────────────

@app.post("/api/v1/scan/sector")
def scan_sector_endpoint(req: ScanRequest, _=Depends(verify_commander)):
    from agents import vision_agent
    sector = req.sector.upper()
    assessment = vision_agent.scan_sector(sector=sector, zoom=req.zoom)
    assessment.pop("annotated_image", None)
    return {
        "sector": sector, "scan_id": assessment.get("scan_id"),
        "anomalies": assessment.get("anomaly_count", 0),
        "detected": assessment.get("anomalies_detected", False),
        "action": assessment.get("recommended_action"),
        "assessment": assessment.get("overall_assessment"),
        "indicators": assessment.get("threat_indicators", []),
        "triggered_alert": assessment.get("triggered_alert"),
        "image_source": assessment.get("image_source"),
        "gcs_uri": assessment.get("gcs_uri", ""),
    }


@app.post("/api/v1/scan/trigger-all")
def trigger_full_scan(_=Depends(verify_commander)):
    from scheduler.daily_scan import trigger_immediate_scan
    job_id = trigger_immediate_scan(sector=None)
    return {"queued": True, "job_id": job_id}


@app.get("/api/v1/scan/history/{sector}")
def get_scan_history(sector: str, limit: int = 10):
    from db import bigquery_client as bq
    scans = bq.get_sector_scan_history(sector.upper(), limit=limit)
    return {"sector": sector.upper(), "count": len(scans), "scans": [
        {"scan_id": s["id"], "scanned_at": str(s.get("scanned_at", "")),
         "source": s.get("image_source", ""), "anomalies": s.get("anomaly_count", 0),
         "detected": s.get("anomalies_detected", False),
         "action": s.get("recommended_action", ""),
         "assessment": s.get("overall_assessment", ""),
         "indicators": json.loads(s["threat_indicators"]) if s.get("threat_indicators") else []}
        for s in scans]}


@app.get("/api/v1/scan/image/{scan_id}",
         summary="Get signed GCS URL for annotated scan image")
def get_scan_image(scan_id: str, _=Depends(verify_commander)):
    from db import bigquery_client as bq
    from mcp_tools.gcs_tool import get_signed_url
    scan = bq.get_vision_scan(scan_id)
    uri  = scan.get("annotated_image_uri", "")
    if not uri:
        raise HTTPException(404, "No image stored for this scan.")
    signed_url = get_signed_url(uri, expiry_minutes=60)
    return {
        "scan_id":    scan_id,
        "sector":     scan.get("sector"),
        "scanned_at": str(scan.get("scanned_at", "")),
        "gcs_uri":    uri,
        "signed_url": signed_url,
        "expires_in": "60 minutes",
    }


@app.get("/api/v1/sectors")
def list_sectors():
    coords_map = json.loads(settings.sector_coords)
    return {"count": len(coords_map), "sectors": [
        {"sector": s, "lat": float(v.split(",")[0]), "lon": float(v.split(",")[1]),
         "map_url": f"https://www.openstreetmap.org/?mlat={v.split(',')[0]}&mlon={v.split(',')[1]}&zoom=14"}
        for s, v in coords_map.items()]}

# ────────────────────Dashboard ──────────────────────────────────────────────

@app.get("/dashboard", include_in_schema=False)
def serve_dashboard():
    """Serve the SENTINEL frontend dashboard."""
    frontend_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "frontend",
        "index.html"
    )
    return FileResponse(os.path.abspath(frontend_path))

# ── Demo + Health ──────────────────────────────────────────────────────────────

@app.post("/api/v1/demo/trigger")
def trigger_demo():
    from db import bigquery_client as bq
    alert = bq.insert_alert(
        alert_type="perimeter_breach", sector="SECTOR-7",
        latitude=34.0522, longitude=74.3587,
        raw_payload=json.dumps({"sensor_id": "PERIMETER-S7-042",
                                "trigger": "motion_ir_combined", "confidence": 0.91}),
    )
    result = run_pipeline(alert)
    return {"alert_id": alert["id"], "pipeline_result": result}


@app.post("/api/v1/demo/vision-scan")
def trigger_demo_vision():
    from agents import vision_agent
    assessment = vision_agent.scan_sector(sector="SECTOR-7", zoom=14)
    assessment.pop("annotated_image", None)
    return {"demo": True, "sector": "SECTOR-7", "result": assessment}


@app.get("/")
def root():
    from scheduler.daily_scan import _scheduler
    running   = _scheduler and _scheduler.running
    next_scan = None
    if running:
        job = _scheduler.get_job("daily_surveillance_scan")
        if job:
            next_scan = job.next_run_time.isoformat()
    return {
        "status": "online", "system": "SENTINEL", "version": "3.0.0",
        "scheduler": "running" if running else "stopped",
        "next_scan": next_scan,
        "pubsub":    "enabled" if settings.use_pubsub else "disabled (sync mode)",
        "image_storage": f"gcs://{settings.gcs_bucket_name}",
    }


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def _dispatch_execution(action: dict) -> bool:
    agent = action.get("agent_name", "")
    if agent == "patrol_agent":
        return patrol_agent.execute_approved_action(action)
    elif agent == "comms_agent":
        return comms_agent.execute_approved_action(action)
    log.warning("Unknown agent in dispatch", agent=agent)
    return False