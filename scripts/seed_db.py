"""
Seed BigQuery with 14 days of historical incidents.
Run once after creating the BQ tables:
  python scripts/seed_db.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import random
from datetime import datetime, timedelta
from db import bigquery_client as bq

SECTORS = ["SECTOR-1","SECTOR-2","SECTOR-4","SECTOR-5","SECTOR-7","SECTOR-9"]
TYPES   = ["perimeter_breach_attempt","unidentified_drone_sighting",
           "suspicious_vehicle_movement","communications_jamming",
           "wire_cutting_attempt","unauthorized_personnel","seismic_anomaly"]
SEVS    = ["low","medium","high","critical"]
SEV_W   = [0.45, 0.30, 0.18, 0.07]
HOT     = {"SECTOR-4": 2.5, "SECTOR-7": 2.0}

def seed():
    print("Seeding BigQuery historical_incidents...")
    now = datetime.utcnow()
    count = 0
    for days_back in range(1, 15):
        base = now - timedelta(days=days_back)
        for sector in SECTORS:
            weight = HOT.get(sector, 1.0)
            n = random.choices([0,1,2,3], weights=[max(0.5,2.0-weight), weight, weight*0.6, weight*0.3])[0]
            for _ in range(n):
                sev = random.choices(SEVS, weights=SEV_W)[0]
                if sector in HOT and random.random() < 0.4:
                    sev = random.choice(["high","critical"])
                occurred = base.replace(
                    hour=random.randint(0,23), minute=random.randint(0,59))
                bq.insert_historical_incident(
                    sector=sector,
                    incident_type=random.choice(TYPES),
                    severity=sev,
                    occurred_at=occurred.isoformat(),
                    description=f"Historical incident — auto-seeded",
                    resolved=random.random() > 0.15,
                )
                count += 1
    print(f"Seeded {count} incidents across {len(SECTORS)} sectors.")
    print("Hot zones: SECTOR-4 and SECTOR-7 (higher incident density)")

if __name__ == "__main__":
    seed()
