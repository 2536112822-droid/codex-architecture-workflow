#!/usr/bin/env python3
"""Generate georeferenced architectural site-analysis diagrams from open data.

This script is intentionally self-contained and can bootstrap its Python
environment. It fetches OSM, elevation, and climate data for a point/radius,
computes standard site analyses, and renders a consistent set of diagrams.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import time
import textwrap
import uuid
import warnings
from pathlib import Path


def _ensure_dependencies() -> None:
    """Create a local .venv once and re-run without recursive self-launching."""
    required = {
        "numpy": "numpy",
        "pandas": "pandas",
        "geopandas": "geopandas",
        "shapely": "shapely",
        "pyproj": "pyproj",
        "requests": "requests",
        "matplotlib": "matplotlib",
        "PIL": "Pillow",
        "osmnx": "osmnx",
        "scipy": "scipy",
    }
    missing = [pkg for mod, pkg in required.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return

    if os.environ.get("SITE_ANALYSIS_BOOTSTRAPPED") == "1":
        raise RuntimeError(
            "Dependencies are still missing after one bootstrap attempt: "
            + ", ".join(missing)
        )

    if os.environ.get("SITE_ANALYSIS_SKIP_BOOTSTRAP") == "1":
        raise RuntimeError(
            "Missing site-analysis dependencies while bootstrap is disabled: "
            + ", ".join(missing)
        )

    venv_dir = Path.cwd() / ".venv"
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    if not venv_dir.exists():
        print(f"[site-analysis] Missing packages {', '.join(missing)}. Creating {venv_dir} ...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    if not python.exists():
        raise RuntimeError(f"Virtual environment is incomplete: {python} does not exist")

    req_file = Path(__file__).with_name("requirements.txt")
    print(f"[site-analysis] Installing dependencies from {req_file} ...")
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(req_file)], check=True)

    print("[site-analysis] Re-running with the project virtual environment ...")
    env = os.environ.copy()
    env["SITE_ANALYSIS_BOOTSTRAPPED"] = "1"
    completed = subprocess.run(
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        check=False,
        env=env,
    )
    sys.exit(completed.returncode)


_ensure_dependencies()

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import geopandas as gpd
import requests
import osmnx as ox
from matplotlib import colors as mcolors
from pyproj import CRS, Transformer
from scipy.interpolate import griddata
from shapely.geometry import Point

warnings.filterwarnings("ignore", category=FutureWarning)

WGS84 = CRS.from_epsg(4326)

OVERpass_ENDPOINTS = [
    "https://overpass-api.de/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
    "https://overpass.openstreetmap.ru/api",
    "https://overpass.openstreetmap.fr/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]

try:
    ox.settings.requests_timeout = 30
    ox.settings.overpass_rate_limit = True
    ox.settings.use_cache = True
except Exception:
    pass

matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "SimHei",
    "Arial Unicode MS",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

OSM_QUERY_LOG: list[dict] = []

# OSMnx mutates socket.getaddrinfo to pin a single server IP; that DNS pinning
# is flaky in some environments. Use the standard resolver instead.
try:
    import osmnx._http as _osm_http
    _osm_http._config_dns = lambda url: None
except Exception:
    pass


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def utm_crs_for(lon: float, lat: float) -> CRS:
    zone = int((lon + 180.0) // 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def make_transformer(src_crs: CRS, dst_crs: CRS) -> Transformer:
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_run_dir(output_root: Path, run_id: str | None = None) -> tuple[str, Path]:
    """Create a unique run directory so stale artifacts can never enter a new manifest."""
    output_root = output_root.resolve()
    if run_id is None:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    if not run_id or any(part in run_id for part in ("/", "\\", "..")):
        raise ValueError("run_id must be a simple directory name")
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


def build_output_manifest(paths: list[Path], base_dir: Path) -> list[dict]:
    """Return an explicit, hash-addressed manifest for files created by this run only."""
    seen: set[Path] = set()
    entries = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.is_file():
            raise FileNotFoundError(f"Manifest output is not a file: {resolved}")
        entries.append(
            {
                "path": resolved.relative_to(base_dir.resolve()).as_posix(),
                "bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )
    return entries


def _query_osm(fn, label: str):
    """Try an OSMnx call against several public Overpass endpoints."""
    last_exc: Exception | None = None
    for endpoint in OVERpass_ENDPOINTS:
        try:
            ox.settings.overpass_url = endpoint
            result = fn()
            accessed_at = utc_now_iso()
            OSM_QUERY_LOG.append(
                {"layer": label, "endpoint": endpoint, "status": "returned",
                 "accessed_at_utc": accessed_at, "retrieved_at_utc": accessed_at,
                 "source_observed_at_utc": None, "cache_status": "unknown"}
            )
            return result
        except Exception as exc:
            last_exc = exc
            OSM_QUERY_LOG.append(
                {"layer": label, "endpoint": endpoint, "status": "error",
                 "accessed_at_utc": utc_now_iso(), "error": str(exc)[:240],
                 "source_observed_at_utc": None, "cache_status": "unknown"}
            )
            print(f"[site-analysis] Overpass endpoint {endpoint} failed: {exc}")
    if last_exc:
        raise last_exc
    raise RuntimeError("No Overpass endpoint was available.")


# ---------------------------------------------------------------------------
# OSM data
# ---------------------------------------------------------------------------


def _first(value):
    if isinstance(value, (list, tuple, set)):
        return value[0] if len(value) else None
    return value


def normalize_tag(value) -> str:
    """Normalize OSM scalar/list tags without turning missing values into the string 'nan'."""
    value = _first(value)
    if value is None:
        return ""
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _scalarize(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep geometry plus a few scalar tag columns so GeoJSON export is safe."""
    cols = ["building", "highway", "landuse", "leisure", "natural", "waterway", "water",
            "amenity", "railway", "public_transport", "name"]
    out = gdf.copy()
    for col in cols:
        if col in out.columns:
            out[col] = out[col].map(_first)
    keep = [c for c in cols if c in out.columns]
    if keep:
        out = out[["geometry"] + keep]
    else:
        out = out[["geometry"]]
    return out


def fetch_osm(center_lat: float, center_lon: float, radius: float, cache_dir: Path) -> dict:
    """Download building, landuse, transit, and road data around a point."""
    OSM_QUERY_LOG.clear()
    ox.settings.cache_folder = str(cache_dir / "osmnx-cache")
    ox.settings.use_cache = True
    center = (center_lat, center_lon)

    def empty_layer(columns: list[str] | None = None) -> gpd.GeoDataFrame:
        data = {column: pd.Series(dtype="object") for column in (columns or [])}
        return gpd.GeoDataFrame(data, geometry=gpd.GeoSeries([], crs=WGS84), crs=WGS84)

    def feature_layer(label: str, tags: dict, columns: list[str]) -> gpd.GeoDataFrame:
        try:
            result = _scalarize(
                _query_osm(
                    lambda: ox.features_from_point(center, tags=tags, dist=radius),
                    label,
                )
            )
            result.attrs["source_status"] = {"status": "available" if len(result) else "empty"}
            return result
        except Exception as exc:
            # OSMnx can collapse an empty response with a timeout remark into
            # this same message. Do not claim successful/complete empty data.
            no_match = (isinstance(exc, ox._errors.InsufficientResponseError)
                        and str(exc) == "No matching features. Check query location, tags, and log.")
            status = "no_matches" if no_match else "unavailable"
            print(f"[site-analysis] OSM layer '{label}' {status}: {exc}")
            result = empty_layer(columns)
            result.attrs["source_status"] = {"status": status, "reason": str(exc)[:240]}
            return result

    buildings = feature_layer("buildings", {"building": True}, ["building"])
    landuse = feature_layer(
        "landuse",
        {
            "landuse": [
                "residential", "commercial", "retail", "industrial", "grass", "forest",
                "meadow", "recreation_ground", "village_green", "allotments", "farmland",
                "farmyard", "reservoir", "basin", "construction", "brownfield", "cemetery",
            ],
            "leisure": ["park", "garden", "pitch", "playground", "golf_course", "recreation_ground"],
            "natural": ["water", "wood", "scrub", "grassland", "beach", "sand", "heath", "moor"],
            "waterway": True,
        },
        ["landuse", "leisure", "natural", "waterway", "water"],
    )
    transit = feature_layer(
        "transit_poi",
        {
            "amenity": [
                "bus_stop", "school", "university", "college", "hospital", "kindergarten",
                "library", "community_centre", "townhall", "police",
            ],
            "railway": ["station", "halt", "tram_stop"],
            "highway": ["bus_stop"],
            "public_transport": ["stop_position", "platform"],
        },
        ["amenity", "railway", "highway", "public_transport", "name"],
    )

    try:
        graph = _query_osm(
            lambda: ox.graph_from_point(
                center,
                dist=radius,
                network_type="all",
                simplify=True,
                retain_all=True,
                truncate_by_edge=True,
            ),
            "roads",
        )
        edges = _scalarize(ox.graph_to_gdfs(graph, nodes=False, edges=True).reset_index(drop=True))
        edges.attrs["source_status"] = {"status": "available" if len(edges) else "empty"}
    except Exception as exc:
        print(f"[site-analysis] OSM layer 'roads' unavailable: {exc}")
        edges = empty_layer(["highway", "name"])
        edges.attrs["source_status"] = {"status": "unavailable", "reason": str(exc)[:240]}

    result = {
        "buildings": buildings,
        "landuse": landuse,
        "transit": transit,
        "roads": edges,
    }
    return result


def classify_road(value) -> str:
    value = normalize_tag(value).lower()
    if value in {"motorway", "motorway_link", "trunk", "trunk_link"}:
        return "primary"
    if value in {"primary", "primary_link", "secondary", "secondary_link"}:
        return "major"
    if value in {"tertiary", "tertiary_link", "unclassified"}:
        return "minor"
    if value in {"residential", "living_street"}:
        return "local"
    if value in {"service", "track", "road"}:
        return "service"
    if value in {"footway", "path", "steps", "pedestrian", "cycleway", "bridleway"}:
        return "pedestrian"
    return "other"


ROAD_STYLE = {
    "primary": {"color": "#222222", "linewidth": 2.6},
    "major": {"color": "#3a3a3a", "linewidth": 2.0},
    "minor": {"color": "#5a5a5a", "linewidth": 1.5},
    "local": {"color": "#8c8c8c", "linewidth": 1.0},
    "service": {"color": "#b0b0b0", "linewidth": 0.7},
    "pedestrian": {"color": "#d0c5a8", "linewidth": 0.9, "linestyle": "--"},
    "other": {"color": "#9a9a9a", "linewidth": 0.8},
}


def classify_landuse(row) -> str:
    landuse = normalize_tag(row.get("landuse")).lower()
    leisure = normalize_tag(row.get("leisure")).lower()
    natural = normalize_tag(row.get("natural")).lower()
    waterway = normalize_tag(row.get("waterway")).lower()
    water = normalize_tag(row.get("water")).lower()

    if (
        natural == "water"
        or waterway
        or water
        or landuse in {"reservoir", "basin", "harbour"}
    ):
        return "water"
    if natural in {"wood", "scrub", "grassland", "heath", "moor", "wetland"} or leisure in {
        "park",
        "garden",
        "pitch",
        "playground",
        "golf_course",
        "recreation_ground",
    } or landuse in {"grass", "forest", "meadow", "village_green", "allotments", "orchard"}:
        return "green"
    if landuse in {
        "residential",
        "commercial",
        "retail",
        "industrial",
        "construction",
        "brownfield",
        "garages",
    }:
        return "built"
    if landuse in {"farmland", "farmyard", "vineyard"}:
        return "farm"
    return "other"


LANDUSE_STYLE = {
    "water": {"facecolor": "#b8d6e8", "edgecolor": "#7fa7bd", "linewidth": 0.5},
    "green": {"facecolor": "#cde3b2", "edgecolor": "#9ebf78", "linewidth": 0.4},
    "built": {"facecolor": "#e0d8cc", "edgecolor": "#b6aa9a", "linewidth": 0.3},
    "farm": {"facecolor": "#e8e2b7", "edgecolor": "#c7bd8d", "linewidth": 0.3},
    "other": {"facecolor": "#f1efe9", "edgecolor": "#c9c4b8", "linewidth": 0.3},
}


def classify_transit(row) -> str:
    railway = normalize_tag(row.get("railway")).lower()
    highway = normalize_tag(row.get("highway")).lower()
    pt = normalize_tag(row.get("public_transport")).lower()
    if railway in {"station", "halt"} or pt == "station":
        return "station"
    if railway == "tram_stop" or pt in {"stop_position", "platform"} or highway == "bus_stop":
        return "stop"
    return "poi"


def pointify_markers(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Convert polygon/line POIs to representative points before marker rendering."""
    if gdf.empty:
        out = gdf.copy()
        out["source_geometry_type"] = pd.Series(dtype="object")
        return out
    out = gdf.copy()
    out["source_geometry_type"] = out.geometry.geom_type
    out.geometry = out.geometry.map(
        lambda geom: geom if geom is not None and geom.geom_type == "Point" else geom.representative_point()
    )
    return out


TRANSIT_STYLE = {
    "station": {"marker": "s", "color": "#c43d3d", "size": 55, "label": "Rail station"},
    "stop": {"marker": "o", "color": "#1f6f8b", "size": 22, "label": "Transit stop"},
    "poi": {"marker": "o", "color": "#7b6c8c", "size": 16, "label": "POI"},
}


# ---------------------------------------------------------------------------
# Elevation
# ---------------------------------------------------------------------------


def _bounds_for_radius(lon: float, lat: float, radius: float, utm: CRS) -> tuple[float, float, float, float]:
    to_utm = make_transformer(WGS84, utm)
    to_wgs = make_transformer(utm, WGS84)
    x, y = to_utm.transform(lon, lat)
    corners_utm = [(x - radius, y - radius), (x + radius, y - radius),
                   (x + radius, y + radius), (x - radius, y + radius)]
    lons, lats = [], []
    for cx, cy in corners_utm:
        lo, la = to_wgs.transform(cx, cy)
        lons.append(lo)
        lats.append(la)
    return min(lats), max(lats), min(lons), max(lons)


def fetch_elevation_grid(center_lat: float, center_lon: float, radius: float,
                         utm: CRS, res: float = 30.0,
                         cache_dir: Path | None = None) -> dict:
    south, north, west, east = _bounds_for_radius(center_lon, center_lat, radius, utm)
    # Keep a margin so the DEM grid covers the full site circle.
    margin = res / 111_000.0
    south -= margin
    north += margin
    west -= margin / max(0.1, math.cos(math.radians(center_lat)))
    east += margin / max(0.1, math.cos(math.radians(center_lat)))

    # Create a regular WGS84 grid at roughly the requested ground resolution.
    dlat = res / 111_320.0
    dlon = res / (111_320.0 * max(0.1, math.cos(math.radians(center_lat))))
    lats = np.arange(south, north + dlat, dlat)
    lons = np.arange(west, east + dlon, dlon)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    elev2d = np.full(lat_grid.shape, np.nan, dtype=float)
    tile_records: list[dict] = []
    tile_cache = (cache_dir or Path.cwd() / ".site-analysis-cache") / "elevation"
    tile_cache.mkdir(parents=True, exist_ok=True)

    # Download the relevant SRTM 1-arc-second (30 m) HGT tiles from AWS.
    cellsize = 1.0 / 3600.0
    lat_sws = np.arange(math.floor(south), math.floor(north) + 1)
    lon_sws = np.arange(math.floor(west), math.floor(east) + 1)
    for lat_sw in lat_sws:
        for lon_sw in lon_sws:
            tile_dir, tile_name, _, _ = _tile_parts(float(lat_sw), float(lon_sw))
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/{tile_dir}/{tile_name}"
            cache_path = tile_cache / tile_name
            try:
                if cache_path.exists():
                    content = cache_path.read_bytes()
                    cache_status = "hit"
                else:
                    resp = requests.get(url, timeout=60)
                    resp.raise_for_status()
                    content = resp.content
                    cache_path.write_bytes(content)
                    cache_status = "downloaded"
                arr = _read_hgt(content)
                tile_records.append(
                    {
                        "tile": tile_name,
                        "url": url,
                        "cache_status": cache_status,
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            except Exception as exc:
                print(f"[site-analysis] Could not download SRTM tile {tile_name}: {exc}")
                tile_records.append({"tile": tile_name, "url": url, "error": str(exc)})
                continue

            tile_north = lat_sw + 1.0
            tile_west = lon_sw
            row_float = (tile_north - lat_grid) / cellsize
            col_float = (lon_grid - tile_west) / cellsize
            row_idx = np.rint(row_float).astype(int)
            col_idx = np.rint(col_float).astype(int)
            valid = (
                (row_idx >= 0) & (row_idx < arr.shape[0])
                & (col_idx >= 0) & (col_idx < arr.shape[1])
            )
            elev2d[valid] = arr[row_idx[valid], col_idx[valid]]

    if np.isfinite(elev2d).sum() < 4:
        raise RuntimeError("Elevation data unavailable for the selected area.")

    # Fill any holes by nearest-neighbour interpolation over WGS84 coordinates.
    good = np.isfinite(elev2d)
    observed_finite_fraction = float(good.mean())
    if not good.all():
        elev2d = griddata(
            (lat_grid[good], lon_grid[good]),
            elev2d[good],
            (lat_grid, lon_grid),
            method="nearest",
        )

    to_utm = make_transformer(WGS84, utm)
    xs_flat, ys_flat = to_utm.transform(lon_grid.ravel(), lat_grid.ravel())
    xs = np.asarray(xs_flat).reshape(lat_grid.shape)
    ys = np.asarray(ys_flat).reshape(lat_grid.shape)

    return {
        "lat_axis": lats,
        "lon_axis": lons,
        "elevation": elev2d,
        "x_grid": xs,
        "y_grid": ys,
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "resolution": res,
        "source": "SRTM 1 arc-second via AWS elevation-tiles-prod/Skadi",
        "tiles": tile_records,
        "finite_fraction": float(np.isfinite(elev2d).mean()),
        "observed_finite_fraction": observed_finite_fraction,
        "interpolated_fraction": float((~good & np.isfinite(elev2d)).mean()),
        "interpolation_method": "nearest" if not good.all() else None,
    }


def _tile_parts(lat_sw: float, lon_sw: float) -> tuple[str, str, int, int]:
    """Return AWS Skadi tile directory, filename, and integer SW corner."""
    if lat_sw < 0:
        ns = "S"
        lat_int = int(abs(lat_sw))
    else:
        ns = "N"
        lat_int = int(lat_sw)
    if lon_sw < 0:
        ew = "W"
        lon_int = int(abs(lon_sw))
    else:
        ew = "E"
        lon_int = int(lon_sw)
    tile_dir = f"{ns}{lat_int:02d}"
    tile_name = f"{tile_dir}{ew}{lon_int:03d}.hgt.gz"
    return tile_dir, tile_name, lat_int, lon_int


def _read_hgt(content: bytes) -> np.ndarray:
    with gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb") as fh:
        raw = fh.read()
    n = int(math.isqrt(len(raw) // 2))
    expected = n * n * 2
    if len(raw) != expected:
        raise ValueError(f"Unexpected HGT size: {len(raw)} bytes")
    arr = np.frombuffer(raw, dtype=">i2").reshape(n, n).astype(float)
    # SRTM uses -32768 as void data; keep those as nan.
    arr[arr <= -32768] = np.nan
    return arr


def compute_terrain(elev: np.ndarray, dx: float, dy: float) -> dict:
    fy, fx = np.gradient(elev, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(fx, fy)))
    aspect = (np.degrees(np.arctan2(-fx, -fy))) % 360.0
    flat = slope < 1.0
    aspect = np.where(flat, -1.0, aspect)
    return {"slope": slope, "aspect": aspect}


def hillshade(elev: np.ndarray, dx: float, dy: float, azimuth: float = 225.0,
              altitude: float = 35.0) -> np.ndarray:
    fy, fx = np.gradient(elev, dy, dx)
    slope = np.arctan(np.hypot(fx, fy))
    aspect = np.arctan2(-fx, -fy)
    az = np.radians(azimuth % 360.0)
    alt = np.radians(altitude)
    shaded = (
        np.sin(alt) * np.cos(slope)
        + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    )
    return np.clip(shaded, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Climate
# ---------------------------------------------------------------------------


def climate_request_params(lat: float, lon: float, start_year: int, end_year: int,
                           model: str | None = None) -> dict:
    start = f"{start_year}-01-01"
    end = f"{end_year}-12-31"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "timezone": "auto",
        "wind_speed_unit": "ms",
        "hourly": "wind_speed_10m,wind_direction_10m,temperature_2m,shortwave_radiation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,shortwave_radiation_sum",
    }
    if model:
        params["models"] = model
    return params


def fetch_climate(lat: float, lon: float, start_year: int = 2019, end_year: int = 2023,
                  model: str | None = None) -> tuple[dict, dict]:
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = climate_request_params(lat, lon, start_year, end_year, model)
    request_meta = {"endpoint": url, "params": params, "retrieved_at_utc": utc_now_iso()}
    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        request_meta["response_units"] = {
            "hourly": data.get("hourly_units", {}),
            "daily": data.get("daily_units", {}),
        }
        request_meta["response_grid"] = {
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "elevation": data.get("elevation"),
            "timezone": data.get("timezone"),
        }
        return data, request_meta
    except Exception as exc:
        print(f"[site-analysis] Climate request failed: {exc}")
        request_meta["error"] = str(exc)
        return {}, request_meta


def wind_rose_data(data: dict) -> dict:
    hourly = data.get("hourly", {})
    if not hourly:
        return {"direction": np.asarray([]), "speed": np.asarray([]), "unit": "m/s"}
    direction = np.asarray(hourly.get("wind_direction_10m", []), dtype=float)
    speed = np.asarray(hourly.get("wind_speed_10m", []), dtype=float)
    if direction.shape != speed.shape:
        return {"direction": np.asarray([]), "speed": np.asarray([]), "unit": "m/s"}
    mask = np.isfinite(direction) & np.isfinite(speed)
    direction = np.mod(direction[mask], 360.0)
    speed = speed[mask]
    source_unit = normalize_tag(data.get("hourly_units", {}).get("wind_speed_10m")).lower()
    if source_unit in {"km/h", "kmh", "km/hours"}:
        speed = speed / 3.6
    elif source_unit in {"mph"}:
        speed = speed * 0.44704
    elif source_unit in {"kn", "kt", "knots"}:
        speed = speed * 0.514444
    elif source_unit not in {"m/s", "ms", ""}:
        raise ValueError(f"Unsupported wind-speed unit: {source_unit}")
    return {"direction": direction, "speed": speed, "unit": "m/s", "source_unit": source_unit}


def wind_rose_frequencies(direction: np.ndarray, speed: np.ndarray,
                          sector_count: int = 16,
                          speed_bins: tuple[float, ...] = (0, 3, 6, 10, 15, math.inf)) -> dict:
    """Compute speed-by-direction frequencies with north-centered sectors."""
    direction = np.asarray(direction, dtype=float)
    speed = np.asarray(speed, dtype=float)
    mask = np.isfinite(direction) & np.isfinite(speed) & (speed >= 0)
    direction = np.mod(direction[mask], 360.0)
    speed = speed[mask]
    width = 360.0 / sector_count
    sector_index = np.floor(np.mod(direction + width / 2.0, 360.0) / width).astype(int)
    speed_edges = np.asarray(speed_bins, dtype=float)
    speed_index = np.digitize(speed, speed_edges[1:-1], right=False)
    counts = np.zeros((len(speed_edges) - 1, sector_count), dtype=float)
    for s_idx, d_idx in zip(speed_index, sector_index):
        counts[s_idx, d_idx] += 1.0
    total = float(counts.sum())
    frequencies = counts / total if total else counts
    centers = np.arange(sector_count, dtype=float) * width
    return {
        "frequencies": frequencies,
        "centers_degrees": centers,
        "sector_width_degrees": width,
        "speed_bins": speed_edges,
        "sample_count": int(total),
    }


def monthly_solar(data: dict) -> pd.DataFrame:
    daily = data.get("daily", {})
    times = pd.to_datetime(daily.get("time", []), errors="coerce")
    solar = pd.to_numeric(pd.Series(daily.get("shortwave_radiation_sum", [])), errors="coerce")
    if times.empty or solar.empty:
        return pd.DataFrame(columns=["month", "radiation"])
    df = pd.DataFrame({"time": times, "radiation": solar}).dropna()
    if df.empty:
        return df
    df["month"] = df["time"].dt.month
    return df.groupby("month")["radiation"].mean().reset_index()


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def north_arrow_vector(x: float = 0.045, y: float = 0.92,
                       length: float = 0.06) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return arrow tail and tip in axes coordinates; the tip is always north/up."""
    return (x, y - length), (x, y)


def add_north_arrow(ax, x: float = 0.045, y: float = 0.92) -> None:
    tail, tip = north_arrow_vector(x, y)
    ax.annotate(
        "N",
        xy=(x, y + 0.012),
        xycoords="axes fraction",
        ha="center",
        va="bottom",
        fontsize=12,
        fontweight="bold",
        color="#111111",
    )
    ax.annotate(
        "",
        xy=tip,
        xytext=tail,
        xycoords="axes fraction",
        textcoords="axes fraction",
        arrowprops={"arrowstyle": "-|>", "lw": 1.6, "color": "#111111"},
    )


def choose_scale_bar_length(width_m: float, target_fraction: float = 0.20) -> float:
    target = max(float(width_m) * target_fraction, 1e-9)
    exponent = math.floor(math.log10(target))
    base = 10.0 ** exponent
    candidates = np.asarray([1.0, 2.0, 5.0, 10.0]) * base
    return float(candidates[np.argmin(np.abs(candidates - target))])


def add_scale_bar(ax, length_m: float | None = None) -> float:
    """Draw an exact data-coordinate scale bar and return its represented length."""
    minx, maxx = ax.get_xlim()
    miny, maxy = ax.get_ylim()
    width = abs(maxx - minx)
    height = abs(maxy - miny)
    length_m = float(length_m or choose_scale_bar_length(width))
    if length_m > width * 0.8:
        raise ValueError("Scale bar is too long for the current map extent")
    x1 = maxx - width * 0.05
    x0 = x1 - length_m
    y = miny + height * 0.045
    tick = height * 0.009
    midpoint = (x0 + x1) / 2.0
    ax.plot([x0, midpoint], [y, y], color="#111111", linewidth=3.0, solid_capstyle="butt", zorder=50)
    ax.plot([midpoint, x1], [y, y], color="#777777", linewidth=3.0, solid_capstyle="butt", zorder=50)
    for x in (x0, midpoint, x1):
        ax.plot([x, x], [y - tick, y + tick], color="#111111", linewidth=1.1, zorder=50)
    ax.text(
        midpoint,
        y + tick * 1.6,
        f"{length_m:g} m",
        ha="center",
        va="bottom",
        fontsize=8,
        color="#111111",
        zorder=50,
    )
    return length_m


def add_source_note(fig, text: str) -> None:
    fig.text(0.01, 0.01, text, fontsize=7, color="#555555", va="bottom", ha="left")


def osm_source_status(layers: dict) -> dict:
    """Keep availability separate from feature counts, including for legacy callers."""
    return {
        key: dict(layers[key].attrs.get("source_status", {
            "status": "available" if len(layers[key]) else "unknown"
        }))
        for key in ("buildings", "roads", "landuse", "transit")
    }


def add_osm_status_note(fig, layers: dict) -> None:
    labels = {"unavailable": "UNAVAILABLE", "skipped": "SKIPPED",
              "no_matches": "no matches (completeness unknown)",
              "empty": "no features returned", "unknown": "availability unknown"}
    notes = [f"{key}: {labels[meta['status']]}" for key, meta in osm_source_status(layers).items()
             if meta["status"] in labels]
    if notes:
        fig.text(0.01, 0.045, textwrap.fill("OSM - " + "; ".join(notes), width=100), fontsize=9,
                 color="#985c00", va="bottom", ha="left")


def add_terrain_status_note(fig, terrain: dict) -> None:
    observed = terrain.get("observed_finite_fraction")
    interpolated = terrain.get("interpolated_fraction", 0.0)
    if observed is not None and interpolated > 0:
        fig.text(0.01, 0.055,
                 f"DEM source coverage {observed:.1%}; nearest interpolation {interpolated:.1%}",
                 fontsize=9, color="#985c00", va="bottom", ha="left")


def style_axes(ax) -> None:
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()


def study_extent_gdf(lon: float, lat: float, radius: float, utm: CRS) -> gpd.GeoDataFrame:
    to_utm = make_transformer(WGS84, utm)
    x, y = to_utm.transform(lon, lat)
    return gpd.GeoDataFrame(geometry=[Point(x, y).buffer(radius)], crs=utm)


def load_site_boundary(path: str | None, utm: CRS) -> gpd.GeoDataFrame:
    if not path:
        return gpd.GeoDataFrame(geometry=[], crs=utm)
    boundary = gpd.read_file(path)
    if boundary.empty:
        raise ValueError(f"Site-boundary file contains no geometry: {path}")
    if boundary.crs is None:
        raise ValueError("Site-boundary file must declare a CRS")
    boundary = boundary.to_crs(utm)
    boundary = boundary[boundary.geometry.notna() & ~boundary.geometry.is_empty].copy()
    if boundary.empty:
        raise ValueError("Site-boundary file has no usable geometry")
    return boundary


def plot_extent_and_boundary(ax, study_extent: gpd.GeoDataFrame,
                             site_boundary: gpd.GeoDataFrame | None = None,
                             linewidth: float = 1.4) -> None:
    study_extent.boundary.plot(
        ax=ax,
        color="#c94b4b",
        linewidth=linewidth,
        linestyle=(0, (4, 3)),
        zorder=40,
    )
    if site_boundary is not None and not site_boundary.empty:
        site_boundary.boundary.plot(
            ax=ax,
            color="#b11f24",
            linewidth=linewidth * 1.5,
            linestyle="-",
            zorder=41,
        )


def add_unavailable(ax, message: str = "数据不可用 / Data unavailable") -> None:
    ax.text(
        0.5,
        0.5,
        message,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=10,
        color="#777777",
        bbox={"facecolor": "white", "edgecolor": "#cccccc", "pad": 5},
        zorder=100,
    )


def project_gdf(gdf: gpd.GeoDataFrame, utm: CRS) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf.to_crs(utm)
    return gdf.to_crs(utm)


def save_figure(fig, out_dir: Path, name: str, dpi: int = 300) -> list[Path]:
    outputs = []
    for ext in ("png", "svg", "pdf"):
        path = out_dir / f"{name}.{ext}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.08, facecolor="white")
        outputs.append(path)
    plt.close(fig)
    return outputs


def plot_context(layers: dict, study_extent: gpd.GeoDataFrame,
                 site_boundary: gpd.GeoDataFrame, bounds: tuple,
                 out_dir: Path, source_note: str) -> list[Path]:
    fig, ax = plt.subplots(figsize=(10, 10))
    minx, miny, maxx, maxy = bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    style_axes(ax)

    land = layers["landuse"]
    if not land.empty:
        for kind, style in LANDUSE_STYLE.items():
            sub = land[land["class"] == kind]
            if not sub.empty:
                sub.plot(ax=ax, facecolor=style["facecolor"], edgecolor=style["edgecolor"],
                         linewidth=style["linewidth"], zorder=1)

    for _, row in layers["roads"].iterrows():
        style = ROAD_STYLE.get(row.get("class", "other"), ROAD_STYLE["other"])
        gpd.GeoSeries([row.geometry]).plot(ax=ax, color=style["color"], linewidth=style["linewidth"],
                                           linestyle=style.get("linestyle", "-"), zorder=3)

    if not layers["buildings"].empty:
        layers["buildings"].plot(ax=ax, facecolor="#1a1a1a", edgecolor="none", zorder=4)

    if not layers["transit"].empty:
        for kind, style in TRANSIT_STYLE.items():
            sub = layers["transit"][layers["transit"]["class"] == kind]
            if not sub.empty:
                sub.plot(ax=ax, marker=style["marker"], color=style["color"], markersize=style["size"],
                         edgecolor="white", linewidth=0.4, zorder=6)

    if not layers["photos"].empty:
        layers["photos"].plot(ax=ax, marker="^", color="#1f77b4", markersize=75,
                              edgecolor="white", linewidth=0.6, zorder=8)

    plot_extent_and_boundary(ax, study_extent, site_boundary)
    add_north_arrow(ax)
    add_scale_bar(ax)
    ax.set_title("Site context / figure-ground", fontsize=13, pad=12)
    add_osm_status_note(fig, layers)
    add_source_note(fig, source_note)
    return save_figure(fig, out_dir, "01_context_figure_ground")


def plot_landuse(layers: dict, study_extent: gpd.GeoDataFrame,
                 site_boundary: gpd.GeoDataFrame, bounds: tuple,
                 out_dir: Path, source_note: str) -> list[Path]:
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    style_axes(ax)

    land = layers["landuse"]
    handles = []
    if not land.empty:
        for kind, style in LANDUSE_STYLE.items():
            sub = land[land["class"] == kind]
            if not sub.empty:
                sub.plot(ax=ax, facecolor=style["facecolor"], edgecolor=style["edgecolor"],
                         linewidth=style["linewidth"], zorder=1)
                handles.append(plt.Rectangle((0, 0), 1, 1, facecolor=style["facecolor"],
                                             edgecolor=style["edgecolor"], label=kind.title()))

    if not layers["buildings"].empty:
        layers["buildings"].plot(ax=ax, facecolor="#b7b7b7", edgecolor="none", zorder=2)
        handles.append(plt.Rectangle((0, 0), 1, 1, facecolor="#b7b7b7", label="Building"))

    if not layers["roads"].empty:
        layers["roads"].plot(ax=ax, color="#555555", linewidth=0.8, zorder=3)
    plot_extent_and_boundary(ax, study_extent, site_boundary)
    if handles:
        ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9)
    add_north_arrow(ax)
    add_scale_bar(ax)
    ax.set_title("Land use / green-blue network", fontsize=13, pad=12)
    add_osm_status_note(fig, layers)
    add_source_note(fig, source_note)
    return save_figure(fig, out_dir, "02_landuse")


def plot_circulation(layers: dict, study_extent: gpd.GeoDataFrame,
                     site_boundary: gpd.GeoDataFrame, bounds: tuple,
                     out_dir: Path, source_note: str) -> list[Path]:
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    style_axes(ax)

    if not layers["landuse"].empty:
        water = layers["landuse"][layers["landuse"]["class"] == "water"]
        if not water.empty:
            water.plot(ax=ax, facecolor="#d4e7f0", edgecolor="none", zorder=0)

    if not layers["buildings"].empty:
        layers["buildings"].plot(ax=ax, facecolor="#e8e2d9", edgecolor="#c4bbad", linewidth=0.25, zorder=1)

    for _, row in layers["roads"].iterrows():
        style = ROAD_STYLE.get(row.get("class", "other"), ROAD_STYLE["other"])
        gpd.GeoSeries([row.geometry]).plot(ax=ax, color=style["color"], linewidth=style["linewidth"],
                                           linestyle=style.get("linestyle", "-"), zorder=2)

    handles = [
        plt.Line2D([0], [0], color=ROAD_STYLE["primary"]["color"], linewidth=2.6, label="Primary/trunk"),
        plt.Line2D([0], [0], color=ROAD_STYLE["major"]["color"], linewidth=2.0, label="Major"),
        plt.Line2D([0], [0], color=ROAD_STYLE["local"]["color"], linewidth=1.0, label="Local"),
        plt.Line2D([0], [0], color=ROAD_STYLE["pedestrian"]["color"], linewidth=0.9, linestyle="--", label="Pedestrian/cycle"),
    ]

    if not layers["transit"].empty:
        for kind, style in TRANSIT_STYLE.items():
            sub = layers["transit"][layers["transit"]["class"] == kind]
            if not sub.empty:
                sub.plot(ax=ax, marker=style["marker"], color=style["color"], markersize=style["size"],
                         edgecolor="white", linewidth=0.4, zorder=3)
                handles.append(plt.Line2D([0], [0], marker=style["marker"], color="w",
                                          markerfacecolor=style["color"], markersize=7, label=style["label"]))

    if not layers["photos"].empty:
        layers["photos"].plot(ax=ax, marker="^", color="#1f77b4", markersize=75,
                              edgecolor="white", linewidth=0.6, zorder=5)
        handles.append(plt.Line2D([0], [0], marker="^", color="w",
                                  markerfacecolor="#1f77b4", markersize=7, label="Photo viewpoint"))

    plot_extent_and_boundary(ax, study_extent, site_boundary)
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9)
    add_north_arrow(ax)
    add_scale_bar(ax)
    ax.set_title("Circulation and access", fontsize=13, pad=12)
    add_osm_status_note(fig, layers)
    add_source_note(fig, source_note)
    return save_figure(fig, out_dir, "03_circulation_access")


def plot_terrain(terrain: dict, study_extent: gpd.GeoDataFrame,
                 site_boundary: gpd.GeoDataFrame, bounds: tuple, out_dir: Path,
                 contour_interval: float, source_note: str) -> list[Path]:
    elev = terrain["elevation"]
    xs = terrain["x_grid"]
    ys = terrain["y_grid"]
    dx = float(np.nanmean(np.gradient(xs[0]))) or 30.0
    dy = float(np.nanmean(np.gradient(ys[:, 0]))) or 30.0

    fig, ax = plt.subplots(figsize=(10, 10))
    hs = hillshade(elev, dx, dy)
    ax.imshow(hs, extent=(xs.min(), xs.max(), ys.min(), ys.max()), cmap="Greys",
              vmin=0.25, vmax=1.0, alpha=0.75, origin="lower", zorder=0)
    levels = np.arange(math.floor(np.nanmin(elev) / contour_interval) * contour_interval,
                       math.ceil(np.nanmax(elev) / contour_interval) * contour_interval + contour_interval,
                       contour_interval)
    cs = ax.contour(xs, ys, elev, levels=levels, colors="#4a3f2f", linewidths=0.65, zorder=1)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%.0f m", colors="#4a3f2f")
    plot_extent_and_boundary(ax, study_extent, site_boundary)
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    style_axes(ax)
    add_north_arrow(ax)
    add_scale_bar(ax)
    ax.set_title(f"Terrain hillshade and contours ({contour_interval:g} m)", fontsize=13, pad=12)
    add_terrain_status_note(fig, terrain)
    add_source_note(fig, source_note)
    outputs = save_figure(fig, out_dir, "04_terrain_contours")

    fig = plt.figure(figsize=(10, 10))
    grid = fig.add_gridspec(2, 2, hspace=0.16, wspace=0.12)
    axes = [
        fig.add_subplot(grid[0, 0]),
        fig.add_subplot(grid[0, 1]),
        fig.add_subplot(grid[1, :]),
    ]
    extent = (xs.min(), xs.max(), ys.min(), ys.max())
    im1 = axes[0].imshow(terrain["slope"], extent=extent, cmap="YlOrRd", vmin=0, vmax=30, origin="lower")
    axes[0].set_title("Slope (degrees)")
    plt.colorbar(im1, ax=axes[0], fraction=0.046, pad=0.02)

    aspect = np.where(terrain["aspect"] < 0, np.nan, terrain["aspect"])
    im2 = axes[1].imshow(aspect, extent=extent, cmap="twilight", vmin=0, vmax=360, origin="lower")
    axes[1].set_title("Aspect (compass)")
    plt.colorbar(im2, ax=axes[1], fraction=0.046, pad=0.02)

    hs2 = hillshade(elev, dx, dy, azimuth=135, altitude=25)
    im3 = axes[2].imshow(hs2, extent=extent, cmap="Greys", vmin=0, vmax=1, origin="lower")
    axes[2].set_title("Hillshade")
    plt.colorbar(im3, ax=axes[2], fraction=0.046, pad=0.02)

    for a in axes:
        a.set_aspect("equal", adjustable="box")
        a.set_axis_off()
        plot_extent_and_boundary(a, study_extent, site_boundary, linewidth=1.0)
        add_north_arrow(a)
    add_source_note(fig, source_note)
    add_terrain_status_note(fig, terrain)
    outputs.extend(save_figure(fig, out_dir, "05_slope_aspect_hillshade"))
    return outputs


def plot_climate(climate: dict, out_dir: Path, source_note: str) -> list[Path]:
    fig = plt.figure(figsize=(10, 10))
    grid = fig.add_gridspec(2, 1, hspace=0.28)
    ax = fig.add_subplot(grid[0, 0], projection="polar")
    wind = wind_rose_data(climate)
    if len(wind["direction"]):
        rose = wind_rose_frequencies(wind["direction"], wind["speed"])
        speed_bins = rose["speed_bins"]
        colors = ["#cce5ff", "#9ec9ff", "#5aa2e0", "#2f6fb2", "#173b63"]
        angles = np.deg2rad(rose["centers_degrees"])
        width = np.deg2rad(rose["sector_width_degrees"] * 0.92)
        bottom = np.zeros_like(rose["centers_degrees"], dtype=float)
        for i, frequency in enumerate(rose["frequencies"]):
            upper = speed_bins[i + 1]
            label = f"{speed_bins[i]:g}+ m/s" if math.isinf(upper) else f"{speed_bins[i]:g}–{upper:g} m/s"
            ax.bar(angles, frequency, width=width, bottom=bottom,
                   color=colors[i], edgecolor="white", linewidth=0.3, label=label)
            bottom += frequency
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.legend(loc="upper right", bbox_to_anchor=(1.18, 1.12), frameon=False, fontsize=8, title="Wind speed")
        ax.set_yticklabels([])
    else:
        add_unavailable(ax, "Wind archive unavailable")
    ax.set_title("Wind rose (direction from)", fontsize=11, pad=14)

    ax2 = fig.add_subplot(grid[1, 0])
    solar = monthly_solar(climate)
    if not solar.empty:
        ax2.bar(solar["month"], solar["radiation"], color="#e5a94f", width=0.7)
        ax2.set_xlabel("Month")
        ax2.set_ylabel("Mean daily shortwave (MJ/m²)")
    else:
        add_unavailable(ax2, "Solar archive unavailable")
    ax2.set_title("Seasonal solar radiation", fontsize=11)
    ax2.set_xticks(range(1, 13))
    ax2.grid(axis="y", linestyle=":", linewidth=0.5)
    fig.suptitle("Climate context", fontsize=14)
    add_source_note(fig, source_note)
    return save_figure(fig, out_dir, "06_climate_wind_solar")


def plot_unavailable(out_dir: Path, name: str, title: str,
                     source_note: str, message: str) -> list[Path]:
    fig, ax = plt.subplots(figsize=(10, 7))
    style_axes(ax)
    add_unavailable(ax, message)
    ax.set_title(title, fontsize=13, pad=12)
    add_source_note(fig, source_note)
    return save_figure(fig, out_dir, name)


def _png_from(outputs: list[Path], stem: str) -> Path:
    for path in outputs:
        if path.suffix.lower() == ".png" and path.stem == stem:
            return path
    raise FileNotFoundError(f"PNG output not found for {stem}")


def render_analysis_board(panel_images: list[tuple[str, Path]], layers: dict,
                          terrain: dict, qa: dict, provenance: dict,
                          out_dir: Path, site_name: str,
                          source_note: str) -> list[Path]:
    """Compose a presentation-ready 3x3 board from verified analysis panels."""
    fig, axes = plt.subplots(3, 3, figsize=(20, 20))
    axes_flat = list(axes.flat)
    for ax, (title, image_path) in zip(axes_flat[:6], panel_images):
        ax.imshow(plt.imread(image_path))
        ax.set_title(title, fontsize=12, fontweight="bold", pad=8, loc="left")
        ax.set_axis_off()

    metrics_ax = axes_flat[6]
    metrics_ax.set_axis_off()
    elevation_text = "Unavailable"
    if terrain and np.isfinite(terrain.get("elevation", np.asarray([]))).any():
        elev = terrain["elevation"]
        elevation_text = f"{np.nanmin(elev):.1f}–{np.nanmax(elev):.1f} m"
    statuses = osm_source_status(layers)

    def layer_metric(key):
        status = statuses[key]["status"]
        if status == "available":
            return f"{len(layers[key]):,}"
        return {"empty": "0 (returned)", "unavailable": "UNAVAILABLE",
                "no_matches": "NO MATCHES*",
                "skipped": "SKIPPED", "unknown": "UNKNOWN"}.get(status, "UNKNOWN")

    metrics = [
        "PROJECT METRICS",
        f"Buildings       {layer_metric('buildings')}",
        f"Road segments   {layer_metric('roads')}",
        f"Land-use areas  {layer_metric('landuse')}",
        f"Transit / POI   {layer_metric('transit')}",
        f"Photo points    {len(layers['photos']):,}",
        f"Elevation       {elevation_text}",
    ]
    if any(meta["status"] == "no_matches" for meta in statuses.values()):
        metrics.append("* Upstream completeness unknown")
    metrics_ax.text(0.04, 0.96, "\n".join(metrics), transform=metrics_ax.transAxes,
                    va="top", ha="left", fontsize=12, linespacing=1.7,
                    family="monospace", color="#202020")

    provenance_ax = axes_flat[7]
    provenance_ax.set_axis_off()
    active_sources = []
    if provenance.get("osm", {}).get("queries"):
        active_sources.append("OpenStreetMap / Overpass")
    if provenance.get("elevation", {}).get("tiles"):
        active_sources.append("SRTM 1 arc-second / AWS")
    if provenance.get("climate", {}).get("endpoint"):
        active_sources.append("Open-Meteo archive")
    if provenance.get("inputs", {}).get("site_boundary"):
        active_sources.append("User site boundary")
    provenance_lines = ["DATA PROVENANCE", *[f"• {item}" for item in active_sources]]
    if not active_sources:
        provenance_lines.append("• No remote source requested")
    provenance_lines.extend([
        "",
        f"CRS  EPSG:{provenance['crs']['epsg']}",
        f"Run  {provenance['run_id']}",
        "Hashes are recorded in manifest.json",
    ])
    provenance_ax.text(0.04, 0.96, "\n".join(provenance_lines),
                       transform=provenance_ax.transAxes, va="top", ha="left",
                       fontsize=12, linespacing=1.6, color="#202020")

    qa_ax = axes_flat[8]
    qa_ax.set_axis_off()
    status_color = {"pass": "#227447", "warn": "#a46a00", "fail": "#b11f24"}.get(
        qa["status"], "#333333"
    )
    qa_ax.text(0.04, 0.96, f"QUALITY GATE  {qa['status'].upper()}",
               transform=qa_ax.transAxes, va="top", ha="left",
               fontsize=13, fontweight="bold", color=status_color)
    y = 0.84
    for check in qa["checks"]:
        icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(
            check["status"], "INFO"
        )
        qa_ax.text(0.04, y, f"{icon}  {check['name']}: {check['detail']}",
                   transform=qa_ax.transAxes, va="top", ha="left",
                   fontsize=10.5, fontweight="bold", color="#282828", wrap=True)
        y -= 0.095
        if y < 0.06:
            break

    fig.suptitle(site_name, x=0.035, y=0.995, ha="left", va="top",
                 fontsize=24, fontweight="bold", color="#171717")
    fig.text(0.965, 0.985, "ARCHITECTURAL SITE ANALYSIS", ha="right", va="top",
             fontsize=10, color="#6a6a6a")
    add_source_note(fig, source_note)
    fig.subplots_adjust(left=0.025, right=0.975, top=0.965, bottom=0.03,
                        wspace=0.045, hspace=0.075)
    return save_figure(fig, out_dir, "00_analysis_board", dpi=240)


# ---------------------------------------------------------------------------
# Report and orchestration
# ---------------------------------------------------------------------------


def evaluate_quality(args, utm: CRS, bounds: tuple, layers: dict,
                     terrain: dict, climate: dict,
                     site_boundary: gpd.GeoDataFrame) -> dict:
    checks: list[dict] = []

    def record(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    record("projected_crs", "pass" if utm.is_projected else "fail",
           f"EPSG:{utm.to_epsg()} in metres" if utm.is_projected else "CRS is not projected")
    finite_bounds = all(math.isfinite(float(value)) for value in bounds)
    record("map_extent", "pass" if finite_bounds and args.radius > 0 else "fail",
           f"{2 * args.radius:g} × {2 * args.radius:g} m study extent")
    marker_types = set(layers["transit"].geometry.geom_type) if not layers["transit"].empty else set()
    record("poi_geometry", "pass" if not marker_types or marker_types <= {"Point", "MultiPoint"} else "fail",
           "POIs rendered as points" if marker_types <= {"Point", "MultiPoint"} else str(sorted(marker_types)))
    if terrain:
        finite_fraction = float(terrain.get("finite_fraction", np.isfinite(terrain["elevation"]).mean()))
        observed = terrain.get("observed_finite_fraction")
        if observed is None:
            record("elevation_coverage", "warn",
                   f"{finite_fraction:.1%} finite DEM cells; source coverage unknown")
        else:
            interpolated = float(terrain.get("interpolated_fraction", 0.0))
            record("elevation_coverage", "pass" if observed >= 0.99 else "warn",
                   f"{observed:.1%} source DEM; {interpolated:.1%} interpolated")
    else:
        record("elevation_coverage", "warn", "Elevation analysis skipped or unavailable")
    wind = wind_rose_data(climate)
    if len(wind["speed"]):
        record("wind_units", "pass", f"Normalized to {wind['unit']} from {wind.get('source_unit') or 'declared m/s'}")
    else:
        record("wind_units", "warn", "Climate analysis skipped or unavailable")
    record("site_boundary", "pass" if not site_boundary.empty else "warn",
           "User-supplied boundary shown as solid red" if not site_boundary.empty
           else "No parcel/site polygon supplied; dashed line is study extent only")
    statuses = osm_source_status(layers)
    gaps = [f"{key}: {meta['status']}" for key, meta in statuses.items()
            if meta["status"] != "available"]
    if gaps:
        record("osm_layers", "warn", "; ".join(gaps))
    elif any(len(layers[key]) for key in ("buildings", "roads", "landuse", "transit")):
        record("osm_layers", "pass", "At least one OSM context layer retrieved")
    else:
        record("osm_layers", "warn", "OSM analysis skipped or no features returned")

    status = "fail" if any(item["status"] == "fail" for item in checks) else (
        "warn" if any(item["status"] == "warn" for item in checks) else "pass"
    )
    return {"status": status, "checks": checks, "evaluated_at_utc": utc_now_iso()}


def build_provenance(args, run_id: str, run_dir: Path, utm: CRS,
                     terrain: dict, climate_meta: dict, layers: dict | None = None) -> dict:
    boundary_meta = None
    if args.site_boundary:
        boundary_path = Path(args.site_boundary).resolve()
        boundary_meta = {
            "path": str(boundary_path),
            "sha256": sha256_file(boundary_path),
        }
    script_path = Path(__file__).resolve()
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "generator": {"path": str(script_path), "sha256": sha256_file(script_path)},
        "output_directory": str(run_dir.resolve()),
        "inputs": {
            "site_name": args.site_name,
            "center": {"lat": args.lat, "lon": args.lon},
            "study_radius_m": args.radius,
            "site_boundary": boundary_meta,
            "photo_manifest": str(Path(args.photo_manifest).resolve()) if args.photo_manifest else None,
        },
        "crs": {"epsg": utm.to_epsg(), "wkt": utm.to_wkt()},
        "osm": {"attribution": "© OpenStreetMap contributors", "queries": list(OSM_QUERY_LOG),
                "layer_status": osm_source_status(layers) if layers is not None else {}},
        "elevation": {
            "source": terrain.get("source"),
            "resolution_m": terrain.get("resolution"),
            "tiles": terrain.get("tiles", []),
            "observed_finite_fraction": terrain.get("observed_finite_fraction"),
            "interpolated_fraction": terrain.get("interpolated_fraction"),
            "interpolation_method": terrain.get("interpolation_method"),
        },
        "climate": climate_meta,
    }


def build_report(args, run_id: str, run_dir: Path, utm: CRS, layers: dict,
                 terrain: dict, climate: dict, bounds: tuple,
                 out_files: list[Path], qa: dict) -> dict:
    elev = terrain.get("elevation")
    report = {
        "site_name": args.site_name,
        "run_id": run_id,
        "center": {"lat": args.lat, "lon": args.lon},
        "radius_m": args.radius,
        "crs": utm.to_epsg(),
        "bounds_utm": {"minx": bounds[0], "miny": bounds[1], "maxx": bounds[2], "maxy": bounds[3]},
        "features": {
            "buildings": int(len(layers["buildings"])),
            "landuse": int(len(layers["landuse"])),
            "roads": int(len(layers["roads"])),
            "transit": int(len(layers["transit"])),
            "photo_viewpoints": int(len(layers["photos"])),
        },
        "terrain": {},
        "climate": {"retrieved": bool(climate.get("hourly"))},
        "quality_status": qa["status"],
        "osm_layer_status": osm_source_status(layers),
        "outputs": [p.resolve().relative_to(run_dir.resolve()).as_posix() for p in out_files],
        "sources": "OSM © OpenStreetMap contributors; SRTM via AWS terrain tiles; Open-Meteo",
    }
    if elev is not None and np.isfinite(elev).any():
        report["terrain"] = {
            "min_elevation_m": round(float(np.nanmin(elev)), 1),
            "max_elevation_m": round(float(np.nanmax(elev)), 1),
            "mean_elevation_m": round(float(np.nanmean(elev)), 1),
            "resolution_m": terrain.get("resolution"),
        }
    return report


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate site-analysis diagrams from open data.")
    p.add_argument("--site-name", default="Study site")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--radius", type=float, default=500.0, help="Site study radius in meters")
    p.add_argument("--out-dir", default="site-analysis-output")
    p.add_argument("--run-id", default=None,
                   help="Optional stable run directory name; otherwise a unique timestamped id is used")
    p.add_argument("--site-boundary", default=None,
                   help="GeoJSON/GPKG/Shapefile site boundary with a declared CRS")
    p.add_argument("--contour-interval", type=float, default=5.0)
    p.add_argument("--elevation-resolution", type=float, default=30.0)
    p.add_argument("--climate-start", type=int, default=2019)
    p.add_argument("--climate-end", type=int, default=2023)
    p.add_argument("--climate-model", default=None,
                   help="Optional Open-Meteo archive model identifier")
    p.add_argument("--skip-osm", action="store_true")
    p.add_argument("--skip-elevation", action="store_true")
    p.add_argument("--skip-climate", action="store_true")
    p.add_argument("--photo-manifest", default=None,
                   help="Path to imagery_manifest.json from ingest_imagery.py")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    OSM_QUERY_LOG.clear()
    output_root = Path(args.out_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id, out_dir = create_run_dir(output_root, args.run_id)
    cache_dir = output_root / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    utm = utm_crs_for(args.lon, args.lat)
    to_utm = make_transformer(WGS84, utm)
    cx, cy = to_utm.transform(args.lon, args.lat)
    bounds = (cx - args.radius, cy - args.radius, cx + args.radius, cy + args.radius)

    print(f"[site-analysis] Site: {args.site_name} at {args.lat}, {args.lon} | radius {args.radius} m")
    print(f"[site-analysis] Local CRS: EPSG:{utm.to_epsg()}")

    layers = {
        "buildings": gpd.GeoDataFrame(geometry=[], crs=utm),
        "landuse": gpd.GeoDataFrame(geometry=[], crs=utm),
        "transit": gpd.GeoDataFrame(geometry=[], crs=utm),
        "roads": gpd.GeoDataFrame(geometry=[], crs=utm),
        "photos": gpd.GeoDataFrame(geometry=[], crs=utm),
    }
    if args.skip_osm:
        for key in ("buildings", "roads", "landuse", "transit"):
            layers[key].attrs["source_status"] = {"status": "skipped"}
    if not args.skip_osm:
        print("[site-analysis] Fetching OpenStreetMap data ...")
        raw = fetch_osm(args.lat, args.lon, args.radius, cache_dir)
        for key, gdf in raw.items():
            gdf = project_gdf(gdf, utm)
            if key == "buildings":
                layers[key] = gdf
            elif key == "landuse":
                gdf["class"] = gdf.apply(classify_landuse, axis=1)
                layers[key] = gdf
            elif key == "transit":
                gdf["class"] = gdf.apply(classify_transit, axis=1)
                layers[key] = pointify_markers(gdf)
            elif key == "roads":
                gdf["class"] = gdf["highway"].map(classify_road)
                layers[key] = gdf

    if args.photo_manifest and Path(args.photo_manifest).exists():
        manifest = json.loads(Path(args.photo_manifest).read_text(encoding="utf-8"))
        photo_rows = []
        for item in manifest:
            gps = item.get("gps") or {}
            if gps.get("lat") is not None and gps.get("lon") is not None:
                photo_rows.append({
                    "geometry": Point(gps["lon"], gps["lat"]),
                    "name": item.get("name", ""),
                })
        if photo_rows:
            layers["photos"] = gpd.GeoDataFrame(photo_rows, crs=WGS84).to_crs(utm)

    terrain = {}
    if not args.skip_elevation:
        print("[site-analysis] Fetching elevation grid ...")
        terrain = fetch_elevation_grid(
            args.lat, args.lon, args.radius, utm, args.elevation_resolution, cache_dir
        )
        dx = terrain["x_grid"].shape[1] > 1 and float(np.nanmean(np.gradient(terrain["x_grid"][0]))) or args.elevation_resolution
        dy = terrain["y_grid"].shape[0] > 1 and float(np.nanmean(np.gradient(terrain["y_grid"][:, 0]))) or args.elevation_resolution
        terrain.update(compute_terrain(terrain["elevation"], dx, dy))

    climate = {}
    climate_meta = {}
    if not args.skip_climate:
        print("[site-analysis] Fetching climate archive ...")
        climate, climate_meta = fetch_climate(
            args.lat, args.lon, args.climate_start, args.climate_end, args.climate_model
        )

    study_extent = study_extent_gdf(args.lon, args.lat, args.radius, utm)
    site_boundary = load_site_boundary(args.site_boundary, utm)
    active_sources = []
    if not args.skip_osm:
        active_sources.append("OSM © OpenStreetMap contributors")
    if terrain:
        active_sources.append("SRTM / AWS Skadi")
    if climate:
        active_sources.append("Open-Meteo archive")
    source_note = (
        f"Data: {' | '.join(active_sources) if active_sources else 'user inputs only'} | "
        f"Generated {utc_now_iso()} | EPSG:{utm.to_epsg()} | Run {run_id}"
    )

    provenance = build_provenance(args, run_id, out_dir, utm, terrain, climate_meta, layers)
    qa = evaluate_quality(args, utm, bounds, layers, terrain, climate, site_boundary)
    if qa["status"] == "fail":
        raise RuntimeError("Site-analysis quality gate failed: " + json.dumps(qa, ensure_ascii=False))

    out_files: list[Path] = []
    context_outputs = plot_context(
        layers, study_extent, site_boundary, bounds, out_dir, source_note
    )
    landuse_outputs = plot_landuse(
        layers, study_extent, site_boundary, bounds, out_dir, source_note
    )
    circulation_outputs = plot_circulation(
        layers, study_extent, site_boundary, bounds, out_dir, source_note
    )
    out_files.extend(context_outputs + landuse_outputs + circulation_outputs)
    if terrain:
        terrain_outputs = plot_terrain(
            terrain, study_extent, site_boundary, bounds, out_dir,
            args.contour_interval, source_note
        )
    else:
        terrain_outputs = plot_unavailable(
            out_dir, "04_terrain_contours", "Terrain hillshade and contours",
            source_note, "Elevation analysis skipped or unavailable"
        )
        terrain_outputs.extend(plot_unavailable(
            out_dir, "05_slope_aspect_hillshade", "Slope / aspect / hillshade",
            source_note, "Elevation analysis skipped or unavailable"
        ))
    out_files.extend(terrain_outputs)

    if climate:
        climate_outputs = plot_climate(climate, out_dir, source_note)
    else:
        climate_outputs = plot_unavailable(
            out_dir, "06_climate_wind_solar", "Climate context",
            source_note, "Climate analysis skipped or unavailable"
        )
    out_files.extend(climate_outputs)

    qa_path = out_dir / "quality_report.json"
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding="utf-8")
    provenance_path = out_dir / "provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    out_files.extend([qa_path, provenance_path])

    panel_images = [
        ("01  Context / figure-ground", _png_from(context_outputs, "01_context_figure_ground")),
        ("02  Land use / green-blue", _png_from(landuse_outputs, "02_landuse")),
        ("03  Circulation / access", _png_from(circulation_outputs, "03_circulation_access")),
        ("04  Terrain / contours", _png_from(terrain_outputs, "04_terrain_contours")),
        ("05  Slope / aspect", _png_from(terrain_outputs, "05_slope_aspect_hillshade")),
        ("06  Wind / solar", _png_from(climate_outputs, "06_climate_wind_solar")),
    ]
    board_outputs = render_analysis_board(
        panel_images, layers, terrain, qa, provenance, out_dir, args.site_name, source_note
    )
    out_files.extend(board_outputs)

    report = build_report(
        args, run_id, out_dir, utm, layers, terrain, climate, bounds, out_files, qa
    )
    report_path = out_dir / "site_analysis_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    out_files.append(report_path)

    manifest_path = out_dir / "manifest.json"
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "files": build_output_manifest(out_files, out_dir),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    latest = {
        "run_id": run_id,
        "run_directory": str(out_dir),
        "manifest": str(manifest_path),
        "quality_status": qa["status"],
        "updated_at_utc": utc_now_iso(),
    }
    latest_tmp = output_root / ".latest.json.tmp"
    latest_tmp.write_text(json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_tmp.replace(output_root / "latest.json")

    print("[site-analysis] Complete.")
    print(f"[site-analysis] Run directory: {out_dir}")
    print(f"[site-analysis] Quality: {qa['status']}")
    for f in sorted(path for path in out_files if path.suffix.lower() == ".png"):
        print(f"  - {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
