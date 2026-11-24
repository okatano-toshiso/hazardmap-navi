"""Read the assumed inundation depth at a point from Hazard Map Portal tiles (deterministic, no AI)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .data import DATA_DIR

ZOOM = 15

# Colour -> depth class, read from the official legend image shinsui_legend3.png
# (https://disaportal.gsi.go.jp/hazardmapportal/hazardmap/copyright/opendata.html), checked 2026-11-24.
LEGEND: dict[tuple[int, int, int], tuple[str, float, float | None]] = {
    (255, 255, 179): ("0.3m未満", 0.0, 0.3),
    (247, 245, 169): ("0.5m未満", 0.0, 0.5),
    (248, 225, 166): ("0.5〜1m", 0.5, 1.0),
    (255, 216, 192): ("0.5〜3m", 0.5, 3.0),
    (255, 183, 183): ("3〜5m", 3.0, 5.0),
    (255, 145, 145): ("5〜10m", 5.0, 10.0),
    (242, 133, 201): ("10〜20m", 10.0, 20.0),
    (220, 122, 220): ("20m以上", 20.0, None),
}


@dataclass(frozen=True)
class HazardLayer:
    key: str
    label: str
    tile_dir: str
    shelter_flag: int  # GSI disasterN flag for designated emergency evacuation sites


LAYERS: dict[str, HazardLayer] = {
    "tsunami": HazardLayer("tsunami", "津波", "04_tsunami_newlegend_data", 5),
    "storm_surge": HazardLayer("storm_surge", "高潮", "03_hightide_l2_shinsuishin_data", 3),
    "flood": HazardLayer("flood", "洪水（想定最大規模）", "01_flood_l2_shinsuishin_data", 1),
}
EARTHQUAKE_FLAG = 4


@dataclass(frozen=True)
class Depth:
    status: str  # "depth" | "none" (no inundation assumed here) | "unknown" (colour not in legend)
    label: str
    min_m: float | None = None
    max_m: float | None = None


def _pixel(lat: float, lon: float) -> tuple[int, int, int, int]:
    n = 2**ZOOM
    fx = (lon + 180) / 360 * n
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int(fx), int(fy), min(255, int((fx % 1) * 256)), min(255, int((fy % 1) * 256))


def classify(rgba: tuple[int, int, int, int]) -> Depth:
    if rgba[3] == 0:
        return Depth("none", "浸水の想定なし")
    hit = LEGEND.get(tuple(rgba[:3]))
    if hit is None:
        return Depth("unknown", "判定できない色")
    label, lo, hi = hit
    return Depth("depth", label, lo, hi)


def depth_at(lat: float, lon: float, layer: HazardLayer, data_dir: Path = DATA_DIR) -> Depth:
    x, y, px, py = _pixel(lat, lon)
    tile = data_dir / "hazard" / layer.tile_dir / str(ZOOM) / str(x) / f"{y}.png"
    if not tile.is_file():  # the portal returns 404 where no inundation is assumed
        return Depth("none", "浸水の想定なし")
    with Image.open(tile) as image:
        return classify(image.convert("RGBA").getpixel((px, py)))
