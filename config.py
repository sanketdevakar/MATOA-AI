"""
SENTINEL Configuration
------------------------
All settings loaded from environment variables / .env file.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file
BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    # pydantic-settings v2 syntax — replaces inner Config class
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Gemini ───────────────────────────────────────────────
    gemini_model: str = "gemini-2.5-flash"

    # ── Google Cloud ─────────────────────────────────────────
    gcp_project_id:   str = "commandmind"
    bq_dataset:       str = "sentinel_db"
    gcp_location:     str = "asia-south1"
    google_application_credentials: str = ""
    google_genai_use_vertexai: str = "1"
    google_calendar_id: str = ""

    # ── MCP Toolbox ──────────────────────────────────────────
    mcp_toolbox_url: str = "https://sentinel-toolbox-vgqcztjqeq-el.a.run.app"

    # ── Cloud Storage ─────────────────────────────────────────
    gcs_bucket_name: str = "sentinel-vision-scans"

    # ── Cloud Pub/Sub ─────────────────────────────────────────
    pubsub_topic_id:        str = "sentinel-alerts"
    pubsub_subscription_id: str = "sentinel-alerts-sub"
    use_pubsub:             bool = False

    # ── App ──────────────────────────────────────────────────
    app_env:           str = "development"
    secret_key:        str = "dev-secret"
    commander_api_key: str = "commander-secret-key-123"

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

    # ── Daily scan schedule ───────────────────────────────────
    daily_scan_hour:   int = 5
    daily_scan_minute: int = 30

    # ── Sector coordinates ───────────────────────────────────
    sector_coords: str = (
        '{"SECTOR-1":"34.15,74.85","SECTOR-2":"34.20,74.90",'
        '"SECTOR-4":"34.08,74.70","SECTOR-5":"34.12,74.80",'
        '"SECTOR-7":"34.05,74.36","SECTOR-9":"34.18,74.95"}'
    )


# Manual singleton — no lru_cache so Cloud Run secrets are always read fresh
_settings: Settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        # os.environ.get ensures Cloud Run injected secrets always win
        env_override = {}
        if os.environ.get("COMMANDER_API_KEY"):
            env_override["commander_api_key"] = os.environ["COMMANDER_API_KEY"]
        _settings = Settings(**env_override)
    return _settings