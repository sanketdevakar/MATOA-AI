"""
Google ADK Agent Definitions — SENTINEL v3
--------------------------------------------
All agents use Gemini 2.5 Flash via Vertex AI.

"""
import os
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
os.environ["GOOGLE_CLOUD_PROJECT"] = "commandmind"
os.environ["GOOGLE_CLOUD_LOCATION"] = "asia-south1"
from google.adk.agents import LlmAgent, SequentialAgent

from config import get_settings
from adk.tools import (
    audit_log_tool, update_threat_tool, update_status_tool,
    history_tool,
    patrol_schedule_tool, patrol_hitl_tool,
    sitrep_save_tool, sitrep_publish_tool, sitrep_hitl_tool,
    geo_image_tool, vision_save_tool,
    gmaps_satellite_tool, gmaps_marked_tool,
    gmaps_geocode_tool, gmaps_reverse_geocode_tool,
    gmaps_terrain_tool, gmaps_route_tool, gmaps_streetview_tool,
)

settings = get_settings()

# ── Model — Gemini 2.0 Flash via Vertex AI (used by all agents) ───────────────
GEMINI_FLASH = settings.gemini_model


# ── 1. Vision Agent ────────────────────────────────────────────────────────────

vision_agent = LlmAgent(
    name="vision_agent",
    model=GEMINI_FLASH,
    description=(
        "Fetches satellite imagery (Google Maps + Mapbox) for the sector, "
        "analyses it using deep visual reasoning for security anomalies, "
        "and optionally verifies findings with Street View imagery."
    ),
    instruction="""You are the Vision Intelligence Agent for SENTINEL, an Indian Army border surveillance system.

STEP 1 — Fetch primary imagery:
  Call gmaps_satellite_image with lat/lon from session state (zoom=15, map_type='satellite').
  If Google Maps unavailable, call fetch_sector_satellite_image as fallback.

STEP 2 — Ground verification (if anomaly confidence > 0.6):
  Call gmaps_street_view for ground-level confirmation (heading=0, then heading=180).
  Note: has_coverage=False is expected in remote border areas.

STEP 3 — Annotate (if anomalies found):
  Call gmaps_satellite_with_threat_markers with detected anomaly locations.

STEP 4 — Save and audit:
  Call save_vision_scan_result with complete findings.
  Call write_audit_log confirming completion.

Threat guidance:
  vehicle concentrations > 5 = high | human gatherings in restricted zones = immediate_alert
  terrain disturbance = patrol_verification | temporary structures = patrol_verification+
""",
    tools=[
        gmaps_satellite_tool, gmaps_marked_tool, gmaps_streetview_tool,
        geo_image_tool, vision_save_tool, audit_log_tool,
    ],
    output_key="vision_result",
)


# ── 2. Intel Agent ─────────────────────────────────────────────────────────────

intel_agent = LlmAgent(
    name="intel_agent",
    model=GEMINI_FLASH,
    description=(
        "Scores threat 1-10 using BigQuery 14-day history, vision findings, "
        "Google Maps terrain context, and precise geocoded location."
    ),
    instruction="""You are the Intel Agent for SENTINEL, an Indian Army surveillance system.

STEP 1: Call get_sector_incident_history (sector from session, 14 days).
STEP 2: Read vision_result from session state.
STEP 3: Call gmaps_nearby_terrain_features (alert lat/lon, radius=2000m).
         Look for: bridges, border roads, river crossings, dense vegetation, settlements.
STEP 4: Call gmaps_reverse_geocode (alert lat/lon) for precise location name.
STEP 5: Compute threat_score 1-10:
  Base score from history:  0 incidents=1, 1-2=+1, 3-5=+2, 6+=+3
  Vision contribution:      confidence 0.5-0.7=+1, 0.7-0.9=+2, >0.9=+3
  Terrain factor:           sensitive feature within 500m=+1
  Max score: 10 (cap at 10)
STEP 6: Call update_alert_threat_score. Call write_audit_log.
""",
    tools=[
        history_tool, gmaps_terrain_tool, gmaps_reverse_geocode_tool,
        update_threat_tool, audit_log_tool,
    ],
    output_key="intel_result",
)


# ── 3. Patrol Agent ────────────────────────────────────────────────────────────

patrol_agent = LlmAgent(
    name="patrol_agent",
    model=GEMINI_FLASH,
    description=(
        "Plans optimised patrol routes using Google Directions API. "
        "Creates HITL pending actions (score 5-7) or executes directly (score 8+)."
    ),
    instruction="""You are the Patrol Agent for SENTINEL, an Indian Army surveillance system.

STEP 1: Read threat_score, sector, lat, lon from session state.
STEP 2: Decision:
  score 1-4: No action. Done.
  score 5-7: Plan route + create HITL pending action.
  score 8+:  Plan route + execute immediately (no HITL).

STEP 3 (score >= 5): Call gmaps_patrol_route:
  origin: nearest base (estimate from sector coords using gmaps_geocode if needed)
  destination: a point 3-5 km from the alert location in the direction of the nearest border
  waypoints: maximum 2 checkpoints, each within 5 km of the alert location
  travel_mode: 'walking' for border patrol
  Keep total patrol distance under 20 km.
  travel_mode: 'walking' for foot patrol

STEP 4: Use route distance/duration in the action description.
  score 5-7: Call create_pending_action_for_patrol (HITL required).
  score 8+:  Call create_patrol_schedule directly (immediate execution).

Unit naming convention:
  "Alpha Company - 3rd Platoon, 8 Sikh LI"
  "Bravo Company - 2nd Platoon, 9 Para SF"
  "Charlie Troop - 15 Corps Recce Battalion"

STEP 5: Call write_audit_log.
""",
    tools=[
        gmaps_route_tool, gmaps_geocode_tool,
        patrol_schedule_tool, patrol_hitl_tool, audit_log_tool,
    ],
    output_key="patrol_result",
)


# ── 4. Comms Agent ─────────────────────────────────────────────────────────────

comms_agent = LlmAgent(
    name="comms_agent",
    model=GEMINI_FLASH,
    description=(
        "Drafts Indian Army-style sitrep using all pipeline context including "
        "Google Maps location data. Publishes directly (ROUTINE) or via HITL gate."
    ),
    instruction="""You are the Comms Agent for SENTINEL, an Indian Army surveillance system.

STEP 1: Read from session: threat_score, severity, sector, alert_location_name,
        terrain_features, vision_result, patrol_result, intel_result, lat, lon.

STEP 2: If alert_location_name missing, call gmaps_reverse_geocode for precise location.

STEP 3: Draft sitrep:
  title format:   SITREP/[CLASSIFICATION]/[SECTOR]/[DDHHMMZMmmYY]
                  Example: SITREP/IMMEDIATE/SECTOR-7/041430ZNOV25
  summary: 3-4 sentences — WHAT detected, WHERE precisely, WHEN, THREAT LEVEL
  recommended_actions: 2-3 numbered, specific, actionable points
  duty_officer_task: one immediate action sentence
  classification: ROUTINE(1-4) | PRIORITY(5-6) | IMMEDIATE(7-8) | FLASH(9-10)

STEP 4: Call save_sitrep_draft to persist to BigQuery.
  ROUTINE: call publish_sitrep_to_notes directly.
  PRIORITY/IMMEDIATE/FLASH: call create_pending_action_for_sitrep (HITL).

STEP 5: Call write_audit_log.
""",
    tools=[
        gmaps_reverse_geocode_tool,
        sitrep_save_tool, sitrep_publish_tool, sitrep_hitl_tool, audit_log_tool,
    ],
    output_key="comms_result",
)


# ── Primary SequentialAgent ────────────────────────────────────────────────────

sentinel_pipeline = SequentialAgent(
    name="sentinel_command_agent",
    description=(
        "Primary SENTINEL command agent. Sequential pipeline: "
        "Vision (Gemini) → Intel (Gemini) → Patrol (Gemini) → Comms (Gemini). "
        "Uses Google Maps Platform throughout. State shared via ADK session."
    ),
    sub_agents=[vision_agent, intel_agent, patrol_agent, comms_agent],
)