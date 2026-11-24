"""EDEN SYSTEM web app: one screen with map, camera view and comment form."""

from __future__ import annotations

import hmac
import logging
import math
import os
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, session

from .store import CAMERA_RADIUS_M, DEMO_CENTER, MAX_TEXT, WRITE_RADIUS_M, RuleError, Store
from .vision import ClaudeVision, MockVision, Vision, VisionError, prepare_photo

log = logging.getLogger("eden")
DEFAULT_PORT = 8766
APP_ROOT = Path(__file__).resolve().parents[2]
PENDING_TTL_S = 600
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; "
       "img-src 'self' data: blob: https://cyberjapandata.gsi.go.jp; frame-ancestors 'none'; base-uri 'none'")


def vision_from_env(provider: str) -> Vision:
    if provider == "mock":
        return MockVision()
    if provider == "claude":
        return ClaudeVision()
    raise ValueError(f"unknown EDEN_AI_PROVIDER: {provider!r} (use 'mock' or 'claude')")


def _coord(value, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        abort(400, "位置が不正です。")
    if not (math.isfinite(v) and lo <= v <= hi):
        abort(400, "位置が不正です。")
    return v


def create_app(vision: Vision | None = None, store: Store | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_bytes(32), MAX_CONTENT_LENGTH=9 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    the_vision = vision or vision_from_env(os.environ.get("EDEN_AI_PROVIDER", "mock"))
    db = store or Store(APP_ROOT / "instance" / "eden.db")
    pending: dict[str, dict] = {}  # recognition results waiting for a comment, kept on the server
    lock = threading.Lock()

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    @app.before_request
    def check_csrf() -> None:
        if request.method == "POST":
            sent = request.headers.get("X-CSRF-Token", "")
            if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
                abort(403, "CSRFトークンが一致しません。ページを再読み込みしてください。")

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=(self), microphone=()"
        return response

    @app.errorhandler(400)
    @app.errorhandler(403)
    def bad(err):
        return jsonify(error=getattr(err, "description", "不正なリクエストです。")), err.code

    @app.errorhandler(413)
    def too_large(_err):
        return jsonify(error="写真が大きすぎます。もう一度選び直すか、別の写真を使ってください。"), 413

    def user_arg(value) -> str:
        user = str(value or "")
        if not db.user_exists(user):
            abort(400, "利用者が不正です。")
        return user

    @app.get("/")
    def index():
        cfg = {"users": db.users(), "center": DEMO_CENTER, "writeRadius": WRITE_RADIUS_M, "cameraRadius": CAMERA_RADIUS_M,
               "maxText": MAX_TEXT, "external": the_vision.external, "model": getattr(the_vision, "model", "")}
        return render_template("index.html", csrf=csrf_token(), cfg=cfg, vision=the_vision)

    @app.get("/api/comments")
    def comments():
        user = user_arg(request.args.get("user"))
        lat, lon = _coord(request.args.get("lat"), -90, 90), _coord(request.args.get("lon"), -180, 180)
        radius = min(_coord(request.args.get("radius", CAMERA_RADIUS_M), 1, 5000), 5000)
        return jsonify(db.visible_comments(user, lat, lon, radius))

    @app.post("/api/recognize")
    def recognize():
        user = user_arg(request.form.get("user"))
        lat, lon = _coord(request.form.get("lat"), -90, 90), _coord(request.form.get("lon"), -180, 180)
        if the_vision.external and request.form.get("consent") != "yes":
            return jsonify(error="外部AIへ写真を送ることに同意したときだけ認識します。"), 400
        photo = request.files.get("photo")
        if photo is None:
            abort(400, "写真がありません。")
        started = time.monotonic()
        try:
            jpeg = prepare_photo(photo.read())
            candidates = db.anchors_near(lat, lon)
            rec = the_vision.recognize(jpeg, candidates)
        except VisionError as exc:
            return jsonify(error=str(exc)), 502
        log.info("recognize provider=%s person=%s matched=%s ms=%d", the_vision.name, rec.main_subject_is_person,
                 rec.match_id is not None, (time.monotonic() - started) * 1000)  # no photo, label or location logged
        if rec.main_subject_is_person:
            return jsonify(person=True, message="人物が主に写っているため、コメントは結び付けません。建物・看板・モノを撮ってください。")
        matched = next((c for c in candidates if c["id"] == rec.match_id), None)
        token = secrets.token_urlsafe(16)
        with lock:
            now = time.time()
            for k in [k for k, v in pending.items() if v["at"] < now - PENDING_TTL_S]:
                pending.pop(k)
            pending[token] = {"user": user, "lat": lat, "lon": lon, "label": rec.label, "description": rec.description,
                              "anchor_id": matched["id"] if matched else None, "at": now}
        attached = db.visible_comments(user, lat, lon, 5000, anchor_id=matched["id"]) if matched else []
        return jsonify(person=False, token=token, label=rec.label, description=rec.description,
                       matched=({"id": matched["id"], "label": matched["label"]} if matched else None), comments=attached)

    @app.post("/api/comments")
    def post_comment():
        body = request.get_json(silent=True) or {}
        user = user_arg(body.get("user"))
        lat, lon = _coord(body.get("lat"), -90, 90), _coord(body.get("lon"), -180, 180)
        visibility, text = str(body.get("visibility", "")), str(body.get("text", ""))
        token = body.get("token")
        rec = None
        if token:
            with lock:
                rec = pending.get(str(token))
            if rec is None or rec["user"] != user:
                abort(400, "写真の認識結果が見つかりません。もう一度撮ってください。")
        if visibility == "public" and text.strip():
            try:
                verdict = the_vision.moderate(text.strip())
            except VisionError as exc:
                return jsonify(error=str(exc)), 502
            if not verdict.allowed:
                return jsonify(error="公開できない内容です：" + verdict.reason), 400
        try:
            anchor_id = None
            if rec is not None:
                anchor_id = rec["anchor_id"]
                if anchor_id is None:
                    from .store import distance_m
                    if distance_m(lat, lon, rec["lat"], rec["lon"]) > WRITE_RADIUS_M:
                        raise RuleError(f"撮影した場所から{int(WRITE_RADIUS_M)}m以内でだけ書き込めます。")
                    anchor_id = db.add_anchor(rec["lat"], rec["lon"], rec["label"], rec["description"])
                    rec["anchor_id"] = anchor_id
            comment_id = db.add_comment(user, lat, lon, text, visibility, anchor_id)
        except RuleError as exc:
            return jsonify(error=str(exc)), 400
        log.info("comment visibility=%s anchored=%s", visibility, anchor_id is not None)
        return jsonify(id=comment_id, anchor_id=anchor_id)

    @app.post("/api/comments/<int:comment_id>/delete")
    def delete_comment(comment_id: int):
        body = request.get_json(silent=True) or {}
        user = user_arg(body.get("user"))
        try:
            db.delete_comment(user, comment_id)
        except RuleError as exc:
            return jsonify(error=str(exc)), 400
        log.info("comment deleted")
        return jsonify(deleted=comment_id)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        app = create_app()
    except ValueError as exc:
        raise SystemExit(f"設定エラー: {exc}") from None
    app.run(host="127.0.0.1", port=int(os.environ.get("EDEN_PORT", DEFAULT_PORT)), debug=False)
