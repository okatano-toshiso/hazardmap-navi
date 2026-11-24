"""Flask app: one screen (map + guide). Deterministic guide first, AI explanation on demand."""

from __future__ import annotations

import hmac
import logging
import math
import os
import secrets
import time

from flask import Flask, abort, jsonify, render_template, request, send_from_directory, session

from . import advisor as adv
from .areas import COMMON_CONTACTS
from .data import DATA_DIR, Dataset, load_all
from .guide import HAZARD_CHOICES, guide
from .hazard import LAYERS, LEGEND, ZOOM

log = logging.getLogger("hinan")
DEFAULT_PORT = 8765  # 5000 is taken by the macOS AirPlay receiver
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data: https://cyberjapandata.gsi.go.jp; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def advisor_from_env(provider: str) -> adv.Advisor:
    if provider == "mock":
        return adv.MockAdvisor()
    if provider == "claude":
        return adv.ClaudeAdvisor()
    raise ValueError(f"unknown HINAN_AI_PROVIDER: {provider!r} (use 'mock' or 'claude')")


def _point(body: dict) -> tuple[float, float, str]:
    try:
        lat, lon, hazard = float(body["lat"]), float(body["lon"]), str(body["hazard"])
    except (KeyError, TypeError, ValueError):
        abort(400, "lat, lon, hazard が必要です。")
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        abort(400, "座標が不正です。")
    if hazard not in HAZARD_CHOICES:
        abort(400, "災害の種類が不正です。")
    return lat, lon, hazard


def create_app(advisor: adv.Advisor | None = None, datasets: tuple[Dataset, ...] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_bytes(32), MAX_CONTENT_LENGTH=16 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    the_advisor = advisor or advisor_from_env(os.environ.get("HINAN_AI_PROVIDER", "mock"))
    all_ds = datasets or load_all()
    by_id = {ds.config.id: ds for ds in all_ds}
    known_sites = {s.name for ds in all_ds for s in ds.shelters}
    # Rendered into a JSON data block (not executed); the page script reads it.
    ui_config = {
        "areas": [{"id": ds.config.id, "name": ds.config.name, "bounds": ds.meta["bounds"], "office": ds.config.office,
                   "counts": {k: sum(flag in s.hazards for s in ds.shelters) for k, (_l, flag) in HAZARD_CHOICES.items()}}
                  for ds in all_ds],
        "legend": [{"rgb": list(rgb), "label": label} for rgb, (label, _lo, _hi) in reversed(LEGEND.items())],
        "hazardLabels": {k: label for k, (label, _f) in HAZARD_CHOICES.items()},
        "overlayHazards": list(LAYERS),
        "external": the_advisor.external,
    }

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
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
        return response

    @app.errorhandler(400)
    @app.errorhandler(403)
    def bad_request(err):
        return jsonify(error=getattr(err, "description", "不正なリクエストです。")), err.code

    @app.get("/")
    def index():
        first = all_ds[0].meta["bounds"]
        return render_template("index.html", csrf=csrf_token(), advisor=the_advisor, areas=all_ds, ui_config=ui_config,
                               demo_consent=os.environ.get("HINAN_DEMO_CONSENT") == "1",
                               hazards=HAZARD_CHOICES, contacts=COMMON_CONTACTS,
                               center=((first[1] + first[3]) / 2, (first[0] + first[2]) / 2))

    @app.get("/api/area")
    def area():
        return jsonify({"type": "FeatureCollection", "features": [ds.area.feature for ds in all_ds]})

    @app.get("/api/sites")
    def api_sites():
        area_id, hazard = request.args.get("area", ""), request.args.get("hazard", "")
        if area_id not in by_id or hazard not in HAZARD_CHOICES:
            abort(400, "地域または災害の種類が不正です。")
        flag = HAZARD_CHOICES[hazard][1]
        return jsonify([{"name": s.name, "address": s.address, "lat": s.lat, "lon": s.lon}
                        for s in by_id[area_id].shelters if flag in s.hazards])

    @app.post("/api/guide")
    def api_guide():
        lat, lon, hazard = _point(request.get_json(silent=True) or {})
        started = time.monotonic()
        result = guide(all_ds, lat, lon, hazard)
        log.info("guide area=%s hazard=%s status=%s candidates=%d ms=%d", result.area_id or "-", hazard, result.status,
                 len(result.candidates), (time.monotonic() - started) * 1000)
        return jsonify(result.to_dict())

    @app.post("/api/advice")
    def api_advice():
        body = request.get_json(silent=True) or {}
        lat, lon, hazard = _point(body)
        if the_advisor.external and body.get("consent") is not True:
            return jsonify(error="外部AIへの送信に同意したときだけ、AIの説明を作ります。"), 400
        result = guide(all_ds, lat, lon, hazard)  # recompute; never trust facts sent by the browser
        started = time.monotonic()
        try:
            advice, cards = adv.advise(the_advisor, result, known_sites)
        except adv.AdviceError as exc:
            log.info("advice error provider=%s ms=%d", the_advisor.name, (time.monotonic() - started) * 1000)
            return jsonify(error=str(exc)), 502
        log.info("advice ok provider=%s prompt=%s ms=%d", the_advisor.name, adv.PROMPT_VERSION,
                 (time.monotonic() - started) * 1000)
        return jsonify(advice=advice.model_dump(), provider=the_advisor.name,
                       sources=[{"id": c.id, "source": c.source, "url": c.url} for c in cards])

    @app.post("/api/chat")
    def api_chat():
        body = request.get_json(silent=True) or {}
        area_id, hazard = str(body.get("area", "")), str(body.get("hazard", ""))
        if area_id not in by_id or hazard not in HAZARD_CHOICES:
            abort(400, "地域または災害の種類が不正です。")
        if the_advisor.external and body.get("consent") is not True:
            return jsonify(error="外部AIへの送信に同意したときだけ、AIが答えます。"), 400
        question = str(body.get("question", "")).strip()
        if not question or len(question) > adv.MAX_QUESTION:
            abort(400, f"質問は1〜{adv.MAX_QUESTION}文字で入力してください。")
        history = body.get("history") if isinstance(body.get("history"), list) else []
        lat = lon = None
        if body.get("lat") is not None and body.get("lon") is not None:
            lat, lon, _ = _point({"lat": body["lat"], "lon": body["lon"], "hazard": hazard})
        facts, cards = adv.chat_context(all_ds, area_id, hazard, lat, lon)
        started = time.monotonic()
        try:
            answer = adv.chat(the_advisor, facts, cards, history, question, known_sites)
        except adv.AdviceError as exc:
            log.info("chat error provider=%s ms=%d", the_advisor.name, (time.monotonic() - started) * 1000)
            return jsonify(error=str(exc)), 502
        log.info("chat ok provider=%s in_scope=%s ms=%d", the_advisor.name, answer.in_scope,
                 (time.monotonic() - started) * 1000)  # the question text is not logged
        by_card = {c.id: c for c in cards}
        return jsonify(answer=answer.answer, in_scope=answer.in_scope, provider=the_advisor.name,
                       sources=[{"id": i, "source": by_card[i].source, "url": by_card[i].url}
                                for i in answer.source_ids if i in by_card])

    @app.get("/tiles/<layer>/<int:z>/<int:x>/<int:y>.png")
    def tile(layer: str, z: int, x: int, y: int):
        dirs = {l.key: l.tile_dir for l in LAYERS.values()}
        if layer not in dirs or z != ZOOM:
            abort(404)
        return send_from_directory(DATA_DIR / "hazard" / dirs[layer] / str(z) / str(x), f"{y}.png", max_age=3600)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        app = create_app()
    except ValueError as exc:
        raise SystemExit(f"設定エラー: {exc}") from None
    app.run(host="127.0.0.1", port=int(os.environ.get("HINAN_PORT", DEFAULT_PORT)), debug=False)
