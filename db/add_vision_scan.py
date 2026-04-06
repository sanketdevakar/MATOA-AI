"""
VisionScan model — add this to db/models.py
Run this script once to add the vision_scans table to your existing DB.

Or simply add the VisionScan class to models.py and call create_tables() again
(SQLAlchemy's create_all is idempotent — it won't drop existing tables).
"""

VISION_SCAN_MODEL = '''
class VisionScan(Base):
    """
    Stores the result of each satellite/map imagery scan performed by the Vision Agent.
    One row per sector scan — created by daily scheduler or alert-triggered scans.
    """
    __tablename__ = "vision_scans"

    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id            = Column(String, ForeignKey("alerts.id"), nullable=True)   # null for scheduled scans
    sector              = Column(String(20), nullable=False)
    scanned_at          = Column(DateTime, nullable=False)
    image_source        = Column(String(50), nullable=False)    # mapbox|google|osm|placeholder
    image_lat           = Column(Float, nullable=False)
    image_lon           = Column(Float, nullable=False)
    zoom_level          = Column(Integer, default=14)
    anomalies_detected  = Column(Boolean, default=False)
    anomaly_count       = Column(Integer, default=0)
    threat_indicators   = Column(Text, nullable=True)           # JSON list
    overall_assessment  = Column(Text, nullable=True)
    recommended_action  = Column(String(50), nullable=True)     # none|patrol_verification|immediate_alert|...
    image_quality       = Column(String(20), nullable=True)     # good|partial|poor
    annotated_image_uri = Column(Text, nullable=True)           # base64 PNG with markers
'''

# ── Instructions ────────────────────────────────────────────────────────────
print("""
Add the following to db/models.py AFTER the existing model classes:

""" + VISION_SCAN_MODEL + """

Also add this import at the top of db/models.py (if not already present):
  from db.models import VisionScan   (for use in other modules)

Then run:
  python -c "from db.models import create_tables; create_tables()"

to create the new table without affecting existing data.
""")
