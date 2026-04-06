-- SENTINEL BigQuery Schema
-- Run once in your GCP project to create all tables.
-- gcloud: bq mk --dataset ${GCP_PROJECT_ID}:sentinel_db
-- Then: bq query --use_legacy_sql=false < db/bq_schema.sql

CREATE TABLE IF NOT EXISTS `sentinel_db.alerts` (
  id            STRING    NOT NULL,
  created_at    TIMESTAMP NOT NULL,
  alert_type    STRING    NOT NULL,
  sector        STRING    NOT NULL,
  latitude      FLOAT64,
  longitude     FLOAT64,
  raw_payload   STRING,
  status        STRING    NOT NULL,
  severity      STRING,
  threat_score  INT64
);

CREATE TABLE IF NOT EXISTS `sentinel_db.historical_incidents` (
  id            STRING    NOT NULL,
  occurred_at   TIMESTAMP NOT NULL,
  sector        STRING    NOT NULL,
  incident_type STRING    NOT NULL,
  severity      STRING    NOT NULL,
  description   STRING,
  resolved      BOOL      NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS `sentinel_db.pending_actions` (
  id            STRING    NOT NULL,
  alert_id      STRING    NOT NULL,
  created_at    TIMESTAMP NOT NULL,
  agent_name    STRING    NOT NULL,
  action_type   STRING    NOT NULL,
  description   STRING    NOT NULL,
  payload       STRING    NOT NULL,
  status        STRING    NOT NULL,
  decided_at    TIMESTAMP,
  decided_by    STRING,
  reject_reason STRING
);

CREATE TABLE IF NOT EXISTS `sentinel_db.patrol_logs` (
  id                STRING    NOT NULL,
  alert_id          STRING,
  created_at        TIMESTAMP NOT NULL,
  sector            STRING    NOT NULL,
  patrol_start      TIMESTAMP NOT NULL,
  patrol_end        TIMESTAMP NOT NULL,
  unit_assigned     STRING    NOT NULL,
  route_notes       STRING,
  calendar_event_id STRING
);

CREATE TABLE IF NOT EXISTS `sentinel_db.sitrep_drafts` (
  id                  STRING    NOT NULL,
  alert_id            STRING    NOT NULL,
  created_at          TIMESTAMP NOT NULL,
  sector              STRING    NOT NULL,
  threat_score        INT64,
  summary             STRING    NOT NULL,
  recommended_actions STRING,
  notes_mcp_id        STRING
);

CREATE TABLE IF NOT EXISTS `sentinel_db.audit_logs` (
  id         STRING    NOT NULL,
  alert_id   STRING,
  timestamp  TIMESTAMP NOT NULL,
  actor      STRING    NOT NULL,
  action     STRING    NOT NULL,
  detail     STRING,
  success    BOOL      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS `sentinel_db.vision_scans` (
  id                  STRING    NOT NULL,
  alert_id            STRING,
  sector              STRING    NOT NULL,
  scanned_at          TIMESTAMP NOT NULL,
  image_source        STRING    NOT NULL,
  image_lat           FLOAT64   NOT NULL,
  image_lon           FLOAT64   NOT NULL,
  zoom_level          INT64     NOT NULL,
  anomalies_detected  BOOL      NOT NULL DEFAULT FALSE,
  anomaly_count       INT64     NOT NULL DEFAULT 0,
  threat_indicators   STRING,
  overall_assessment  STRING,
  recommended_action  STRING,
  image_quality       STRING,
  annotated_image_uri STRING  -- gs:// URI, image stored in GCS
);
