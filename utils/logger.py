"""
Structured Cloud Logging — SENTINEL
--------------------------------------
Replaces all print() calls across agents, ADK runner, and scheduler.

In production (APP_ENV=production or GCP credentials present):
  → Writes structured JSON logs to Google Cloud Logging
  → Each log entry has: severity, agent_name, alert_id, sector, action
  → Queryable in Cloud Logging console with log-based metric alerts

In development (APP_ENV=development):
  → Rich-formatted console output (same structured data, human-readable)
  → No GCP calls, no credentials needed

Usage:
  from utils.logger import get_logger
  log = get_logger("intel_agent")
  log.info("Threat assessment complete", alert_id="abc", sector="SECTOR-7", score=8)
  log.warning("MCP timeout", tool="calendar_mcp", retry=2)
  log.error("Pipeline failed", alert_id="abc", error=str(e))
"""

import os
import json
import logging
from datetime import datetime
from typing import Any

from config import get_settings

settings = get_settings()

# Severity → Cloud Logging severity mapping
SEVERITY = {
    "debug":    "DEBUG",
    "info":     "INFO",
    "warning":  "WARNING",
    "error":    "ERROR",
    "critical": "CRITICAL",
}

# Try to initialise Cloud Logging client once
_cloud_client = None
_cloud_logger  = None

def _init_cloud_logging():
    global _cloud_client, _cloud_logger
    if _cloud_client is not None:
        return True
    try:
        import google.cloud.logging
        _cloud_client = google.cloud.logging.Client(project=settings.gcp_project_id)
        _cloud_logger  = _cloud_client.logger("sentinel")
        return True
    except Exception:
        return False


def _use_cloud() -> bool:
    """Use Cloud Logging in production when GCP creds are available."""
    return (
        settings.app_env == "production"
        and bool(settings.google_application_credentials)
        and _init_cloud_logging()
    )


class SentinelLogger:
    """
    Structured logger for a named SENTINEL component.
    Writes to Cloud Logging in production, rich console in dev.
    """

    def __init__(self, component: str):
        self.component = component
        self._console  = logging.getLogger(f"sentinel.{component}")
        if not self._console.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
                datefmt="%H:%M:%S",
            ))
            self._console.addHandler(handler)
            self._console.setLevel(logging.DEBUG)

    def _log(self, level: str, message: str, **labels):
        """Core log dispatcher."""
        payload = {
            "timestamp":  datetime.utcnow().isoformat(),
            "component":  self.component,
            "severity":   SEVERITY.get(level, "INFO"),
            "message":    message,
            **{k: str(v) for k, v in labels.items() if v is not None},
        }

        if _use_cloud():
            try:
                _cloud_logger.log_struct(
                    payload,
                    severity=payload["severity"],
                    labels={
                        "component": self.component,
                        "alert_id":  str(labels.get("alert_id", "")),
                        "sector":    str(labels.get("sector", "")),
                    },
                )
                return
            except Exception:
                pass   # Fall through to console on cloud failure

        # Console fallback — colour-coded by severity
        colors = {
            "debug": "\033[37m", "info": "\033[36m",
            "warning": "\033[33m", "error": "\033[31m", "critical": "\033[35m",
        }
        reset = "\033[0m"
        color = colors.get(level, "")

        # Build compact label string for console
        label_str = "  ".join(f"{k}={v}" for k, v in labels.items() if v is not None)
        extra = f"  {label_str}" if label_str else ""

        print(f"{color}[{self.component}] {message}{extra}{reset}")

    def debug(self, msg: str, **kw):    self._log("debug",    msg, **kw)
    def info(self, msg: str, **kw):     self._log("info",     msg, **kw)
    def warning(self, msg: str, **kw):  self._log("warning",  msg, **kw)
    def error(self, msg: str, **kw):    self._log("error",    msg, **kw)
    def critical(self, msg: str, **kw): self._log("critical", msg, **kw)

    def pipeline_event(self, action: str, alert_id: str = None,
                       sector: str = None, success: bool = True, **kw):
        """Convenience method for pipeline step logging — always INFO or ERROR."""
        level = "info" if success else "error"
        self._log(level, action, alert_id=alert_id, sector=sector, **kw)


# Cache loggers by component name
_loggers: dict[str, SentinelLogger] = {}

def get_logger(component: str) -> SentinelLogger:
    if component not in _loggers:
        _loggers[component] = SentinelLogger(component)
    return _loggers[component]
