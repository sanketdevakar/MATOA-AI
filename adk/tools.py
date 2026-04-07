"""
ADK Tool Definitions for SENTINEL
------------------------------------
Each function decorated with @adk_tool becomes a callable tool
that ADK sub-agents can invoke autonomously during their turn.

Tools are grouped by agent responsibility:
  - intel_tools    → BigQuery history queries
  - patrol_tools   → Calendar MCP, patrol log writes
  - comms_tools    → Notes MCP, task creation, sitrep writes
  - vision_tools   → Geo imagery fetch, BigQuery vision scan writes
  - shared_tools   → Audit log, alert status updates
"""

import json
from datetime import datetime, timedelta
from google.adk.tools import FunctionTool

from db import bigquery_client as bq
from mcp_tools.calendar_tool import create_patrol_event
from mcp_tools.notes_tool import write_note
from mcp_tools.tasks_tool import create_task
from mcp_tools.geo_tool import fetch_sector_image, overlay_waypoints


# ── Shared tools ───────────────────────────────────────────────────────────────

def write_audit_log(alert_id: str, actor: str, action: str, detail: str, success: bool = True) -> dict:
    """Write an immutable audit log entry to BigQuery."""
    bq.insert_audit_log(actor=actor, action=action, detail=detail,
                         alert_id=alert_id, success=success)
    return {"logged": True, "actor": actor, "action": action}


def update_alert_threat_score(alert_id: str, threat_score: int, severity: str) -> dict:
    """Update threat score and severity on an alert in BigQuery."""
    bq.update_alert_threat(alert_id=alert_id, threat_score=threat_score, severity=severity)
    return {"updated": True, "alert_id": alert_id, "threat_score": threat_score, "severity": severity}


def update_alert_status(alert_id: str, status: str) -> dict:
    """Update the pipeline status of an alert in BigQuery."""
    bq.update_alert_status(alert_id=alert_id, status=status)
    return {"updated": True, "status": status}


# ── Intel tools ────────────────────────────────────────────────────────────────

def get_sector_incident_history(sector: str, days_back: int = 14) -> dict:
    """
    Fetch recent historical incidents for a sector from BigQuery.
    Returns formatted history for threat scoring context.
    """
    rows = bq.get_sector_history(sector=sector, days=days_back, limit=20)
    formatted = []
    for r in rows:
        formatted.append({
            "occurred_at":   str(r.get("occurred_at", ""))[:16],
            "incident_type": r.get("incident_type", ""),
            "severity":      r.get("severity", ""),
            "resolved":      r.get("resolved", False),
        })
    return {
        "sector":         sector,
        "days_back":      days_back,
        "incident_count": len(formatted),
        "incidents":      formatted,
    }


# ── Patrol tools ───────────────────────────────────────────────────────────────

def create_patrol_schedule(
    alert_id: str,
    sector: str,
    unit: str,
    start_offset_hours: int,
    duration_hours: int,
    route_notes: str,
) -> dict:
    """
    Create a patrol event on Google Calendar MCP and log it to BigQuery.
    Returns the calendar event ID and patrol log ID.
    """
    start_dt = datetime.utcnow() + timedelta(hours=start_offset_hours)
    end_dt   = start_dt + timedelta(hours=duration_hours)

    event_id = create_patrol_event(
        sector=sector, unit=unit,
        start_iso=start_dt.isoformat(),
        end_iso=end_dt.isoformat(),
        route_notes=route_notes,
    )
    log_id = bq.insert_patrol_log(
        alert_id=alert_id, sector=sector,
        patrol_start=start_dt.isoformat(), patrol_end=end_dt.isoformat(),
        unit_assigned=unit, route_notes=route_notes,
        calendar_event_id=event_id,
    )
    return {
        "calendar_event_id": event_id,
        "patrol_log_id":     log_id,
        "unit":              unit,
        "sector":            sector,
        "patrol_start":      start_dt.isoformat(),
        "patrol_end":        end_dt.isoformat(),
    }


def create_pending_action_for_patrol(
    alert_id: str,
    action_type: str,
    description: str,
    sector: str,
    unit: str,
    start_offset_hours: int,
    duration_hours: int,
    route_notes: str,
) -> dict:
    """
    Create a HITL pending action for patrol scheduling (requires commander approval).
    Called when threat_score > 5.
    """
    start_dt = datetime.utcnow() + timedelta(hours=start_offset_hours)
    end_dt   = start_dt + timedelta(hours=duration_hours)
    payload  = {
        "sector": sector, "unit": unit,
        "start_iso": start_dt.isoformat(), "end_iso": end_dt.isoformat(),
        "route_notes": route_notes, "alert_id": alert_id,
    }
    action = bq.insert_pending_action(
        alert_id=alert_id, agent_name="patrol_agent",
        action_type=action_type, description=description, payload=payload,
    )
    return {"pending_action_id": action["id"], "description": description, "requires_approval": True}


# ── Comms tools ────────────────────────────────────────────────────────────────

def save_sitrep_draft(
    alert_id: str,
    sector: str,
    threat_score: int,
    summary: str,
    recommended_actions: str,
) -> dict:
    """Save a situation report draft to BigQuery."""
    draft_id = bq.insert_sitrep_draft(
        alert_id=alert_id, sector=sector,
        threat_score=threat_score, summary=summary,
        recommended_actions=recommended_actions,
    )
    return {"draft_id": draft_id, "saved": True}


def publish_sitrep_to_notes(
    alert_id: str,
    draft_id: str,
    title: str,
    body: str,
    classification: str,
    duty_officer_task: str,
) -> dict:
    """
    Publish a sitrep directly to Notes MCP and create a duty officer task.
    Used for ROUTINE classification (score <= 4) without HITL.
    """
    note_id = write_note(title=title, body=body,
                          tags=["sitrep", classification.lower()])
    task_id = create_task(
        title=f"ACTION REQUIRED: {title}",
        description=duty_officer_task,
        priority="medium",
    )
    bq.update_sitrep_notes_id(draft_id=draft_id, notes_mcp_id=note_id)
    return {"note_id": note_id, "task_id": task_id, "published": True}


def create_pending_action_for_sitrep(
    alert_id: str,
    draft_id: str,
    title: str,
    body: str,
    classification: str,
    duty_officer_task: str,
) -> dict:
    """
    Create a HITL pending action for sitrep publishing (requires commander approval).
    Called when threat_score > 4.
    """
    payload = {
        "draft_id": draft_id, "title": title, "body": body,
        "classification": classification,
        "duty_officer_task": duty_officer_task, "alert_id": alert_id,
    }
    action = bq.insert_pending_action(
        alert_id=alert_id, agent_name="comms_agent",
        action_type="publish_sitrep",
        description=f"Publish {classification} sitrep: {title}",
        payload=payload,
    )
    return {"pending_action_id": action["id"], "classification": classification, "requires_approval": True}


# ── Vision tools ───────────────────────────────────────────────────────────────

def fetch_sector_satellite_image(sector: str, zoom: int = 14) -> dict:
    """
    Fetch satellite / map imagery for a sector.
    Returns base64-encoded PNG and metadata.
    Source priority: Mapbox → Google Static → OpenStreetMap tiles.
    """
    geo_data = fetch_sector_image(sector=sector, zoom=zoom)
    return {
        "sector":      sector,
        "image_b64":   geo_data["base64"],
        "source":      geo_data["source"],
        "lat":         geo_data["lat"],
        "lon":         geo_data["lon"],
        "zoom":        zoom,
        "bbox":        geo_data.get("bbox", {}),
    }


def save_vision_scan_result(
    sector: str,
    alert_id: str,
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
) -> dict:
    """Persist vision scan results to BigQuery vision_scans table."""
    scan_id = bq.insert_vision_scan(
        sector=sector, scanned_at=datetime.utcnow().isoformat(),
        image_source=image_source, image_lat=image_lat, image_lon=image_lon,
        zoom_level=zoom_level, anomalies_detected=anomalies_detected,
        anomaly_count=anomaly_count, threat_indicators=threat_indicators,
        overall_assessment=overall_assessment, recommended_action=recommended_action,
        image_quality=image_quality, alert_id=alert_id,
    )
    return {"scan_id": scan_id, "saved": True, "anomaly_count": anomaly_count}


# ── Wrap as ADK FunctionTools ──────────────────────────────────────────────────

# Shared
audit_log_tool          = FunctionTool(func=write_audit_log)
update_threat_tool      = FunctionTool(func=update_alert_threat_score)
update_status_tool      = FunctionTool(func=update_alert_status)

# Intel
history_tool            = FunctionTool(func=get_sector_incident_history)

# Patrol
patrol_schedule_tool    = FunctionTool(func=create_patrol_schedule)
patrol_hitl_tool        = FunctionTool(func=create_pending_action_for_patrol)

# Comms
sitrep_save_tool        = FunctionTool(func=save_sitrep_draft)
sitrep_publish_tool     = FunctionTool(func=publish_sitrep_to_notes)
sitrep_hitl_tool        = FunctionTool(func=create_pending_action_for_sitrep)

# Vision
geo_image_tool          = FunctionTool(func=fetch_sector_satellite_image)
vision_save_tool        = FunctionTool(func=save_vision_scan_result)


# ── Google Maps Platform Tools ────────────────────────────────────────────────
# Registered as ADK FunctionTools so agents can call them autonomously.

from mcp_tools.google_maps_tool import (
    fetch_satellite_image as _gmaps_satellite,
    fetch_satellite_with_markers as _gmaps_marked,
    geocode_location,
    reverse_geocode,
    find_nearby_features,
    get_patrol_route,
    fetch_street_view,
)


def gmaps_satellite_image(lat: float, lon: float, zoom: int = 15, map_type: str = "satellite") -> dict:
    """
    Fetch Google Maps satellite or hybrid imagery for a location.
    map_type: 'satellite' for raw imagery, 'hybrid' for satellite + labels,
    'terrain' for topographic view. Used by Vision Agent for high-quality
    sector scanning when Mapbox is unavailable.
    """
    return _gmaps_satellite(lat=lat, lon=lon, zoom=zoom, map_type=map_type)


def gmaps_satellite_with_threat_markers(
    lat: float, lon: float,
    markers: list,
    zoom: int = 15,
) -> dict:
    """
    Fetch Google Maps hybrid image with threat markers rendered natively.
    markers: list of dicts with lat, lon, label, color keys.
    Returns annotated image with Google-rendered pins at anomaly locations.
    """
    return _gmaps_marked(lat=lat, lon=lon, markers=markers, zoom=zoom, map_type="hybrid")


def gmaps_geocode(address: str) -> dict:
    """
    Convert a place name or address to lat/lon coordinates.
    Use to resolve sector names, village names, or landmark descriptions
    into precise coordinates for patrol planning and vision scanning.
    """
    return geocode_location(address=address)


def gmaps_reverse_geocode(lat: float, lon: float) -> dict:
    """
    Convert lat/lon to a human-readable address and location name.
    Use when reporting incident locations to commanders — gives a
    recognisable place name rather than raw coordinates.
    """
    return reverse_geocode(lat=lat, lon=lon)


def gmaps_nearby_terrain_features(
    lat: float, lon: float,
    radius_meters: int = 2000,
) -> dict:
    """
    Find terrain features, infrastructure, and points of interest
    within radius_meters of a location using Google Places API.
    Use for sector context — bridges, roads, settlements, chokepoints.
    Helps Intel Agent understand the physical environment around an alert.
    """
    return find_nearby_features(
        lat=lat, lon=lon, radius_meters=radius_meters,
        place_types=["natural_feature", "point_of_interest", "route"],
    )


def gmaps_patrol_route(
    origin_lat: float, origin_lon: float,
    destination_lat: float, destination_lon: float,
    waypoints: list = None,
    travel_mode: str = "walking",
) -> dict:
    """
    Calculate optimised patrol route between points using Google Directions API.
    waypoints: optional list of intermediate checkpoints [{"lat": f, "lon": f}].
    travel_mode: 'walking' for foot patrol, 'driving' for vehicle patrol.
    Returns distance, duration, turn-by-turn steps, and overview polyline.
    Used by Patrol Agent to plan efficient routes through high-risk zones.
    """
    return get_patrol_route(
        origin_lat=origin_lat, origin_lon=origin_lon,
        waypoints=waypoints or [],
        destination_lat=destination_lat, destination_lon=destination_lon,
        travel_mode=travel_mode,
    )


def gmaps_street_view(
    lat: float, lon: float,
    heading: int = 0,
    fov: int = 90,
) -> dict:
    """
    Fetch ground-level Street View imagery for threat verification.
    heading: compass direction 0-360 (0=North, 90=East, 180=South, 270=West).
    fov: field of view in degrees (10-120, wider = more context).
    Used by Vision Agent to verify satellite anomalies at ground level.
    Returns base64 JPEG or has_coverage=False if no coverage exists.
    """
    return fetch_street_view(lat=lat, lon=lon, heading=heading, fov=fov)


# Register all as ADK FunctionTools
gmaps_satellite_tool      = FunctionTool(func=gmaps_satellite_image)
gmaps_marked_tool         = FunctionTool(func=gmaps_satellite_with_threat_markers)
gmaps_geocode_tool        = FunctionTool(func=gmaps_geocode)
gmaps_reverse_geocode_tool= FunctionTool(func=gmaps_reverse_geocode)
gmaps_terrain_tool        = FunctionTool(func=gmaps_nearby_terrain_features)
gmaps_route_tool          = FunctionTool(func=gmaps_patrol_route)
gmaps_streetview_tool     = FunctionTool(func=gmaps_street_view)
