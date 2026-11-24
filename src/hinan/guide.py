"""Deterministic evacuation guide: depth at the point, hazard-matched sites, walking routes, contacts."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .areas import AREAS, COMMON_CONTACTS
from .data import Dataset, area_of, haversine_m
from .hazard import EARTHQUAKE_FLAG, LAYERS, Depth, depth_at

HAZARD_CHOICES = {
    "tsunami": ("津波", LAYERS["tsunami"].shelter_flag),
    "storm_surge": ("高潮", LAYERS["storm_surge"].shelter_flag),
    "flood": ("洪水", LAYERS["flood"].shelter_flag),
    "earthquake": ("地震", EARTHQUAKE_FLAG),
}
WALK_SPEED_MPS = 1.0  # planning assumption shown on screen; real speed varies by person and conditions
TOP_N = 3

@dataclass
class Candidate:
    rank: int
    name: str
    address: str
    lat: float
    lon: float
    distance_m: int
    minutes: int
    route: list[tuple[float, float]]


@dataclass
class GuideResult:
    status: str  # "ok" | "out_of_area"
    area_id: str
    area_name: str
    hazard: str
    hazard_label: str
    lat: float
    lon: float
    depths: dict[str, dict] = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)
    message: str = ""
    contacts: tuple[dict, ...] = COMMON_CONTACTS
    fetched_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def guide(datasets: tuple[Dataset, ...], lat: float, lon: float, hazard: str) -> GuideResult:
    if hazard not in HAZARD_CHOICES:
        raise ValueError(f"unknown hazard: {hazard!r}")
    label, flag = HAZARD_CHOICES[hazard]
    ds = area_of(datasets, lat, lon)
    if ds is None:
        names = "・".join(a.name for a in AREAS)
        return GuideResult("out_of_area", "", "", hazard, label, lat, lon,
                           message=f"この試作は{names}のデータだけを持っています。対象地域内の地点を選んでください。")
    result = GuideResult("ok", ds.config.id, ds.config.name, hazard, label, lat, lon,
                         contacts=(*COMMON_CONTACTS, ds.config.office), fetched_at=ds.meta.get("fetched_at", ""))

    for key, layer in LAYERS.items():
        d: Depth = depth_at(lat, lon, layer)
        result.depths[key] = {"layer": layer.label, "status": d.status, "depth_label": d.label,
                              "min_m": d.min_m, "max_m": d.max_m}

    matching = [s for s in ds.shelters if flag in s.hazards]
    if not matching:
        result.message = (f"{label}に対応する指定緊急避難場所は、取得したデータ（{ds.config.name}）にはありません。"
                          "近くの頑丈な建物の上の階など、その時点で最も安全な場所を自分で判断してください。")
        return result

    origin, snap_m = ds.graph.nearest(lat, lon)
    dist, prev = ds.graph.dijkstra(origin)
    scored = []
    for s in matching:
        node, gap_m = ds.graph.nearest(s.lat, s.lon)
        if node not in dist:  # not connected on foot (e.g. another island)
            continue
        total = snap_m + dist[node] + gap_m
        scored.append((total, s.name, s, node))
    scored.sort(key=lambda t: (t[0], t[1]))
    for rank, (total, _, s, node) in enumerate(scored[:TOP_N], start=1):
        route = [(lat, lon), *ds.graph.path(prev, origin, node), (s.lat, s.lon)]
        result.candidates.append(Candidate(rank, s.name, s.address, s.lat, s.lon, round(total),
                                           math.ceil(total / WALK_SPEED_MPS / 60), route))
    if not result.candidates:
        result.message = (f"{label}に対応する避難場所へ、歩いて行ける経路がデータ上見つかりませんでした。"
                          "近くの頑丈な建物の上の階など、その時点で最も安全な場所を自分で判断してください。")
    return result


def straight_line_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_m(a[0], a[1], b[0], b[1])
