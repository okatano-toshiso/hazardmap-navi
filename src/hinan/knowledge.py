"""Grounding cards for the AI advisor, quoted from official pages checked on 2026-11-24.

Retrieval is deliberately simple and auditable: cards are selected by hazard and situation tags,
so every sentence the AI may lean on has a known official source.
"""

from __future__ import annotations

from dataclasses import dataclass

JMA_TSUNAMI = "https://www.jma.go.jp/jma/kishou/know/jishin/tsunami_bosai/index.html"
JMA_ALERT = "https://www.jma.go.jp/jma/kishou/know/bosai/alertlevel.html"
BOUSAI_GUIDELINE = "https://www.bousai.go.jp/oukyu/hinanjouhou/r3_hinanjouhou_guideline/"


@dataclass(frozen=True)
class Card:
    id: str
    text: str
    source: str
    url: str
    tags: frozenset[str]


CARDS: tuple[Card, ...] = (
    Card("jma-tsunami-move",
         "津波警報・注意報を見聞きしたり、海辺で強い揺れを感じたり、長くゆっくりした揺れを感じたりしたら、"
         "海辺から離れ、より高い安全な場所へ避難しましょう。",
         "気象庁「津波から身を守るために」", JMA_TSUNAMI, frozenset({"tsunami", "earthquake"})),
    Card("jma-tsunami-stay", "津波警報が出ている間は、絶対に戻ってはいけません。",
         "気象庁「津波から身を守るために」", JMA_TSUNAMI, frozenset({"tsunami"})),
    Card("jma-tsunami-early", "見てから逃げるのでは間に合いません。",
         "気象庁「津波から身を守るために」", JMA_TSUNAMI, frozenset({"tsunami"})),
    Card("jma-alert-act",
         "自治体から警戒レベル４避難指示や警戒レベル３高齢者等避難が発令された際には速やかに避難行動をとってください。",
         "気象庁「防災気象情報と警戒レベルとの対応について」", JMA_ALERT, frozenset({"flood", "storm_surge"})),
    Card("jma-alert-upper",
         "避難にあたっては、あらかじめ指定された避難場所へ向かうことにこだわらず、川や崖から少しでも離れた、"
         "近くの頑丈な建物の上層階に避難するなど、自らの判断でその時点で最善の安全確保行動をとることが重要です。",
         "気象庁「防災気象情報と警戒レベルとの対応について」", JMA_ALERT,
         frozenset({"flood", "storm_surge", "no_site", "deep"})),
    Card("jma-alert-level5", "（警戒レベル５相当）命の危険が迫っているため直ちに身の安全を確保してください。",
         "気象庁「防災気象情報と警戒レベルとの対応について」", JMA_ALERT, frozenset({"flood", "storm_surge", "deep"})),
    Card("bousai-kinds",
         "避難には、指定緊急避難場所・小中学校・公民館・親戚や知人宅・ホテルなどへの「立退き避難」と、"
         "上の階へ移動する・上の階に留まる「屋内安全確保」がある。",
         "防災庁「避難情報に関するガイドライン」（図の区分を要約）", BOUSAI_GUIDELINE,
         frozenset({"flood", "storm_surge", "no_site", "deep"})),
)


def select(hazard: str, deep: bool, no_site: bool, limit: int = 4) -> list[Card]:
    wanted = {hazard} | ({"deep"} if deep else set()) | ({"no_site"} if no_site else set())
    scored = sorted(CARDS, key=lambda c: (-len(c.tags & wanted), CARDS.index(c)))
    return [c for c in scored if c.tags & wanted][:limit]
