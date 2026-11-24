"""Deterministic core: depth legend, hazard-matched sites, area check, routing."""

import pytest

from hinan.data import WalkGraph, load_all, point_in_rings
from hinan.guide import HAZARD_CHOICES, guide
from hinan.hazard import LAYERS, LEGEND, classify, depth_at

NISHIKUJO = (34.68241, 135.4705)
SHIMAYA = (34.674039, 135.443735)
UMEDA = (34.7025, 135.4959)  # Osaka Kita-ku, outside every supported area
YASHIO = (35.82435, 139.8367)
MISATO = (35.82481, 139.87024)


@pytest.fixture(scope="module")
def ds():
    return load_all()


def test_every_legend_colour_maps_to_a_depth_and_unknown_colours_do_not():
    for rgb, (label, lo, _hi) in LEGEND.items():
        d = classify((*rgb, 255))
        assert d.status == "depth" and d.label == label and d.min_m == lo
    assert classify((0, 0, 0, 0)).status == "none"
    assert classify((1, 2, 3, 255)).status == "unknown"


def test_depth_at_known_points_matches_portal_tiles():
    assert depth_at(*NISHIKUJO, LAYERS["tsunami"]).label == "0.5〜1m"
    assert depth_at(*NISHIKUJO, LAYERS["storm_surge"]).label == "3〜5m"
    assert depth_at(*SHIMAYA, LAYERS["storm_surge"]).label == "5〜10m"


@pytest.mark.parametrize("hazard", ["tsunami", "flood", "earthquake"])
def test_only_sites_designated_for_the_hazard_are_offered(ds, hazard):
    r = guide(ds, *NISHIKUJO, hazard)
    flag = HAZARD_CHOICES[hazard][1]
    by_name = {s.name: s for d in ds for s in d.shelters}
    assert 1 <= len(r.candidates) <= 3
    assert all(flag in by_name[c.name].hazards for c in r.candidates)
    assert [c.distance_m for c in r.candidates] == sorted(c.distance_m for c in r.candidates)


def test_storm_surge_has_no_designated_site_in_the_data_and_says_so(ds):
    konohana = next(d for d in ds if d.config.id == "konohana")
    assert not any(3 in s.hazards for s in konohana.shelters)
    r = guide(ds, *SHIMAYA, "storm_surge")
    assert r.status == "ok" and r.candidates == []
    assert "データ（大阪市此花区）にはありません" in r.message


def test_outside_the_ward_stops_without_routes(ds):
    r = guide(ds, *UMEDA, "tsunami")
    assert r.status == "out_of_area" and r.candidates == [] and r.depths == {}


def test_unknown_hazard_is_rejected(ds):
    with pytest.raises(ValueError):
        guide(ds, *NISHIKUJO, "meteor")


def test_routes_are_deterministic_and_start_and_end_at_the_points(ds):
    a = guide(ds, *NISHIKUJO, "tsunami").to_dict()
    b = guide(ds, *NISHIKUJO, "tsunami").to_dict()
    assert a == b
    first = a["candidates"][0]
    assert tuple(first["route"][0]) == NISHIKUJO
    assert tuple(first["route"][-1]) == (first["lat"], first["lon"])


def test_dijkstra_picks_the_shorter_path():
    g = WalkGraph([[1, 0, 0], [2, 0, 1], [3, 1, 0], [4, 1, 1]], [[1, 2, 10], [2, 4, 10], [1, 3, 1], [3, 4, 1]])
    dist, prev = g.dijkstra(1)
    assert dist[4] == 2
    assert g.path(prev, 1, 4) == [(0, 0), (1, 0), (1, 1)]


def test_point_in_polygon_even_odd():
    square = [[[0, 0], [10, 0], [10, 10], [0, 10]]]
    assert point_in_rings(5, 5, square)
    assert not point_in_rings(15, 5, square)


@pytest.mark.parametrize("point, area_id, phone", [(YASHIO, "yashio", "048-996-2111"), (MISATO, "misato", "048-953-1111"),
                                                   (NISHIKUJO, "konohana", "06-6466-9986")])
def test_point_is_assigned_to_its_area_with_the_right_office(ds, point, area_id, phone):
    r = guide(ds, *point, "flood")
    assert r.status == "ok" and r.area_id == area_id
    assert r.contacts[-1]["phone"] == phone and [c["phone"] for c in r.contacts[:3]] == ["119", "110", "171"]


@pytest.mark.parametrize("point", [YASHIO, MISATO])
def test_saitama_flood_sites_and_depth(ds, point):
    r = guide(ds, *point, "flood")
    flag = HAZARD_CHOICES["flood"][1]
    area = next(d for d in ds if d.config.id == r.area_id)
    names = {s.name: s for s in area.shelters}
    assert r.depths["flood"]["depth_label"] == "0.5〜3m"
    assert len(r.candidates) == 3 and all(flag in names[c.name].hazards for c in r.candidates)


def test_no_tsunami_sites_in_yashio_is_stated(ds):
    r = guide(ds, *YASHIO, "tsunami")
    assert r.candidates == [] and "埼玉県八潮市" in r.message
