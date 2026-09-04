import json
from datetime import datetime, timedelta
from pathlib import Path
import requests
from ..config import BOUNDARY_URL, USER_AGENT, DATA_DIR

CACHE = DATA_DIR / "electorates.geojson"


def fetch_boundaries(timeout: int = 45, max_age_days: int = 7):
    if CACHE.exists():
        age = datetime.now() - datetime.fromtimestamp(CACHE.stat().st_mtime)
        if age < timedelta(days=max_age_days):
            return json.loads(CACHE.read_text(encoding="utf-8"))
    params = {
        "where": "1=1",
        "outFields": "adminareaname,id",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "geojson",
    }
    try:
        r = requests.get(BOUNDARY_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("type") != "FeatureCollection":
            raise RuntimeError("Boundary service did not return GeoJSON FeatureCollection")
        CACHE.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception:
        if CACHE.exists():
            return json.loads(CACHE.read_text(encoding="utf-8"))
        raise
