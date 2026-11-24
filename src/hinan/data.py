"""Load the pre-fetched open data (see scripts/fetch_data.py) and answer geometric questions about it."""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .areas import AREAS, BY_ID, AreaConfig

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_in_rings(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    """Even-odd rule over all rings (outer rings and holes)."""
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


@dataclass(frozen=True)
class Shelter:
    name: str
    address: str
    lat: float
    lon: float
    hazards: tuple[int, ...]


class Area:
    def __init__(self, feature: dict) -> None:
        geom = feature["geometry"]
        polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        self.rings = [ring for polygon in polygons for ring in polygon]
        self.feature = feature

    def contains(self, lat: float, lon: float) -> bool:
        return point_in_rings(lon, lat, self.rings)


class WalkGraph:
    """Undirected walking network from OpenStreetMap; shortest paths by Dijkstra (lengths in metres)."""

    def __init__(self, nodes: list[list[float]], edges: list[list[float]]) -> None:
        self.coord = {int(n): (lat, lon) for n, lat, lon in nodes}
        self.adj: dict[int, list[tuple[int, float]]] = {n: [] for n in self.coord}
        for u, v, w in edges:
            self.adj[int(u)].append((int(v), float(w)))
            self.adj[int(v)].append((int(u), float(w)))

    def nearest(self, lat: float, lon: float) -> tuple[int, float]:
        node = min(self.coord, key=lambda n: (self.coord[n][0] - lat) ** 2 + ((self.coord[n][1] - lon) * 0.82) ** 2)
        return node, haversine_m(lat, lon, *self.coord[node])

    def dijkstra(self, source: int) -> tuple[dict[int, float], dict[int, int]]:
        dist, prev = {source: 0.0}, {}
        heap = [(0.0, source)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            for v, w in self.adj[u]:
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(heap, (nd, v))
        return dist, prev

    def path(self, prev: dict[int, int], source: int, target: int) -> list[tuple[float, float]]:
        nodes = [target]
        while nodes[-1] != source:
            nodes.append(prev[nodes[-1]])
        return [self.coord[n] for n in reversed(nodes)]


@dataclass(frozen=True)
class Dataset:
    config: AreaConfig
    area: Area
    shelters: tuple[Shelter, ...]
    graph: WalkGraph
    meta: dict


@lru_cache(maxsize=None)
def load(area_id: str) -> Dataset:
    data_dir = DATA_DIR / "areas" / area_id
    area = Area(json.loads((data_dir / "area.geojson").read_text(encoding="utf-8")))
    shelters = tuple(
        Shelter(s["name"], s["address"], s["lat"], s["lon"], tuple(s["hazards"]))
        for s in json.loads((data_dir / "shelters.json").read_text(encoding="utf-8"))
    )
    graph_data = json.loads((data_dir / "walk_graph.json").read_text(encoding="utf-8"))
    graph = WalkGraph(graph_data["nodes"], graph_data["edges"])
    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
    return Dataset(BY_ID[area_id], area, shelters, graph, meta)


def load_all() -> tuple[Dataset, ...]:
    return tuple(load(a.id) for a in AREAS)


def area_of(datasets: tuple[Dataset, ...], lat: float, lon: float) -> Dataset | None:
    return next((ds for ds in datasets if ds.area.contains(lat, lon)), None)
