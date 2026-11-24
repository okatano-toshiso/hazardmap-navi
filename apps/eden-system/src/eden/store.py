"""SQLite store and the deterministic rules: distance, visibility, expiry."""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

WRITE_RADIUS_M = 50.0     # you can only post where you are
CAMERA_RADIUS_M = 200.0   # comments floating in the camera view
PRIVATE_TTL_S = 24 * 3600  # private notes (meeting points) disappear after a day
MAX_TEXT = 140

DEMO_USERS = (("aoi", "あおい"), ("yuto", "ゆうと"), ("sakura", "さくら"))
DEMO_FRIENDS = (("aoi", "yuto"),)  # sakura is nobody's friend in the demo
DEMO_CENTER = (35.68123, 139.76712)  # Tokyo Station, Marunouchi side

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS friends (a TEXT NOT NULL, b TEXT NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS anchors (
  id INTEGER PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL, label TEXT NOT NULL, description TEXT NOT NULL,
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY, author TEXT NOT NULL REFERENCES users(id), lat REAL NOT NULL, lon REAL NOT NULL,
  anchor_id INTEGER REFERENCES anchors(id), text TEXT NOT NULL, visibility TEXT NOT NULL CHECK (visibility IN ('public','private')),
  created_at REAL NOT NULL, expires_at REAL);
"""


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


class RuleError(ValueError):
    """A deterministic rule was not met (shown to the user as is)."""


@dataclass
class Store:
    path: Path | str
    now: callable = time.time

    def __post_init__(self) -> None:
        if str(self.path) != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if not self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            self.db.executemany("INSERT INTO users VALUES (?, ?)", DEMO_USERS)
            self.db.executemany("INSERT INTO friends VALUES (?, ?)", [*DEMO_FRIENDS, *[(b, a) for a, b in DEMO_FRIENDS]])
            self.db.commit()

    # ---- users ------------------------------------------------------------------------------
    def users(self) -> list[dict]:
        rows = self.db.execute("SELECT id, name FROM users ORDER BY rowid").fetchall()
        return [{"id": r["id"], "name": r["name"], "friends": self.friends_of(r["id"])} for r in rows]

    def user_exists(self, user: str) -> bool:
        return self.db.execute("SELECT 1 FROM users WHERE id = ?", (user,)).fetchone() is not None

    def friends_of(self, user: str) -> list[str]:
        return [r["b"] for r in self.db.execute("SELECT b FROM friends WHERE a = ? ORDER BY b", (user,))]

    # ---- anchors (AI-recognised objects) -----------------------------------------------------
    def anchors_near(self, lat: float, lon: float, radius: float = CAMERA_RADIUS_M) -> list[dict]:
        rows = self.db.execute("SELECT * FROM anchors").fetchall()
        return [dict(r) for r in rows if distance_m(lat, lon, r["lat"], r["lon"]) <= radius]

    def add_anchor(self, lat: float, lon: float, label: str, description: str) -> int:
        cur = self.db.execute("INSERT INTO anchors (lat, lon, label, description, created_at) VALUES (?, ?, ?, ?, ?)",
                              (lat, lon, label[:60], description[:200], self.now()))
        self.db.commit()
        return int(cur.lastrowid)

    def anchor(self, anchor_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM anchors WHERE id = ?", (anchor_id,)).fetchone()
        return dict(row) if row else None

    # ---- comments -----------------------------------------------------------------------------
    def can_see(self, viewer: str, row) -> bool:
        if row["expires_at"] is not None and row["expires_at"] <= self.now():
            return False
        if row["visibility"] == "public" or row["author"] == viewer:
            return True
        return row["author"] in self.friends_of(viewer)

    def visible_comments(self, viewer: str, lat: float, lon: float, radius: float, anchor_id: int | None = None) -> list[dict]:
        rows = self.db.execute(
            "SELECT c.*, u.name AS author_name, a.label AS anchor_label FROM comments c JOIN users u ON u.id = c.author "
            "LEFT JOIN anchors a ON a.id = c.anchor_id ORDER BY c.created_at DESC").fetchall()
        out = []
        for r in rows:
            if anchor_id is not None and r["anchor_id"] != anchor_id:
                continue
            d = distance_m(lat, lon, r["lat"], r["lon"])
            if d > radius or not self.can_see(viewer, r):
                continue
            out.append({"id": r["id"], "author": r["author"], "author_name": r["author_name"], "text": r["text"],
                        "visibility": r["visibility"], "lat": r["lat"], "lon": r["lon"], "anchor_id": r["anchor_id"],
                        "anchor_label": r["anchor_label"], "distance_m": round(d), "bearing": round(bearing_deg(lat, lon, r["lat"], r["lon"])),
                        "created_at": r["created_at"], "expires_at": r["expires_at"]})
        return out

    def add_comment(self, author: str, here_lat: float, here_lon: float, text: str, visibility: str,
                    anchor_id: int | None = None) -> int:
        text = text.strip()
        if not self.user_exists(author):
            raise RuleError("利用者が不正です。")
        if visibility not in ("public", "private"):
            raise RuleError("公開範囲が不正です。")
        if not text or len(text) > MAX_TEXT:
            raise RuleError(f"コメントは1〜{MAX_TEXT}文字で入力してください。")
        lat, lon = here_lat, here_lon
        if anchor_id is not None:
            a = self.anchor(anchor_id)
            if a is None:
                raise RuleError("結び付ける対象が見つかりません。")
            if distance_m(here_lat, here_lon, a["lat"], a["lon"]) > WRITE_RADIUS_M:
                raise RuleError(f"対象から{int(WRITE_RADIUS_M)}m以内にいるときだけ書き込めます。")
            lat, lon = a["lat"], a["lon"]
        now = self.now()
        expires = now + PRIVATE_TTL_S if visibility == "private" else None
        cur = self.db.execute(
            "INSERT INTO comments (author, lat, lon, anchor_id, text, visibility, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (author, lat, lon, anchor_id, text, visibility, now, expires))
        self.db.commit()
        return int(cur.lastrowid)

    def delete_comment(self, user: str, comment_id: int) -> None:
        """Only the author may delete. The comment is removed from the database, not just hidden."""
        row = self.db.execute("SELECT author FROM comments WHERE id = ?", (comment_id,)).fetchone()
        if row is None:
            raise RuleError("コメントが見つかりません。")
        if row["author"] != user:
            raise RuleError("自分のコメントだけ削除できます。")
        self.db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        self.db.commit()
