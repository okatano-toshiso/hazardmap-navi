"""Web layer: CSRF, input validation, consent, headers, tiles, default port."""

import re

import pytest

from hinan import advisor as A
from hinan.web import create_app


class ExternalStub(A.MockAdvisor):
    name = "stub"
    external = True
    model = "stub"

    def __init__(self):
        self.calls = 0

    def advise(self, facts, cards):
        self.calls += 1
        return super().advise(facts, cards)


@pytest.fixture
def make():
    def _make(advisor=None):
        app = create_app(advisor or A.MockAdvisor())
        app.testing = True
        client = app.test_client()
        token = re.search(r'data-csrf="([^"]+)"', client.get("/").get_data(as_text=True)).group(1)
        return client, token
    return _make


def _post(client, token, url, **body):
    return client.post(url, json=body, headers={"X-CSRF-Token": token} if token else {})


def test_page_has_security_headers_and_attribution(make):
    client, _ = make()
    page = client.get("/")
    assert "script-src 'self'" in page.headers["Content-Security-Policy"]
    assert page.headers["X-Frame-Options"] == "DENY"
    html = page.get_data(as_text=True)
    assert "OpenStreetMap" in html and "国土地理院" in html and "ハザードマップポータルサイト" in html
    assert "119" in html and "171" in html  # common contacts are visible before any lookup
    assert "ハザードマップナビ" in html and "埼玉県八潮市" in html and "埼玉県三郷市" in html


def test_page_config_carries_each_area_office_for_the_contact_list(make):
    import json
    client, _ = make()
    html = client.get("/").get_data(as_text=True)
    cfg = json.loads(re.search(r'<script type="application/json" id="ui-config">(.*?)</script>', html, re.S).group(1))
    offices = {a["id"]: a["office"]["phone"] for a in cfg["areas"]}
    assert offices == {"konohana": "06-6466-9986", "yashio": "048-996-2111", "misato": "048-953-1111"}
    assert cfg["legend"][0]["label"] == "20m以上" and len(cfg["legend"]) == 8


@pytest.mark.parametrize("area, hazard, n", [("konohana", "tsunami", 80), ("yashio", "flood", 27), ("misato", "storm_surge", 0)])
def test_sites_endpoint_filters_by_area_and_hazard(make, area, hazard, n):
    client, _ = make()
    assert len(client.get(f"/api/sites?area={area}&hazard={hazard}").get_json()) == n


@pytest.mark.parametrize("query", ["area=nowhere&hazard=flood", "area=yashio&hazard=meteor", ""])
def test_sites_endpoint_rejects_bad_params(make, query):
    client, _ = make()
    assert client.get(f"/api/sites?{query}").status_code == 400


def test_area_endpoint_lists_all_areas(make):
    client, _ = make()
    ids = [f["properties"]["id"] for f in client.get("/api/area").get_json()["features"]]
    assert ids == ["konohana", "yashio", "misato"]


def test_post_without_csrf_is_rejected(make):
    client, _ = make()
    assert _post(client, None, "/api/guide", lat=34.68, lon=135.47, hazard="tsunami").status_code == 403


@pytest.mark.parametrize("body", [{"lat": "x", "lon": 135.47, "hazard": "tsunami"},
                                  {"lat": 34.68, "lon": 135.47, "hazard": "meteor"},
                                  {"lat": 999, "lon": 135.47, "hazard": "tsunami"}])
def test_invalid_input_is_400(make, body):
    client, token = make()
    assert _post(client, token, "/api/guide", **body).status_code == 400


def test_guide_returns_candidates(make):
    client, token = make()
    data = _post(client, token, "/api/guide", lat=34.68241, lon=135.4705, hazard="tsunami").get_json()
    assert data["status"] == "ok" and len(data["candidates"]) == 3


def test_external_ai_requires_consent(make):
    stub = ExternalStub()
    client, token = make(stub)
    res = _post(client, token, "/api/advice", lat=34.68241, lon=135.4705, hazard="tsunami")
    assert res.status_code == 400 and stub.calls == 0
    res = _post(client, token, "/api/advice", lat=34.68241, lon=135.4705, hazard="tsunami", consent=True)
    assert res.status_code == 200 and stub.calls == 1


def test_tiles_only_serve_known_layers(make):
    client, _ = make()
    assert client.get("/tiles/tsunami/15/28714/13014.png").status_code == 200
    assert client.get("/tiles/secret/15/1/1.png").status_code == 404
    assert client.get("/tiles/tsunami/14/1/1.png").status_code == 404


def test_main_defaults_to_port_8765(monkeypatch):
    from flask import Flask

    from hinan import web

    seen = {}
    monkeypatch.delenv("HINAN_PORT", raising=False)
    monkeypatch.setenv("HINAN_AI_PROVIDER", "mock")
    monkeypatch.setattr(Flask, "run", lambda self, **kw: seen.update(kw))
    web.main()
    assert seen == {"host": "127.0.0.1", "port": 8765, "debug": False}


class ChatStub(A.MockAdvisor):
    """External advisor whose chat reply is fixed, to test the endpoint's checks."""

    name = "chatstub"
    external = True
    model = "stub"

    def __init__(self, reply="海辺から離れ、高い所へ向かってください。"):
        self.reply, self.calls, self.facts = reply, 0, None

    def chat(self, facts, cards, history, question):
        self.calls += 1
        self.facts = facts
        return A.ChatAnswer(answer=self.reply, source_ids=["facts"], in_scope=True)


def test_page_has_floating_chat_widget_closed_by_default(make):
    client, _ = make()
    html = client.get("/").get_data(as_text=True)
    assert 'id="chat-launcher"' in html and 'id="chat-panel"' in html
    assert re.search(r'id="chat-panel"[^>]*\bhidden\b', html)


def test_chat_requires_consent_for_external_ai(make):
    stub = ChatStub()
    client, token = make(stub)
    res = _post(client, token, "/api/chat", area="yashio", hazard="flood", question="何をすればいい？")
    assert res.status_code == 400 and stub.calls == 0


@pytest.mark.parametrize("body", [{"area": "yashio", "hazard": "flood", "question": ""},
                                  {"area": "yashio", "hazard": "flood", "question": "あ" * 301},
                                  {"area": "nowhere", "hazard": "flood", "question": "質問"}])
def test_chat_rejects_bad_input(make, body):
    stub = ChatStub()
    client, token = make(stub)
    assert _post(client, token, "/api/chat", consent=True, **body).status_code == 400 and stub.calls == 0


def test_chat_uses_area_facts_before_a_point_and_guide_facts_after(make):
    stub = ChatStub()
    client, token = make(stub)
    assert _post(client, token, "/api/chat", area="yashio", hazard="flood", question="避難場所は？", consent=True).status_code == 200
    assert stub.facts["area"] == "埼玉県八潮市" and stub.facts["evacuation_sites"] == []
    assert stub.facts["designated_sites_for_this_hazard_in_area"] == 27
    assert _post(client, token, "/api/chat", area="yashio", hazard="flood", question="避難場所は？", consent=True,
                 lat=35.82435, lon=139.8367).status_code == 200
    assert stub.facts["evacuation_sites"][0]["name"] == "八潮中学校"
    assert "35.82" not in str(stub.facts)  # coordinates are never sent to the AI


def test_chat_answer_with_invented_number_is_not_shown(make):
    client, token = make(ChatStub(reply="徒歩で約37分です。"))
    res = _post(client, token, "/api/chat", area="yashio", hazard="flood", question="何分かかる？", consent=True)
    assert res.status_code == 502 and "37" in res.get_json()["error"]


def test_chat_may_repeat_numbers_the_user_wrote(make):
    client, token = make(ChatStub(reply="3階にいる場合も、自治体の情報を確認してください。"))
    res = _post(client, token, "/api/chat", area="yashio", hazard="flood", question="3階に住んでいます", consent=True)
    assert res.status_code == 200
