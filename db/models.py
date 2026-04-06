from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text,
    Boolean, ForeignKey, Enum as SAEnum, create_engine
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum

from config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, echo=settings.app_env == "development")
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Enums ──────────────────────────────────────────────────────────────────────

class AlertType(str, enum.Enum):
    PERIMETER_BREACH = "perimeter_breach"
    DRONE_SIGHTING    = "drone_sighting"
    MANUAL_REPORT     = "manual_report"
    SEISMIC_ACTIVITY  = "seismic_activity"

class AlertStatus(str, enum.Enum):
    RECEIVED    = "received"
    PROCESSING  = "processing"
    AWAITING_HITL = "awaiting_hitl"
    APPROVED    = "approved"
    REJECTED    = "rejected"
    COMPLETED   = "completed"

class Severity(str, enum.Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"

class ActionStatus(str, enum.Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED   = "failed"


# ── Models ─────────────────────────────────────────────────────────────────────

class Alert(Base):
    """Raw event from a sensor, drone, or manual trigger."""
    __tablename__ = "alerts"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    alert_type = Column(SAEnum(AlertType), nullable=False)
    sector     = Column(String(20), nullable=False)           # e.g. "SECTOR-7"
    latitude   = Column(Float, nullable=True)
    longitude  = Column(Float, nullable=True)
    raw_payload= Column(Text, nullable=True)                  # JSON string from sensor
    status     = Column(SAEnum(AlertStatus), default=AlertStatus.RECEIVED)
    severity   = Column(SAEnum(Severity), nullable=True)      # filled by Intel Agent
    threat_score = Column(Integer, nullable=True)             # 1-10, filled by Intel Agent

    # Relationships
    pending_actions = relationship("PendingAction", back_populates="alert")
    patrol_logs     = relationship("PatrolLog", back_populates="alert")
    sitrep_drafts   = relationship("SitrepDraft", back_populates="alert")
    audit_logs      = relationship("AuditLog", back_populates="alert")


class HistoricalIncident(Base):
    """Seeded historical data — Intel Agent uses this for threat scoring."""
    __tablename__ = "historical_incidents"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    occurred_at = Column(DateTime, nullable=False)
    sector      = Column(String(20), nullable=False)
    incident_type = Column(String(100), nullable=False)
    severity    = Column(SAEnum(Severity), nullable=False)
    description = Column(Text, nullable=True)
    resolved    = Column(Boolean, default=False)


class PendingAction(Base):
    """Proposed actions waiting for commander HITL approval."""
    __tablename__ = "pending_actions"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id     = Column(String, ForeignKey("alerts.id"), nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)
    agent_name   = Column(String(50), nullable=False)   # "patrol_agent", "comms_agent" etc.
    action_type  = Column(String(100), nullable=False)  # "reschedule_patrol", "send_brief" etc.
    description  = Column(Text, nullable=False)         # Human-readable summary for commander
    payload      = Column(Text, nullable=False)         # JSON — exact MCP call parameters
    status       = Column(SAEnum(ActionStatus), default=ActionStatus.PENDING)
    decided_at   = Column(DateTime, nullable=True)
    decided_by   = Column(String(100), nullable=True)   # commander ID
    reject_reason= Column(Text, nullable=True)

    alert        = relationship("Alert", back_populates="pending_actions")


class PatrolLog(Base):
    """Patrol schedule entries created or modified by the Patrol Agent."""
    __tablename__ = "patrol_logs"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id      = Column(String, ForeignKey("alerts.id"), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    sector        = Column(String(20), nullable=False)
    patrol_start  = Column(DateTime, nullable=False)
    patrol_end    = Column(DateTime, nullable=False)
    unit_assigned = Column(String(100), nullable=False)
    route_notes   = Column(Text, nullable=True)
    calendar_event_id = Column(String(200), nullable=True)  # Google Calendar event ID

    alert = relationship("Alert", back_populates="patrol_logs")


class SitrepDraft(Base):
    """Situation reports drafted by the Comms Agent."""
    __tablename__ = "sitrep_drafts"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id      = Column(String, ForeignKey("alerts.id"), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    sector        = Column(String(20), nullable=False)
    threat_score  = Column(Integer, nullable=True)
    summary       = Column(Text, nullable=False)           # LLM-generated sitrep
    recommended_actions = Column(Text, nullable=True)
    notes_mcp_id  = Column(String(200), nullable=True)     # Notes MCP reference

    alert = relationship("Alert", back_populates="sitrep_drafts")


class AuditLog(Base):
    """Immutable record of every agent action and commander decision."""
    __tablename__ = "audit_logs"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id   = Column(String, ForeignKey("alerts.id"), nullable=True)
    timestamp  = Column(DateTime, default=datetime.utcnow, nullable=False)
    actor      = Column(String(100), nullable=False)   # agent name or commander ID
    action     = Column(String(200), nullable=False)
    detail     = Column(Text, nullable=True)
    success    = Column(Boolean, default=True)

    alert = relationship("Alert", back_populates="audit_logs")


class VisionScan(Base):
    """
    Stores the result of each satellite/map imagery scan by the Vision Agent.
    One row per scan — created by daily scheduler or alert-triggered scans.
    """
    __tablename__ = "vision_scans"

    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id            = Column(String, ForeignKey("alerts.id"), nullable=True)
    sector              = Column(String(20), nullable=False)
    scanned_at          = Column(DateTime, nullable=False)
    image_source        = Column(String(50), nullable=False)
    image_lat           = Column(Float, nullable=False)
    image_lon           = Column(Float, nullable=False)
    zoom_level          = Column(Integer, default=14)
    anomalies_detected  = Column(Boolean, default=False)
    anomaly_count       = Column(Integer, default=0)
    threat_indicators   = Column(Text, nullable=True)
    overall_assessment  = Column(Text, nullable=True)
    recommended_action  = Column(String(50), nullable=True)
    image_quality       = Column(String(20), nullable=True)
    annotated_image_uri = Column(Text, nullable=True)  # gs:// URI


def create_tables():
    Base.metadata.create_all(bind=engine)
