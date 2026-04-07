"""
Geospatial MCP Tool — SENTINEL
---------------------------------
Fetches map/satellite imagery for a sector using a 3-tier source chain:
  1. Mapbox Satellite  (if MAPBOX_TOKEN set)  — best satellite quality
  2. Google Maps Static (via google_maps_tool) — good quality, 5 APIs available
  3. OpenStreetMap tiles                       — always available, no key needed

Fix applied: removed duplicate _fetch_google_static() call.
All Google Maps calls now route through mcp/google_maps_tool.py exclusively.
"""

import io
import math
import base64
import json
import requests
from typing import Optional
from PIL import Image, ImageDraw

from config import get_settings
from utils.logger import get_logger

settings = get_settings()
log = get_logger("geo_tool")


# ── Coordinate helpers ─────────────────────────────────────────────────────────

def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_lat_lon(x: int, y: int, zoom: int) -> tuple[float, float]:
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_r = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return math.degrees(lat_r), lon


def parse_sector_coords(sector: str) -> tuple[float, float]:
    try:
        coords_map = json.loads(settings.sector_coords)
        raw = coords_map.get(sector, "34.10,74.80")
        lat, lon = raw.split(",")
        return float(lat), float(lon)
    except Exception:
        return 34.10, 74.80


# ── Image fetchers ─────────────────────────────────────────────────────────────

def fetch_sector_image(sector: str, zoom: int = 14,
                       width_px: int = 640, height_px: int = 640) -> dict:
    """
    Main entry — fetch imagery for a sector via best available source.
    Returns: {base64, source, lat, lon, zoom, bbox}
    """
    lat, lon = parse_sector_coords(sector)

    # Tier 1 — Mapbox (best satellite quality)
    if settings.mapbox_token:
        result = _fetch_mapbox(lat, lon, zoom, width_px, height_px)
        if result:
            result.update({"lat": lat, "lon": lon, "zoom": zoom})
            result["bbox"] = _compute_bbox(lat, lon, zoom, width_px, height_px)
            log.info("Image fetched via Mapbox", sector=sector, zoom=zoom)
            return result

    # Tier 2 — Google Maps Static (via google_maps_tool — no duplicate call)
    if settings.google_maps_api_key:
        from mcp_tools.google_maps_tool import fetch_satellite_image as gmaps_fetch
        result = gmaps_fetch(lat=lat, lon=lon, zoom=zoom,
                             width=width_px, height=height_px, map_type="satellite")
        if result and result.get("source", "").startswith("google") and "error" not in result:
            result.update({"lat": lat, "lon": lon, "zoom": zoom})
            result["bbox"] = _compute_bbox(lat, lon, zoom, width_px, height_px)
            # Normalise key — google_maps_tool uses image_b64, geo_tool uses base64
            if "image_b64" in result and "base64" not in result:
                result["base64"] = result["image_b64"]
            log.info("Image fetched via Google Maps", sector=sector, zoom=zoom)
            return result

    # Tier 3 — OpenStreetMap tiles (always available)
    result = _fetch_osm_tiles(lat, lon, zoom, width_px, height_px)
    result.update({"lat": lat, "lon": lon, "zoom": zoom})
    result["bbox"] = _compute_bbox(lat, lon, zoom, width_px, height_px)
    log.info("Image fetched via OSM tiles", sector=sector, zoom=zoom)
    return result


def _fetch_mapbox(lat, lon, zoom, width_px, height_px) -> Optional[dict]:
    try:
        url = (
            f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
            f"{lon},{lat},{zoom}/{width_px}x{height_px}"
            f"?access_token={settings.mapbox_token}"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        b64 = base64.standard_b64encode(resp.content).decode()
        return {"base64": b64, "source": "mapbox_satellite"}
    except Exception as e:
        log.warning("Mapbox fetch failed", error=str(e))
        return None


def _fetch_osm_tiles(lat, lon, zoom, width_px, height_px) -> dict:
    try:
        tiles_x = math.ceil(width_px / 256) + 1
        tiles_y = math.ceil(height_px / 256) + 1
        cx, cy  = lat_lon_to_tile(lat, lon, zoom)
        start_x = cx - tiles_x // 2
        start_y = cy - tiles_y // 2
        canvas  = Image.new("RGB", (tiles_x * 256, tiles_y * 256), (200, 200, 200))
        headers = {"User-Agent": "SENTINEL-SurveillanceSystem/1.0"}

        for dx in range(tiles_x):
            for dy in range(tiles_y):
                tx, ty = start_x + dx, start_y + dy
                url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
                try:
                    r = requests.get(url, headers=headers, timeout=8)
                    if r.status_code == 200:
                        tile_img = Image.open(io.BytesIO(r.content)).convert("RGB")
                        canvas.paste(tile_img, (dx * 256, dy * 256))
                except Exception:
                    pass

        left  = (canvas.width  - width_px)  // 2
        top   = (canvas.height - height_px) // 2
        canvas = canvas.crop((left, top, left + width_px, top + height_px))
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return {"base64": base64.standard_b64encode(buf.getvalue()).decode(),
                "source": "osm_tiles"}
    except Exception as e:
        log.error("OSM tile fetch failed", error=str(e))
        return {"base64": _placeholder_b64(), "source": "placeholder"}


# ── Overlay helpers ────────────────────────────────────────────────────────────

def overlay_waypoints(base64_image: str, waypoints: list,
                      image_lat: float, image_lon: float,
                      zoom: int, width_px: int = 640, height_px: int = 640) -> str:
    try:
        img = Image.open(io.BytesIO(base64.standard_b64decode(base64_image))).convert("RGBA")
        draw = ImageDraw.Draw(img)
        cx, cy = lat_lon_to_tile(image_lat, image_lon, zoom)
        nw_lat, nw_lon = tile_to_lat_lon(cx - width_px // 512, cy - height_px // 512, zoom)
        se_lat, se_lon = tile_to_lat_lon(cx + width_px // 512 + 1, cy + height_px // 512 + 1, zoom)
        lat_range = (nw_lat - se_lat) or 1
        lon_range = (se_lon - nw_lon) or 1

        for wp in waypoints:
            px = int((wp["lon"] - nw_lon) / lon_range * width_px)
            py = int((nw_lat - wp["lat"]) / lat_range * height_px)
            r  = 8
            draw.ellipse([(px-r, py-r), (px+r, py+r)],
                         fill=wp.get("color", "red"), outline="white", width=2)
            if wp.get("label"):
                draw.text((px + r + 3, py - 6), wp["label"], fill="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.standard_b64encode(buf.getvalue()).decode()
    except Exception as e:
        log.warning("Overlay failed", error=str(e))
        return base64_image


# ── Utilities ──────────────────────────────────────────────────────────────────

def _compute_bbox(lat, lon, zoom, width_px, height_px) -> dict:
    cx, cy = lat_lon_to_tile(lat, lon, zoom)
    t = math.ceil(width_px / 256) // 2 + 1
    nw_lat, nw_lon = tile_to_lat_lon(cx - t, cy - t, zoom)
    se_lat, se_lon = tile_to_lat_lon(cx + t, cy + t, zoom)
    return {"north": nw_lat, "south": se_lat, "east": se_lon, "west": nw_lon}


def _placeholder_b64() -> str:
    img = Image.new("RGB", (640, 640), (80, 80, 80))
    draw = ImageDraw.Draw(img)
    draw.text((20, 310), "Map unavailable — all sources failed", fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()
