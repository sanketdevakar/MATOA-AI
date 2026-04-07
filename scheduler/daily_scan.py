"""
Daily Surveillance Scheduler — Cloud Logging version
Fix 7: Structured logging replaces all print() calls.
"""
import json
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from config import get_settings
from db import bigquery_client as bq
from utils.logger import get_logger

settings = get_settings()
log      = get_logger("scheduler")

_scheduler: BackgroundScheduler = None


def get_sector_list() -> list[str]:
    try:
        return list(json.loads(settings.sector_coords).keys())
    except Exception:
        return ["SECTOR-1", "SECTOR-2", "SECTOR-4", "SECTOR-5", "SECTOR-7", "SECTOR-9"]


def daily_scan_job():
    from agents import vision_agent
    from db import bigquery_client as bq

    sectors    = get_sector_list()
    scan_date  = datetime.utcnow().strftime("%Y-%m-%d")
    log.info("Daily scan started", scan_date=scan_date, sector_count=len(sectors))

    results = []
    for sector in sectors:
        try:
            log.info("Scanning sector", sector=sector)
            assessment = vision_agent.scan_sector(sector=sector, zoom=14)
            results.append({
                "sector":           sector,
                "anomalies":        assessment.get("anomaly_count", 0),
                "action":           assessment.get("recommended_action", "none"),
                "triggered_alert":  assessment.get("triggered_alert"),
                "status":           "ok",
            })
        except Exception as e:
            log.error("Sector scan failed", sector=sector, error=str(e))
            results.append({"sector": sector, "status": "error", "error": str(e)})

    triggered = [r for r in results if r.get("triggered_alert")]
    errors    = [r for r in results if r.get("status") == "error"]
    clean     = [r for r in results if r.get("anomalies", 0) == 0 and r.get("status") == "ok"]

    summary = (
        f"Daily scan complete. Sectors={len(sectors)} "
        f"Clean={len(clean)} Alerts={len(triggered)} Errors={len(errors)}"
    )
    bq.insert_audit_log(
        actor="scheduler", action="daily_scan_complete",
        detail=json.dumps({"summary": summary, "results": results}),
        success=len(errors) == 0,
    )
    log.info("Daily scan complete",
             sectors=len(sectors), clean=len(clean),
             alerts=len(triggered), errors=len(errors))
    if triggered:
        log.warning("Alerts triggered during daily scan",
                    sectors=[r["sector"] for r in triggered])


def on_job_error(event):
    log.error("Scheduled job failed", job_id=event.job_id, error=str(event.exception))


def on_job_executed(event):
    log.info("Scheduled job completed", job_id=event.job_id)


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        daily_scan_job,
        trigger=CronTrigger(
            hour=settings.daily_scan_hour,
            minute=settings.daily_scan_minute,
            timezone="Asia/Kolkata",
        ),
        id="daily_surveillance_scan",
        name="Daily sector surveillance scan",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_listener(on_job_error,    EVENT_JOB_ERROR)
    _scheduler.add_listener(on_job_executed, EVENT_JOB_EXECUTED)
    _scheduler.start()

    next_run = _scheduler.get_job("daily_surveillance_scan").next_run_time
    log.info("Scheduler started",
             next_scan=next_run.strftime("%Y-%m-%d %H:%M IST"))
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")


def trigger_immediate_scan(sector: str = None):
    global _scheduler
    if sector:
        job_id = f"manual_scan_{sector}_{datetime.utcnow().timestamp():.0f}"
        _scheduler.add_job(_single_sector_scan, args=[sector], id=job_id,
                           name=f"Manual scan: {sector}", replace_existing=False)
        log.info("Manual scan queued", sector=sector, job_id=job_id)
    else:
        job_id = f"manual_scan_all_{datetime.utcnow().timestamp():.0f}"
        _scheduler.add_job(daily_scan_job, id=job_id,
                           name="Manual scan: all sectors", replace_existing=False)
        log.info("Manual full scan queued", job_id=job_id)
    return job_id


def _single_sector_scan(sector: str):
    from agents import vision_agent
    from db import bigquery_client as bq
    vision_agent.scan_sector(sector=sector, zoom=14)
