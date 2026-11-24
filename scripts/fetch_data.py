#!/usr/bin/env python3
"""Fetch and pre-process the open data for one or more areas (run once, offline afterwards).

    uv run --frozen --group data python scripts/fetch_data.py [area_id ...]   # default: all areas

Writes data/areas/<id>/{area.geojson, walk_graph.json, shelters.json, meta.json} and the shared
hazard tiles data/hazard/<layer>/15/x/y.png. Sources and terms: docs/architecture/data-inventory.md.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

import osmnx as ox

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from hinan.areas import AREAS, BY_ID  # noqa: E402

DATA = ROOT / "data"
UA = "hinan-prototype/0.1 (local evaluation; one-time download)"
SHELTER_URL = "https://cyberjapandata.gsi.go.jp/xyz/skhb{n:02d}/{z}/{x}/{y}.geojson"
HAZARD_URL = "https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{x}/{y}.png"
HAZARD_LAYERS = ("04_tsunami_newlegend_data", "03_hightide_l2_shinsuishin_data", "01_flood_l2_shinsuishin_data")
HAZARD_Z = 15
SHELTER_Z = 10


def tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2**z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def get(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # no data for this tile
            return None
        raise
    finally:
        time.sleep(0.1)  # be gentle with public servers


def point_in_polygon(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def fetch_area(cfg) -> None:
    OUT = DATA / "areas" / cfg.id
    OUT.mkdir(parents=True, exist_ok=True)
    fetched_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    # 1. Boundary (OSM via Nominatim)
    area = ox.geocode_to_gdf(cfg.place)
    geom = area.geometry.iloc[0]
    (OUT / "area.geojson").write_text(json.dumps(
        {"type": "Feature", "properties": {"id": cfg.id, "name": cfg.name}, "geometry": geom.__geo_interface__},
        ensure_ascii=False))
    polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    rings = [[list(map(list, p.exterior.coords))] for p in polygons]
    west, south, east, north = geom.bounds
    print(cfg.id, "area bounds", geom.bounds, "polygons", len(polygons))

    # 2. Walking network (OSM via Overpass), slightly buffered so routes may leave the ward edge
    graph = ox.graph_from_polygon(geom.buffer(0.004), network_type="walk", simplify=True)
    graph = ox.convert.to_undirected(graph)
    nodes = [[int(n), round(d["y"], 7), round(d["x"], 7)] for n, d in graph.nodes(data=True)]
    edges = {}
    for u, v, d in graph.edges(data=True):
        key = (min(u, v), max(u, v))
        edges[key] = min(edges.get(key, math.inf), float(d["length"]))
    (OUT / "walk_graph.json").write_text(json.dumps(
        {"nodes": nodes, "edges": [[int(u), int(v), round(w, 1)] for (u, v), w in edges.items()]}))
    print("walk graph", len(nodes), "nodes", len(edges), "edges")

    # 3. Designated emergency evacuation sites per hazard type (GSI vector tiles)
    x0, y0 = tile_xy(north, west, SHELTER_Z)
    x1, y1 = tile_xy(south, east, SHELTER_Z)
    sites: dict[tuple, dict] = {}
    for n in range(1, 9):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                body = get(SHELTER_URL.format(n=n, z=SHELTER_Z, x=x, y=y))
                if not body:
                    continue
                for f in json.loads(body)["features"]:
                    lon, lat = f["geometry"]["coordinates"][:2]
                    p = f["properties"]
                    if not any(point_in_polygon(lon, lat, r) for r in rings):
                        continue
                    key = (p["name"], round(lat, 6), round(lon, 6))
                    site = sites.setdefault(key, {"name": p["name"], "address": p.get("address") or "",
                                                  "lat": lat, "lon": lon, "hazards": []})
                    flags = sorted(int(k[8:]) for k, v in p.items() if k.startswith("disaster") and v == 1)
                    site["hazards"] = sorted(set(site["hazards"]) | set(flags))
    shelter_list = sorted(sites.values(), key=lambda s: (s["name"], s["lat"]))
    (OUT / "shelters.json").write_text(json.dumps(shelter_list, ensure_ascii=False, indent=0))
    counts = {h: sum(h in s["hazards"] for s in shelter_list) for h in range(1, 9)}
    print("shelters", len(shelter_list), counts)

    # 4. Inundation depth tiles (Hazard Map Portal)
    x0, y0 = tile_xy(north, west, HAZARD_Z)
    x1, y1 = tile_xy(south, east, HAZARD_Z)
    tile_counts = {}
    for layer in HAZARD_LAYERS:
        saved = 0
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                body = get(HAZARD_URL.format(layer=layer, z=HAZARD_Z, x=x, y=y))
                if body:
                    path = DATA / "hazard" / layer / str(HAZARD_Z) / str(x) / f"{y}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                    saved += 1
        tile_counts[layer] = saved
    print("hazard tiles", tile_counts)

    (OUT / "meta.json").write_text(json.dumps({
        "fetched_at": fetched_at,
        "id": cfg.id,
        "name": cfg.name,
        "place": cfg.place,
        "bounds": [west, south, east, north],
        "shelter_counts_by_hazard": counts,
        "hazard_tiles": tile_counts,
        "walk_graph": {"nodes": len(nodes), "edges": len(edges)},
        "sources": {
            "shelters": "国土地理院 指定緊急避難場所データ（地理院タイル skhb01-08） https://www.gsi.go.jp/bousaichiri/hinanbasho.html",
            "hazard": "ハザードマップポータルサイト（洪水・高潮・津波 浸水想定） https://disaportal.gsi.go.jp/hazardmapportal/hazardmap/copyright/opendata.html",
            "osm": "© OpenStreetMap contributors (ODbL) https://www.openstreetmap.org/copyright",
        },
    }, ensure_ascii=False, indent=2))


def main() -> int:
    ids = sys.argv[1:] or [a.id for a in AREAS]
    for area_id in ids:
        fetch_area(BY_ID[area_id])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
