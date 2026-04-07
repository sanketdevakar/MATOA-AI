"""
Google Cloud Storage MCP Tool — SENTINEL
------------------------------------------
Handles all satellite image storage. Replaces direct base64 storage in BigQuery.

Why GCS instead of BigQuery for images:
  BigQuery is a columnar analytics DB — storing 300KB base64 blobs per row
  makes queries slow, expensive, and the table unwieldy.
  GCS is an object store — $0.02/GB/month, instant read, signed URL access.

Operations:
  upload_image()       — store a PNG/JPEG from bytes or base64 → gs:// URI
  download_image()     — fetch bytes from a gs:// URI
  get_signed_url()     — generate a time-limited public URL for API responses
  delete_image()       — clean up old scan images
  image_exists()       — check before re-fetching

Bucket layout:
  gs://{bucket}/vision-scans/{date}/{scan_id}.png
  gs://{bucket}/vision-scans/{date}/{scan_id}_annotated.png

Setup:
  1. Create GCS bucket in GCP Console (same region as BigQuery — asia-south1)
  2. Grant service account: Storage Object Admin role on the bucket
  3. Add to .env: GCS_BUCKET_NAME=sentinel-vision-scans
  4. Add to .env: GOOGLE_APPLICATION_CREDENTIALS=keys/your-sa-key.json
"""

import base64
import io
from datetime import datetime, timedelta
from typing import Optional

from config import get_settings
from utils.logger import get_logger

settings = get_settings()
log = get_logger("gcs_tool")

_storage_client = None
_bucket         = None


def _get_bucket():
    """Lazy-init GCS client and bucket using service account credentials."""
    global _storage_client, _bucket
    if _bucket is not None:
        return _bucket
    try:
        from google.cloud import storage
        from google.oauth2 import service_account

        key_path = settings.google_application_credentials
        log.info("GCS init", key_path=key_path)

        if key_path:
            credentials = service_account.Credentials.from_service_account_file(
                key_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            _storage_client = storage.Client(
                project=settings.gcp_project_id,
                credentials=credentials,
            )
        else:
            # Fallback to application default credentials
            _storage_client = storage.Client(project=settings.gcp_project_id)

        _bucket = _storage_client.bucket(settings.gcs_bucket_name)
        log.info("GCS bucket connected", bucket=settings.gcs_bucket_name)
        return _bucket
    except Exception as e:
        log.error("GCS init failed", error=str(e))
        return None


def upload_image(
    image_data: bytes | str,
    scan_id: str,
    annotated: bool = False,
    content_type: str = "image/png",
) -> str:
    """
    Upload a satellite image to GCS.
    Returns the gs:// URI, or empty string on failure.

    Path: gs://{bucket}/vision-scans/{YYYY-MM-DD}/{scan_id}[_annotated].png
    """
    bucket = _get_bucket()
    if bucket is None:
        log.warning("GCS unavailable — image not persisted", scan_id=scan_id)
        return ""

    if isinstance(image_data, str):
        image_data = base64.standard_b64decode(image_data)

    date_prefix = datetime.utcnow().strftime("%Y-%m-%d")
    suffix      = "_annotated" if annotated else ""
    blob_path   = f"vision-scans/{date_prefix}/{scan_id}{suffix}.png"

    try:
        blob = bucket.blob(blob_path)
        blob.upload_from_string(image_data, content_type=content_type)
        uri = f"gs://{settings.gcs_bucket_name}/{blob_path}"
        log.info("Image uploaded to GCS", scan_id=scan_id, uri=uri, annotated=annotated)
        return uri
    except Exception as e:
        log.error("GCS upload failed", scan_id=scan_id, error=str(e))
        return ""


def download_image(gcs_uri: str) -> Optional[bytes]:
    """
    Download image bytes from a gs:// URI.
    Returns None on failure.
    """
    bucket = _get_bucket()
    if bucket is None or not gcs_uri.startswith("gs://"):
        return None

    try:
        blob_path = gcs_uri.replace(f"gs://{settings.gcs_bucket_name}/", "")
        blob = bucket.blob(blob_path)
        return blob.download_as_bytes()
    except Exception as e:
        log.error("GCS download failed", uri=gcs_uri, error=str(e))
        return None


def get_signed_url(gcs_uri: str, expiry_minutes: int = 60) -> str:
    """
    Generate a time-limited signed URL for direct browser/client access.
    Used by the API's GET /scan/image/{scan_id} endpoint.

    Returns the signed URL string, or empty string on failure.
    Requires service account key — application default credentials cannot sign.
    """
    bucket = _get_bucket()
    if bucket is None or not gcs_uri.startswith("gs://"):
        return ""

    try:
        blob_path = gcs_uri.replace(f"gs://{settings.gcs_bucket_name}/", "")
        blob = bucket.blob(blob_path)
        url = blob.generate_signed_url(
            expiration=timedelta(minutes=expiry_minutes),
            method="GET",
            version="v4",
        )
        return url
    except Exception as e:
        log.error("Signed URL generation failed", uri=gcs_uri, error=str(e))
        return ""


def image_exists(gcs_uri: str) -> bool:
    """Check if an image already exists in GCS — avoids redundant uploads."""
    bucket = _get_bucket()
    if bucket is None or not gcs_uri.startswith("gs://"):
        return False
    try:
        blob_path = gcs_uri.replace(f"gs://{settings.gcs_bucket_name}/", "")
        return bucket.blob(blob_path).exists()
    except Exception:
        return False


def delete_image(gcs_uri: str) -> bool:
    """Delete an image from GCS. Returns True on success."""
    bucket = _get_bucket()
    if bucket is None:
        return False
    try:
        blob_path = gcs_uri.replace(f"gs://{settings.gcs_bucket_name}/", "")
        bucket.blob(blob_path).delete()
        log.info("Image deleted from GCS", uri=gcs_uri)
        return True
    except Exception as e:
        log.error("GCS delete failed", uri=gcs_uri, error=str(e))
        return False