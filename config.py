"""
SENTINEL Configuration
------------------------
All settings loaded from environment variables / .env file.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):


    # ── Gemini (for ADK Patrol + Comms agents) ───────────────
    gemini_model: str = "gemini-2.0-flash"

    # ── Google Cloud ─────────────────────────────────────────
    gcp_project_id:   str = "your-gcp-project-id"
    bq_dataset:       str = "sentinel_db"
    gcp_location:     str = "asia-south1"
    google_application_credentials: str = ""
    google_genai_use_vertexai: str = "1"
    google_calendar_id: str = ""

    # ── MCP Toolbox (BigQuery gateway) ───────────────────────
    mcp_toolbox_url: str = "http://localhost:5000"

    # ── Cloud Storage (images) ───────────────────────────────
    gcs_bucket_name: str = "sentinel-vision-scans"

    # ── Cloud Pub/Sub (async event bus) ──────────────────────
    pubsub_topic_id:        str = "sentinel-alerts"
    pubsub_subscription_id: str = "sentinel-alerts-sub"
    use_pubsub:             bool = False

    # ── App ──────────────────────────────────────────────────
    app_env:           str = "development"
    secret_key:        str = "dev-secret"
    commander_api_key: str = ""

    # ── MCP tool endpoints ───────────────────────────────────
    calendar_mcp_url: str = "https://gcal.mcp.claude.com/mcp"
    tasks_mcp_url:    str = "https://tasks.mcp.claude.com/mcp"
    notes_mcp_url:    str = "https://notes.mcp.claude.com/mcp"

    # ── Alert thresholds ─────────────────────────────────────
    threat_auto_escalate_score: int = 8
    hitl_required_above_score:  int = 5

    # ── Geospatial ───────────────────────────────────────────
    map_tile_url:        str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    google_maps_api_key: str = ""
    mapbox_token:        str = ""

    # ── Daily scan schedule (IST, 24h) ───────────────────────
    daily_scan_hour:   int = 5
    daily_scan_minute: int = 30

    # ── Sector coordinates ───────────────────────────────────
    sector_coords: str = (
        '{"SECTOR-1":"34.15,74.85","SECTOR-2":"34.20,74.90",'
        '"SECTOR-4":"34.08,74.70","SECTOR-5":"34.12,74.80",'
        '"SECTOR-7":"34.05,74.36","SECTOR-9":"34.18,74.95"}'
    )

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()