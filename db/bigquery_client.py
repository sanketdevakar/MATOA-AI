"""
BigQuery Client — SENTINEL
-----------------------------
Uses toolbox-core Python SDK to call MCP Toolbox server.
Toolbox server runs at http://localhost:5000 (started with toolbox.exe).

The SDK exposes each tool as an async callable. We wrap them
synchronously here so the rest of the codebase stays simple.

Usage:
  from db.bigquery_client import get_sector_history, insert_alert
  rows = get_sector_history("SECTOR-7", days=14)
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from toolbox_core import ToolboxSyncClient
from config import get_settings

settings = get_settings()
TOOLBOX_URL = settings.mcp_toolbox_url   # http://localhost:5000

# ── Toolbox helpers ─────────────────────────────────────────────────────────────

# ── Toolbox client (singleton) ──────────────────────────────────────────────────

_client: ToolboxSyncClient = None

def _get_client() -> ToolboxSyncClient:
    global _client
    if _client is None:
        _client = ToolboxSyncClient(TOOLBOX_URL.rstrip("/"))
    return _client

def close_client():
    global _client
    if _client is not None:
        _client.close()
        _client = None

def reset_client():
    """Force-reset the Toolbox client — call after closing an event loop."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None


def _call_tool(tool_name: str, **kwargs) -> Any:
    """Load and invoke a Toolbox tool synchronously."""
    for attempt in range(2):  # retry once on session errors
        try:
            tool = _get_client().load_tool(tool_name)
            result = tool(**kwargs)

            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    return parsed if isinstance(parsed, list) else [parsed]
                except (json.JSONDecodeError, ValueError):
                    # Non-JSON string means "no rows" message from Toolbox
                    return []

            return result

        except RuntimeError as exc:
            if "Session is closed" in str(exc) and attempt == 0:
                reset_client()  # force fresh client, retry once
                continue
            raise RuntimeError(
                f"Tool '{tool_name}' failed: {exc}. "
                f"Is toolbox running at {TOOLBOX_URL}?"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Tool '{tool_name}' failed: {exc}. "
                f"Is toolbox running at {TOOLBOX_URL}?"
            ) from exc


def _now() -> str:
    # FIX: use timezone-aware UTC so BigQuery TIMESTAMP comparisons are correct.
    # datetime.utcnow() returns a naive datetime which can cause subtle bugs
    # when Toolbox or BigQuery interprets the timezone.
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Alerts ─────────────────────────────────────────────────────────────────────

def insert_alert(
    alert_type: str,
    sector: str,
    latitude: float = None,
    longitude: float = None,
    raw_payload: str = None,
) -> dict:
    # FIX: latitude=0.0 / longitude=0.0 is a valid coordinate (Gulf of Guinea).
    # Use None-check instead of truthiness so real 0.0 values are not replaced.
    alert_id = _new_id()
    _call_tool("insert_alert",
        id=alert_id,
        created_at=_now(),
        alert_type=alert_type,
        sector=sector,
        latitude=str(latitude if latitude is not None else 0.0),
        longitude=str(longitude if longitude is not None else 0.0),
        raw_payload=raw_payload or "",
        status="received",
        severity="",
        threat_score=0,
    )
    return get_alert(alert_id)


def get_alert(alert_id: str) -> dict:
    rows = _call_tool("get_alert_by_id", id=alert_id)
    if not rows:
        raise ValueError(f"Alert {alert_id} not found")
    return rows[0] if isinstance(rows, list) else rows


def update_alert_status(alert_id: str, status: str):
    _call_tool("update_alert_status", id=alert_id, status=status)


def update_alert_threat(alert_id: str, threat_score: int, severity: str):
    _call_tool("update_alert_threat",
        id=alert_id, threat_score=threat_score, severity=severity)


def list_alerts(limit: int = 20) -> list:
    result = _call_tool("list_alerts", limit=limit)
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []


# ── Historical Incidents ───────────────────────────────────────────────────────

def get_sector_history(sector: str, days: int = 14, limit: int = 20) -> list:
    result = _call_tool("get_sector_history",
        sector=sector, days_back=days, limit=limit)
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []

def insert_historical_incident(
    sector: str,
    incident_type: str,
    severity: str,
    occurred_at: str,
    description: str = "",
    resolved: bool = False,
) -> str:
    inc_id = _new_id()
    _call_tool("insert_historical_incident",
        id=inc_id,
        occurred_at=occurred_at,
        sector=sector,
        incident_type=incident_type,
        severity=severity,
        description=description,
        resolved=resolved,
    )
    return inc_id


# ── Pending Actions ────────────────────────────────────────────────────────────

def insert_pending_action(
    alert_id: str,
    agent_name: str,
    action_type: str,
    description: str,
    payload: dict,
) -> dict:
    # FIX: moved json import to top of file — no need for a deferred import here.
    action_id = _new_id()
    _call_tool("insert_pending_action",
        id=action_id,
        alert_id=alert_id,
        created_at=_now(),
        agent_name=agent_name,
        action_type=action_type,
        description=description,
        payload=json.dumps(payload),
        status="pending",
    )
    return get_pending_action(action_id)


def get_pending_action(action_id: str) -> dict:
    rows = _call_tool("get_pending_action_by_id", id=action_id)
    if not rows:
        raise ValueError(f"PendingAction {action_id} not found")
    return rows[0] if isinstance(rows, list) else rows


def list_pending_actions(status: str = "pending") -> list:
    result = _call_tool("list_pending_actions", status=status)
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []


def approve_pending_action(action_id: str, decided_by: str = "commander"):
    _call_tool("update_pending_action_status",
        id=action_id,
        status="approved",
        decided_at=_now(),
        decided_by=decided_by,
        reject_reason="",
    )


def reject_pending_action(action_id: str, reason: str, decided_by: str = "commander"):
    _call_tool("update_pending_action_status",
        id=action_id,
        status="rejected",
        decided_at=_now(),
        decided_by=decided_by,
        reject_reason=reason,
    )


def mark_action_executed(action_id: str):
    _call_tool("update_pending_action_status",
        id=action_id,
        status="executed",
        decided_at=_now(),
        decided_by="system",
        reject_reason="",
    )


def mark_action_failed(action_id: str):
    _call_tool("update_pending_action_status",
        id=action_id,
        status="failed",
        decided_at=_now(),
        decided_by="system",
        reject_reason="",
    )


# ── Patrol Logs ────────────────────────────────────────────────────────────────
# NOTE: insert_patrol_log, insert_sitrep_draft, update_sitrep_notes_id,
# insert_vision_scan, get_vision_scan, and get_sector_scan_history are kept
# here in the client but have NO corresponding tools in toolbox_config.yaml
# (you chose not to add those tables). Calling these functions will raise a
# RuntimeError from _call_tool. Either remove these functions, or add the
# matching tables + YAML tools when you are ready.

def insert_patrol_log(
    alert_id: str,
    sector: str,
    patrol_start: str,
    patrol_end: str,
    unit_assigned: str,
    route_notes: str = "",
    calendar_event_id: str = None,
) -> str:
    log_id = _new_id()
    _call_tool("insert_patrol_log",
        id=log_id,
        alert_id=alert_id,
        sector=sector,
        created_at=_now(),
        patrol_start=patrol_start,
        patrol_end=patrol_end,
        unit_assigned=unit_assigned,
        route_notes=route_notes or "",
        calendar_event_id=calendar_event_id or "",
    )
    return log_id


# ── Sitrep Drafts ──────────────────────────────────────────────────────────────

def insert_sitrep_draft(
    alert_id: str,
    sector: str,
    threat_score: int,
    summary: str,
    recommended_actions: str = "",
) -> str:
    draft_id = _new_id()
    _call_tool("insert_sitrep_draft",
        id=draft_id,
        alert_id=alert_id,
        created_at=_now(),
        sector=sector,
        threat_score=threat_score,
        summary=summary,
        recommended_actions=recommended_actions or "",
        notes_mcp_id="",
    )
    return draft_id


def update_sitrep_notes_id(draft_id: str, notes_mcp_id: str):
    _call_tool("update_sitrep_notes_id",
        id=draft_id, notes_mcp_id=notes_mcp_id)


# ── Audit Log ──────────────────────────────────────────────────────────────────

def insert_audit_log(
    actor: str,
    action: str,
    detail: str = "",
    alert_id: str = None,
    success: bool = True,
):
    _call_tool("insert_audit_log",
        id=_new_id(),
        alert_id=alert_id or "",
        timestamp=_now(),
        actor=actor,
        action=action,
        detail=detail or "",
        success=success,
    )


def get_audit_trail(alert_id: str) -> list:
    result = _call_tool("get_audit_trail", alert_id=alert_id)
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []


# ── Vision Scans ───────────────────────────────────────────────────────────────

def insert_vision_scan(
    sector: str,
    scanned_at: str,
    image_source: str,
    image_lat: float,
    image_lon: float,
    zoom_level: int,
    anomalies_detected: bool,
    anomaly_count: int,
    threat_indicators: list,
    overall_assessment: str,
    recommended_action: str,
    image_quality: str,
    annotated_image_uri: str = None,
    alert_id: str = None,
) -> str:
    scan_id = _new_id()
    _call_tool("insert_vision_scan",
        id=scan_id,
        alert_id=alert_id or "",
        sector=sector,
        scanned_at=scanned_at,
        image_source=image_source,
        image_lat=str(image_lat),   # ← convert to string
        image_lon=str(image_lon),   # ← convert to string
        zoom_level=zoom_level,
        anomalies_detected=anomalies_detected,
        anomaly_count=anomaly_count,
        threat_indicators=json.dumps(threat_indicators),
        overall_assessment=overall_assessment,
        recommended_action=recommended_action,
        image_quality=image_quality,
        annotated_image_uri=annotated_image_uri or "",
    )
    return scan_id


def get_vision_scan(scan_id: str) -> dict:
    rows = _call_tool("get_vision_scan_by_id", id=scan_id)
    if not rows:
        raise ValueError(f"VisionScan {scan_id} not found")
    return rows[0] if isinstance(rows, list) else rows


def get_sector_scan_history(sector: str, limit: int = 10) -> list:
    result = _call_tool("get_sector_scan_history", sector=sector, limit=limit)
    if not isinstance(result, list):
        return []
    parsed_result = []
    for item in result:
        if isinstance(item, dict):
            parsed_result.append(item)
        elif isinstance(item, str):
            try:
                parsed_result.append(json.loads(item))
            except (json.JSONDecodeError, ValueError):
                pass  # skip "no rows" strings
    return parsed_result


def get_alerts_count_since(date_str: str) -> int:
    """Count alerts created since date_str (YYYY-MM-DD)"""
    result = _call_tool("count_alerts_since", since_date=date_str)
    if isinstance(result, list) and result:
        item = result[0]
        if isinstance(item, dict):
            return item.get("count", 0)
        elif isinstance(item, str):
            try:
                parsed = json.loads(item)
                return parsed.get("count", 0) if isinstance(parsed, dict) else 0
            except (json.JSONDecodeError, ValueError):
                return 0
        else:
            return int(item) if isinstance(item, (int, str)) else 0
    elif isinstance(result, (int, str)):
        return int(result)
    return 0


def get_latest_scan_timestamp() -> str:
    """Get the most recent scan timestamp across all sectors"""
    result = _call_tool("get_latest_scan_timestamp")
    if isinstance(result, list) and result:
        item = result[0]
        if isinstance(item, dict):
            return item.get("latest_scan", "")
        elif isinstance(item, str):
            try:
                parsed = json.loads(item)
                return parsed.get("latest_scan", "") if isinstance(parsed, dict) else ""
            except (json.JSONDecodeError, ValueError):
                return ""
        else:
            return str(item)
    elif isinstance(result, str):
        return result
    return ""


def get_all_audit_logs(limit: int = 100) -> list:
    """Get all audit logs, ordered by timestamp desc, limited"""
    result = _call_tool("get_all_audit_logs", limit=limit)
    if not isinstance(result, list):
        return []
    parsed_result = []
    for item in result:
        if isinstance(item, dict):
            parsed_result.append(item)
        elif isinstance(item, str):
            try:
                parsed_result.append(json.loads(item))
            except (json.JSONDecodeError, ValueError):
                pass  # skip "no rows" strings
    return parsed_result

