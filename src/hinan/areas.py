"""Supported areas. Each has its own boundary, evacuation sites and walking network under data/areas/<id>/."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AreaConfig:
    id: str
    name: str
    place: str  # Nominatim query used by scripts/fetch_data.py
    office: dict  # verified on the official site on 2026-11-24


AREAS: tuple[AreaConfig, ...] = (
    AreaConfig("konohana", "大阪市此花区", "此花区, 大阪市, 大阪府, 日本",
               {"name": "此花区役所（代表）", "phone": "06-6466-9986", "note": "大阪市此花区春日出北1-8-4",
                "source": "https://www.city.osaka.lg.jp/konohana/"}),
    AreaConfig("yashio", "埼玉県八潮市", "八潮市, 埼玉県, 日本",
               {"name": "八潮市役所（代表）", "phone": "048-996-2111", "note": "埼玉県八潮市中央一丁目2番地1（危機管理防災課も同番号）",
                "source": "https://www.city.yashio.lg.jp/"}),
    AreaConfig("misato", "埼玉県三郷市", "三郷市, 埼玉県, 日本",
               {"name": "三郷市役所（代表）", "phone": "048-953-1111", "note": "埼玉県三郷市花和田648番地1",
                "source": "https://www.city.misato.lg.jp/"}),
)
BY_ID = {a.id: a for a in AREAS}

COMMON_CONTACTS = (
    {"name": "消防・救急", "phone": "119", "note": "火事・けが・急病", "source": ""},
    {"name": "警察", "phone": "110", "note": "事件・事故", "source": ""},
    {"name": "災害用伝言ダイヤル", "phone": "171", "note": "録音は171→1、再生は171→2（NTT東日本・西日本）",
     "source": "https://www.ntt-west.co.jp/dengon/"},
)
