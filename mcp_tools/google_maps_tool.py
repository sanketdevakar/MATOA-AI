"""
Google Maps Platform MCP Tool — SENTINEL
------------------------------------------
Wraps five Google Maps Platform APIs as proper MCP-callable functions:

  1. Static Maps API      — satellite/hybrid imagery for vision scanning
  2. Geocoding API        — sector name ↔ lat/lon conversion
  3. Places API (Nearby)  — identify terrain features near a sector
  4. Directions API       — optimal patrol routes between waypoints
  5. Street View API      — ground-level imagery for threat verification

Each function is also registered as an ADK FunctionTool in adk/tools.py
so Vision Agent and Patrol Agent can call them autonomously during pipeline.

All calls include graceful fallback — if the API key is missing or the
call fails, a structured mock response is returned so the pipeline never
blocks on Maps availability.

Setup:
  1. Enable these APIs in Google Cloud Console:
       - Maps Static API
       - Geocoding API
       - Places API (New)
       - Directions API
       - Street View Static API
  2. Create an API key with these APIs enabled
  3. Add to .env:  GOOGLE_MAPS_API_KEY=AIza...

Rate limits (free tier):
  - Static Maps:  $2/1000 requests → 28,000 free/month
  - Geocoding:    $5/1000 → 40,000 free/month
  - Places:       $17/1000 → varies by type
  - Directions:   $5/1000 → 40,000 free/month
  - Street View:  $7/1000 → 28,000 free/month
"""

import base64
import json
import requests
from typing import Optional

from config import get_settings

settings = get_settings()
GMAPS_KEY = settings.google_maps_api_key
BASE      = "https://maps.googleapis.com"


# ── 1. Static Maps / Satellite Imagery ─────────────────────────────────────────

def fetch_satellite_image(
    lat: float,
    lon: float,
    zoom: int = 15,
    width: int = 640,
    height: int = 640,
    map_type: str = "satellite",   # satellite | hybrid | terrain | roadmap
) -> dict:
    """
    Fetch a satellite or hybrid map image from Google Maps Static API.
    Returns base64-encoded PNG + metadata.

    map_type options:
      - 'satellite' : raw satellite imagery (best for anomaly detection)
      - 'hybrid'    : satellite + road/label overlay (best for navigation)
      - 'terrain'   : topographic detail (best for route planning)
      - 'roadmap'   : standard map (fallback)
    """
    if not GMAPS_KEY:
        return _mock_image_response(lat, lon, zoom, "no_api_key")

    url = (
        f"{BASE}/maps/api/staticmap"
        f"?center={lat},{lon}"
        f"&zoom={zoom}"
        f"&size={width}x{height}"
        f"&maptype={map_type}"
        f"&key={GMAPS_KEY}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        b64 = base64.standard_b64encode(resp.content).decode()
        return {
            "source":    f"google_{map_type}",
            "image_b64": b64,
            "lat":       lat,
            "lon":       lon,
            "zoom":      zoom,
            "map_type":  map_type,
            "width":     width,
            "height":    height,
            "url_used":  url.replace(GMAPS_KEY, "REDACTED"),
        }
    except Exception as e:
        print(f"[GoogleMapsTool] Static Maps failed: {e}")
        return _mock_image_response(lat, lon, zoom, str(e))


def fetch_satellite_with_markers(
    lat: float,
    lon: float,
    markers: list,    # [{"lat": f, "lon": f, "label": str, "color": str}]
    zoom: int = 15,
    map_type: str = "hybrid",
) -> dict:
    """
    Fetch satellite imagery with threat marker pins overlaid via Google Maps.
    More accurate than Pillow overlay since Google renders markers natively.
    """
    if not GMAPS_KEY:
        return _mock_image_response(lat, lon, zoom, "no_api_key")

    # Build marker params
    marker_params = ""
    color_map = {
        "red": "red", "orange": "orange", "yellow": "yellow",
        "green": "green", "blue": "blue", "white": "white",
    }
    for m in markers:
        color = color_map.get(m.get("color", "red"), "red")
        label = m.get("label", "T")[:1].upper()
        marker_params += f"&markers=color:{color}|label:{label}|{m['lat']},{m['lon']}"

    url = (
        f"{BASE}/maps/api/staticmap"
        f"?center={lat},{lon}&zoom={zoom}"
        f"&size=640x640&maptype={map_type}"
        f"{marker_params}&key={GMAPS_KEY}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        b64 = base64.standard_b64encode(resp.content).decode()
        return {
            "source":    f"google_{map_type}_marked",
            "image_b64": b64,
            "lat": lat, "lon": lon, "zoom": zoom,
            "markers_drawn": len(markers),
        }
    except Exception as e:
        print(f"[GoogleMapsTool] Marked fetch failed: {e}")
        return _mock_image_response(lat, lon, zoom, str(e))


# ── 2. Geocoding API ──────────────────────────────────────────────────────────

def geocode_location(address: str) -> dict:
    """
    Convert a place name or address to lat/lon coordinates.
    Useful for converting sector descriptions to precise coordinates.

    Example: geocode_location("Line of Control, Kupwara, Jammu & Kashmir")
    """
    if not GMAPS_KEY:
        return {"error": "No API key", "lat": 34.10, "lon": 74.80, "formatted_address": address}

    url = f"{BASE}/maps/api/geocode/json"
    try:
        resp = requests.get(url, params={"address": address, "key": GMAPS_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK" or not data.get("results"):
            return {"error": data.get("status", "no_results"), "query": address}

        result   = data["results"][0]
        location = result["geometry"]["location"]
        return {
            "lat":               location["lat"],
            "lon":               location["lng"],
            "formatted_address": result.get("formatted_address", ""),
            "place_id":          result.get("place_id", ""),
            "location_type":     result["geometry"].get("location_type", ""),
            "bounds":            result["geometry"].get("bounds", {}),
        }
    except Exception as e:
        return {"error": str(e), "query": address}


def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Convert lat/lon to a human-readable address.
    Useful for reporting precise incident locations to commanders.
    """
    if not GMAPS_KEY:
        return {"error": "No API key", "lat": lat, "lon": lon}

    url = f"{BASE}/maps/api/geocode/json"
    try:
        resp = requests.get(url, params={"latlng": f"{lat},{lon}", "key": GMAPS_KEY}, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK" or not data.get("results"):
            return {"error": data.get("status"), "lat": lat, "lon": lon}

        result = data["results"][0]
        return {
            "formatted_address": result.get("formatted_address", ""),
            "place_id":          result.get("place_id", ""),
            "address_components": result.get("address_components", []),
            "lat": lat,
            "lon": lon,
        }
    except Exception as e:
        return {"error": str(e), "lat": lat, "lon": lon}


# ── 3. Places API (Nearby Search) ────────────────────────────────────────────

def find_nearby_features(
    lat: float,
    lon: float,
    radius_meters: int = 2000,
    place_types: list = None,   # e.g. ["checkpoint", "bridge", "road"]
) -> dict:
    """
    Find terrain features, infrastructure, and points of interest
    near a sector centre using Google Places Nearby Search API.

    Useful for:
      - Identifying bridges, roads, and chokepoints for patrol planning
      - Finding civilian settlements (affects rules of engagement)
      - Locating water sources and terrain features
      - Building sector context for Intel Agent threat assessment

    Common place_types for military use:
      natural_feature, park, route, point_of_interest,
      lodging (possible staging areas), storage (possible cache sites)
    """
    if not GMAPS_KEY:
        return {"error": "No API key", "features": [], "lat": lat, "lon": lon}

    if not place_types:
        place_types = ["natural_feature", "point_of_interest", "route"]

    url = f"{BASE}/maps/api/place/nearbysearch/json"
    all_features = []

    for ptype in place_types[:3]:   # Limit to 3 types to avoid quota burn
        try:
            params = {
                "location": f"{lat},{lon}",
                "radius":   radius_meters,
                "type":     ptype,
                "key":      GMAPS_KEY,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            for place in data.get("results", [])[:5]:   # Top 5 per type
                loc = place.get("geometry", {}).get("location", {})
                all_features.append({
                    "name":      place.get("name", ""),
                    "type":      ptype,
                    "lat":       loc.get("lat"),
                    "lon":       loc.get("lng"),
                    "place_id":  place.get("place_id", ""),
                    "vicinity":  place.get("vicinity", ""),
                    "rating":    place.get("rating"),
                })
        except Exception as e:
            print(f"[GoogleMapsTool] Places search failed for {ptype}: {e}")

    return {
        "lat":          lat,
        "lon":          lon,
        "radius_m":     radius_meters,
        "feature_count": len(all_features),
        "features":     all_features,
    }


# ── 4. Directions API — Patrol Route Planning ─────────────────────────────────

def get_patrol_route(
    origin_lat: float,
    origin_lon: float,
    waypoints: list,         # [{"lat": f, "lon": f}, ...]
    destination_lat: float,
    destination_lon: float,
    travel_mode: str = "walking",   # walking | driving | bicycling
) -> dict:
    """
    Calculate the optimal patrol route between a sequence of waypoints
    using Google Maps Directions API.

    Returns:
      - Total distance and duration
      - Turn-by-turn instructions for each patrol leg
      - Encoded polyline for map overlay
      - Individual leg distances and durations

    Used by Patrol Agent when threat_score >= 7 to plan an optimised
    patrol route through high-risk waypoints rather than a generic grid.

    travel_mode:
      'walking'   — foot patrol (most common for border surveillance)
      'driving'   — vehicle patrol on roads
      'bicycling' — bicycle patrol for intermediate terrain
    """
    if not GMAPS_KEY:
        return _mock_route_response(origin_lat, origin_lon, destination_lat, destination_lon)

    url = f"{BASE}/maps/api/directions/json"

    # Format waypoints for API
    wp_str = "|".join(f"{w['lat']},{w['lon']}" for w in waypoints) if waypoints else ""

    params = {
        "origin":      f"{origin_lat},{origin_lon}",
        "destination": f"{destination_lat},{destination_lon}",
        "mode":        travel_mode,
        "key":         GMAPS_KEY,
    }
    if wp_str:
        params["waypoints"] = f"optimize:true|{wp_str}"

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK" or not data.get("routes"):
            return {"error": data.get("status", "no_route"), "params": params}

        route = data["routes"][0]
        legs  = route.get("legs", [])

        # Extract structured leg data
        leg_summaries = []
        total_distance_m  = 0
        total_duration_s  = 0

        for i, leg in enumerate(legs):
            dist = leg.get("distance", {})
            dur  = leg.get("duration", {})
            total_distance_m += dist.get("value", 0)
            total_duration_s += dur.get("value", 0)

            # Extract turn-by-turn steps
            steps = []
            for step in leg.get("steps", [])[:5]:   # First 5 steps per leg
                steps.append({
                    "instruction": _strip_html(step.get("html_instructions", "")),
                    "distance":    step.get("distance", {}).get("text", ""),
                    "duration":    step.get("duration", {}).get("text", ""),
                })

            leg_summaries.append({
                "leg":            i + 1,
                "start_address":  leg.get("start_address", ""),
                "end_address":    leg.get("end_address", ""),
                "distance":       dist.get("text", ""),
                "duration":       dur.get("text", ""),
                "steps":          steps,
            })

        return {
            "status":              "OK",
            "travel_mode":         travel_mode,
            "total_distance_km":   round(total_distance_m / 1000, 2),
            "total_duration_min":  round(total_duration_s / 60, 1),
            "total_duration_text": _format_duration(total_duration_s),
            "waypoint_count":      len(waypoints),
            "legs":                leg_summaries,
            "overview_polyline":   route.get("overview_polyline", {}).get("points", ""),
            "summary":             route.get("summary", ""),
            "warnings":            route.get("warnings", []),
        }
    except Exception as e:
        print(f"[GoogleMapsTool] Directions failed: {e}")
        return _mock_route_response(origin_lat, origin_lon, destination_lat, destination_lon)


# ── 5. Street View Static API ─────────────────────────────────────────────────

def fetch_street_view(
    lat: float,
    lon: float,
    heading: int = 0,       # compass direction 0-360 (0=North, 90=East)
    pitch: int = 0,         # vertical angle -90 to 90
    fov: int = 90,          # field of view 10-120 degrees
    width: int = 640,
    height: int = 400,
) -> dict:
    """
    Fetch ground-level Street View imagery for a location.
    Used by Vision Agent for ground-truth verification when satellite
    imagery shows a potential anomaly — confirms what's actually there
    at road/ground level.

    heading: compass direction the camera faces
      0   = North (toward border)
      90  = East
      180 = South
      270 = West

    Returns base64-encoded JPEG + metadata, or error if no Street View
    coverage exists at the location (common in remote border areas).
    """
    if not GMAPS_KEY:
        return {"error": "No API key", "has_coverage": False}

    # First check if coverage exists (avoids wasting quota on empty images)
    meta_url = (
        f"{BASE}/maps/api/streetview/metadata"
        f"?location={lat},{lon}&key={GMAPS_KEY}"
    )
    try:
        meta = requests.get(meta_url, timeout=8).json()
        if meta.get("status") != "OK":
            return {
                "has_coverage": False,
                "status":       meta.get("status", "no_coverage"),
                "lat": lat, "lon": lon,
                "note": "No Street View coverage at this location — common in remote border areas.",
            }
    except Exception:
        pass   # Proceed to image fetch anyway

    # Fetch the actual image
    img_url = (
        f"{BASE}/maps/api/streetview"
        f"?size={width}x{height}"
        f"&location={lat},{lon}"
        f"&heading={heading}&pitch={pitch}&fov={fov}"
        f"&key={GMAPS_KEY}"
    )
    try:
        resp = requests.get(img_url, timeout=15)
        resp.raise_for_status()
        b64 = base64.standard_b64encode(resp.content).decode()
        return {
            "has_coverage": True,
            "image_b64":    b64,
            "lat":     lat,   "lon":     lon,
            "heading": heading, "pitch": pitch, "fov": fov,
            "source":  "google_street_view",
            "note":    f"Ground-level view facing {_compass(heading)}",
        }
    except Exception as e:
        return {"has_coverage": False, "error": str(e), "lat": lat, "lon": lon}


# ── Utilities ──────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags from Directions API instructions."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h:
        return f"{h}h {m}min"
    return f"{m} min"


def _compass(heading: int) -> str:
    dirs = ["North", "NE", "East", "SE", "South", "SW", "West", "NW"]
    return dirs[round(heading / 45) % 8]


def _mock_image_response(lat, lon, zoom, reason) -> dict:
    """Return a labeled placeholder image when API is unavailable."""
    from PIL import Image, ImageDraw
    import io
    img = Image.new("RGB", (640, 640), (60, 60, 60))
    draw = ImageDraw.Draw(img)
    draw.text((20, 300), f"Google Maps unavailable", fill="white")
    draw.text((20, 320), f"Reason: {reason[:50]}", fill="lightgray")
    draw.text((20, 340), f"Lat: {lat:.4f}  Lon: {lon:.4f}", fill="lightgray")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {
        "source":    "placeholder",
        "image_b64": base64.standard_b64encode(buf.getvalue()).decode(),
        "lat": lat, "lon": lon, "zoom": zoom,
        "error":     reason,
    }


def _mock_route_response(o_lat, o_lon, d_lat, d_lon) -> dict:
    """Return a mock route when Directions API is unavailable."""
    import math
    dist = math.sqrt((d_lat - o_lat)**2 + (d_lon - o_lon)**2) * 111
    return {
        "status":              "MOCK",
        "travel_mode":         "walking",
        "total_distance_km":   round(dist, 2),
        "total_duration_min":  round(dist / 0.05),
        "total_duration_text": f"{round(dist / 0.05)} min (estimated)",
        "waypoint_count":      0,
        "legs":                [],
        "overview_polyline":   "",
        "note":                "Mock route — Google Maps API key not configured.",
    }
