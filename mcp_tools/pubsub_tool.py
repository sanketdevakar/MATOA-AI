"""
Cloud Pub/Sub Tool — SENTINEL Event Bus
-----------------------------------------
Makes the alert ingestion pipeline fully async and non-blocking.

Before (synchronous — bad):
  POST /alert → run entire ADK pipeline (30s) → return response
  Sensor HTTP request hangs for 30 seconds. On timeout: alert lost.

After (async — correct):
  POST /alert → publish to Pub/Sub → return 202 immediately (< 100ms)
  Background worker subscribes → runs ADK pipeline → updates BigQuery
  Sensor gets instant acknowledgement. Pipeline runs in background.

Architecture:
  Publisher  : FastAPI ingest_alert endpoint
  Topic      : projects/{project}/topics/sentinel-alerts
  Subscriber : sentinel_worker() — runs in background thread on startup
  Dead-letter: projects/{project}/topics/sentinel-alerts-dead-letter

Setup in GCP Console:
  1. Create topic: sentinel-alerts
  2. Create subscription: sentinel-alerts-sub (pull type)
  3. Create dead-letter topic: sentinel-alerts-dead-letter
  4. Grant service account: Pub/Sub Publisher + Subscriber roles
  5. Add to .env: PUBSUB_TOPIC_ID=sentinel-alerts
                  PUBSUB_SUBSCRIPTION_ID=sentinel-alerts-sub
"""

import json
import threading
from datetime import datetime
from typing import Callable

from config import get_settings
from utils.logger import get_logger

settings = get_settings()
log = get_logger("pubsub_tool")

_publisher  = None
_subscriber = None
_topic_path = None
_sub_path   = None


def _get_publisher():
    global _publisher, _topic_path
    if _publisher is not None:
        return _publisher, _topic_path
    try:
        from google.cloud import pubsub_v1
        _publisher  = pubsub_v1.PublisherClient()
        _topic_path = _publisher.topic_path(
            settings.gcp_project_id, settings.pubsub_topic_id
        )
        log.info("Pub/Sub publisher ready", topic=_topic_path)
        return _publisher, _topic_path
    except Exception as e:
        log.error("Pub/Sub publisher init failed", error=str(e))
        return None, None


def _get_subscriber():
    global _subscriber, _sub_path
    if _subscriber is not None:
        return _subscriber, _sub_path
    try:
        from google.cloud import pubsub_v1
        _subscriber = pubsub_v1.SubscriberClient()
        _sub_path   = _subscriber.subscription_path(
            settings.gcp_project_id, settings.pubsub_subscription_id
        )
        return _subscriber, _sub_path
    except Exception as e:
        log.error("Pub/Sub subscriber init failed", error=str(e))
        return None, None


def publish_alert(alert: dict) -> str:
    """
    Publish an alert dict to the Pub/Sub topic.
    Returns the message ID on success, empty string on failure.

    The alert dict is JSON-serialised and published as the message data.
    Attributes include alert_id and sector for server-side filtering.
    """
    publisher, topic_path = _get_publisher()
    if publisher is None:
        log.warning("Pub/Sub unavailable — falling back to sync pipeline",
                    alert_id=alert.get("id"))
        return ""

    try:
        data = json.dumps(alert, default=str).encode("utf-8")
        future = publisher.publish(
            topic_path,
            data=data,
            alert_id=str(alert.get("id", "")),
            sector=str(alert.get("sector", "")),
            alert_type=str(alert.get("alert_type", "")),
            published_at=datetime.utcnow().isoformat(),
        )
        message_id = future.result(timeout=10)
        log.info("Alert published to Pub/Sub",
                 alert_id=alert.get("id"), sector=alert.get("sector"),
                 message_id=message_id)
        return message_id
    except Exception as e:
        log.error("Pub/Sub publish failed", alert_id=alert.get("id"), error=str(e))
        return ""


def start_subscriber_worker(pipeline_fn: Callable):
    """
    Start a background thread that subscribes to the Pub/Sub topic
    and runs pipeline_fn(alert_dict) for each received message.

    Called once on FastAPI startup. Runs forever in a daemon thread.
    If Pub/Sub is unavailable, this is a no-op (sync fallback still works).
    """
    subscriber, sub_path = _get_subscriber()
    if subscriber is None:
        log.warning("Pub/Sub subscriber unavailable — using sync pipeline only")
        return

    def _message_handler(message):
        """Process one Pub/Sub message — runs pipeline, acks or nacks."""
        alert_id = message.attributes.get("alert_id", "unknown")
        try:
            alert = json.loads(message.data.decode("utf-8"))
            log.info("Pub/Sub message received",
                     alert_id=alert_id, sector=message.attributes.get("sector"))
            pipeline_fn(alert)
            message.ack()
            log.info("Pub/Sub message acked", alert_id=alert_id)
        except Exception as e:
            log.error("Pub/Sub message processing failed",
                      alert_id=alert_id, error=str(e))
            message.nack()   # Message returns to queue for retry

    def _run_subscriber():
        log.info("Pub/Sub subscriber worker started", subscription=sub_path)
        streaming_pull = subscriber.subscribe(sub_path, callback=_message_handler)
        try:
            streaming_pull.result()   # Blocks forever
        except Exception as e:
            log.error("Pub/Sub subscriber crashed", error=str(e))

    thread = threading.Thread(target=_run_subscriber, daemon=True, name="pubsub-worker")
    thread.start()
    log.info("Pub/Sub worker thread started")
