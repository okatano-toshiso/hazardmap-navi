"""EDEN SYSTEM: distance, visibility, expiry, moderation, photo handling, person rule, re-recognition."""

import io
import json
import re
import subprocess

import pytest
from PIL import Image

from eden.store import DEMO_CENTER, PRIVATE_TTL_S, RuleError, Store
from eden.vision import ClaudeVision, MockVision, Recognition, prepare_photo
from eden.web import create_app

LAT, LON = DEMO_CENTER
FAR_LAT = LAT + 0.001  # ~111 m north


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def photo(color=(200, 30, 30), gps=False) -> bytes:
    im = Image.new("RGB", (64, 48), color)
    buf = io.BytesIO()
    if gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (35.0, 41.0, 0.0)}
        im.save(buf, format="JPEG", exif=exif)
    else:
        im.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def store():
    return Store(":memory:", now=Clock())


# ---- store rules -----------------------------------------------------------------------------
def test_private_is_seen_by_author_and_friends_only(store):
    store.add_comment("aoi", LAT, LON, "ちょっと離れてる。待ってて", "private")
    assert [c["text"] for c in store.visible_comments("aoi", LAT, LON, 200)] == ["ちょっと離れてる。待ってて"]
    assert len(store.visible_comments("yuto", LAT, LON, 200)) == 1   # friend
    assert store.visible_comments("sakura", LAT, LON, 200) == []     # not a friend


def test_public_is_seen_by_everyone(store):
    store.add_comment("sakura", LAT, LON, "この先のラーメン屋はおいしい！", "public")
    assert all(len(store.visible_comments(u, LAT, LON, 200)) == 1 for u in ("aoi", "yuto", "sakura"))


def test_private_expires_after_24_hours(store):
    store.add_comment("aoi", LAT, LON, "待ってて", "private")
    store.now.t += PRIVATE_TTL_S - 1
    assert store.visible_comments("yuto", LAT, LON, 200)
    store.now.t += 2
    assert store.visible_comments("yuto", LAT, LON, 200) == []


def test_cannot_write_to_an_object_more_than_50m_away(store):
    anchor = store.add_anchor(LAT, LON, "赤い看板のラーメン店", "説明")
    with pytest.raises(RuleError):
        store.add_comment("aoi", FAR_LAT, LON, "おいしい", "public", anchor)
    store.add_comment("aoi", LAT + 0.0003, LON, "おいしい", "public", anchor)  # ~33 m


def test_comments_outside_the_radius_are_not_returned(store):
    store.add_comment("aoi", LAT, LON, "ここ", "public")
    assert store.visible_comments("aoi", LAT + 0.01, LON, 200) == []  # ~1.1 km away


@pytest.mark.parametrize("text, vis", [("", "public"), ("あ" * 141, "public"), ("ok", "secret")])
def test_invalid_comment_is_rejected(store, text, vis):
    with pytest.raises(RuleError):
        store.add_comment("aoi", LAT, LON, text, vis)


# ---- photo handling ------------------------------------------------------------------------------
def test_photo_metadata_is_removed_before_ai():
    clean = prepare_photo(photo(gps=True))
    with Image.open(io.BytesIO(clean)) as im:
        assert not im.getexif()


def test_mock_recognition_is_deterministic_and_matches_same_label():
    v = MockVision()
    first = v.recognize(prepare_photo(photo()), [])
    again = v.recognize(prepare_photo(photo()), [{"id": 7, "label": first.label, "description": ""}])
    assert first.label == again.label and again.match_id == 7


def test_claude_recognition_reads_only_the_photo_folder():
    seen = {}

    def runner(args, **kw):
        seen["args"], seen["kw"] = args, kw
        out = {"structured_output": {"label": "看板", "description": "d", "main_subject_is_person": False, "match_id": None}}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(out), stderr="")

    ClaudeVision(runner=runner).recognize(prepare_photo(photo()), [])
    args = seen["args"]
    assert args[args.index("--tools") + 1] == "Read" and args[args.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in args and seen["kw"]["cwd"] in args[2]
    assert "人物は認識の対象にしません" in args[args.index("--system-prompt") + 1]


# ---- web ----------------------------------------------------------------------------------------------
class PersonVision(MockVision):
    external = True

    def recognize(self, jpeg, candidates):
        return Recognition(label="", description="", main_subject_is_person=True, match_id=None)


def client_for(vision=None):
    app = create_app(vision or MockVision(), Store(":memory:", now=Clock()))
    app.testing = True
    c = app.test_client()
    token = re.search(r'data-csrf="([^"]+)"', c.get("/").get_data(as_text=True)).group(1)
    return c, token


def recognize(c, token, user="aoi", lat=LAT, lon=LON, consent="yes", data=None):
    form = {"user": user, "lat": str(lat), "lon": str(lon), "consent": consent,
            "photo": (io.BytesIO(data or photo()), "p.jpg")}
    return c.post("/api/recognize", data=form, headers={"X-CSRF-Token": token}, content_type="multipart/form-data")


def post(c, csrf, **body):
    return c.post("/api/comments", json=body, headers={"X-CSRF-Token": csrf})


def test_csrf_and_security_headers():
    c, token = client_for()
    assert "script-src 'self'" in c.get("/").headers["Content-Security-Policy"]
    assert c.post("/api/comments", json={}).status_code == 403


def test_external_ai_needs_consent():
    class Ext(MockVision):
        external = True
    c, token = client_for(Ext())
    assert recognize(c, token, consent="no").status_code == 400


def test_person_photo_is_not_anchored():
    c, token = client_for(PersonVision())
    body = recognize(c, token).get_json()
    assert body["person"] is True and "token" not in body


def test_recognise_post_and_find_again_with_the_same_object():
    c, token = client_for()
    first = recognize(c, token).get_json()
    assert first["matched"] is None
    res = post(c, token, user="aoi", lat=LAT, lon=LON, text="この先のラーメン屋はおいしい！", visibility="public", token=first["token"])
    assert res.status_code == 200 and res.get_json()["anchor_id"]
    again = recognize(c, token, user="sakura", lat=LAT + 0.0002, lon=LON).get_json()  # another user, ~22 m away
    assert again["matched"]["id"] == res.get_json()["anchor_id"]
    assert [x["text"] for x in again["comments"]] == ["この先のラーメン屋はおいしい！"]


def test_recognition_token_belongs_to_its_user():
    c, token = client_for()
    t = recognize(c, token, user="aoi").get_json()["token"]
    assert post(c, token, user="sakura", lat=LAT, lon=LON, text="x", visibility="public", token=t).status_code == 400


def test_public_text_must_pass_moderation():
    c, token = client_for()
    res = post(c, token, user="aoi", lat=LAT, lon=LON, text="店員の電話は090-1234-5678", visibility="public")
    assert res.status_code == 400 and "公開できない" in res.get_json()["error"]
    assert post(c, token, user="aoi", lat=LAT, lon=LON, text="景色がきれい", visibility="public").status_code == 200


def test_friend_only_visibility_through_the_api():
    c, token = client_for()
    assert post(c, token, user="aoi", lat=LAT, lon=LON, text="改札の前にいるね", visibility="private").status_code == 200
    seen = {u: c.get(f"/api/comments?user={u}&lat={LAT}&lon={LON}").get_json() for u in ("aoi", "yuto", "sakura")}
    assert len(seen["aoi"]) == 1 and len(seen["yuto"]) == 1 and seen["sakura"] == []
    assert {"bearing", "distance_m"} <= set(seen["yuto"][0])


def test_oversized_upload_gets_a_json_error():
    c, token = client_for()
    big = b"\xff\xd8" + b"0" * (10 * 1024 * 1024)
    res = recognize(c, token, data=big)
    assert res.status_code == 413 and "大きすぎます" in res.get_json()["error"]


# ---- deleting your own comment -----------------------------------------------------------------------
def test_author_can_delete_own_comment_and_others_cannot(store):
    cid = store.add_comment("aoi", LAT, LON, "待ってて", "private")
    with pytest.raises(RuleError):
        store.delete_comment("yuto", cid)          # a friend can see it but cannot delete it
    assert store.visible_comments("yuto", LAT, LON, 200)
    store.delete_comment("aoi", cid)
    assert store.visible_comments("aoi", LAT, LON, 200) == []
    with pytest.raises(RuleError):
        store.delete_comment("aoi", cid)           # already gone


def test_delete_through_the_api_requires_csrf_and_ownership():
    c, token = client_for()
    cid = post(c, token, user="sakura", lat=LAT, lon=LON, text="景色がきれい", visibility="public").get_json()["id"]
    assert c.post(f"/api/comments/{cid}/delete", json={"user": "sakura"}).status_code == 403          # no CSRF token
    assert c.post(f"/api/comments/{cid}/delete", json={"user": "aoi"}, headers={"X-CSRF-Token": token}).status_code == 400
    assert c.post(f"/api/comments/{cid}/delete", json={"user": "sakura"}, headers={"X-CSRF-Token": token}).status_code == 200
    assert c.get(f"/api/comments?user=sakura&lat={LAT}&lon={LON}").get_json() == []
