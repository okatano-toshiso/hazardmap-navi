// ハザードマップナビ: hazard map + area selection + deterministic guide; AI explanation only on request.
// All data-derived text goes into the DOM via textContent (no innerHTML with data).
(function () {
  "use strict";
  const body = document.body;
  const csrf = body.dataset.csrf;
  const cfg = JSON.parse(document.getElementById("ui-config").textContent);
  const external = cfg.external;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const areaById = Object.fromEntries(cfg.areas.map((a) => [a.id, a]));
  const toLatLngBounds = (b) => L.latLngBounds([[b[1], b[0]], [b[3], b[2]]]);

  let hazard = document.querySelector(".hz.on").dataset.hazard;
  let areaId = document.querySelector(".area-card.on").dataset.area;
  let point = null;
  let overlayOn = true;
  let overlayOpacity = 0.6;

  // ---- map, base layer, attribution --------------------------------------------------------
  const map = L.map("map", { minZoom: 11, maxZoom: 18, zoomSnap: 0.5 });
  L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html">地理院タイル</a>',
  }).addTo(map);
  map.attributionControl.addAttribution('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors');
  map.attributionControl.addAttribution('<a href="https://disaportal.gsi.go.jp/">ハザードマップポータルサイト</a>');

  // ---- hazard map overlay: the same saved tiles the depth check uses, limited to the areas' bounds.
  // Overlapping area rectangles (Yashio and Misato are adjacent) are merged so no tile is drawn twice.
  function mergedBounds() {
    let groups = cfg.areas.map((a) => toLatLngBounds(a.bounds));
    let merged = true;
    while (merged) {
      merged = false;
      outer: for (let i = 0; i < groups.length; i++) {
        for (let j = i + 1; j < groups.length; j++) {
          if (groups[i].intersects(groups[j])) {
            groups[i] = L.latLngBounds(groups[i].getSouthWest(), groups[i].getNorthEast()).extend(groups[j]);
            groups.splice(j, 1); merged = true; break outer;
          }
        }
      }
    }
    return groups;
  }
  const overlayBounds = mergedBounds();
  const overlay = L.layerGroup().addTo(map);
  function drawOverlay() {
    overlay.clearLayers();
    if (!overlayOn || !cfg.overlayHazards.includes(hazard)) return;
    overlayBounds.forEach((b) => {
      L.tileLayer("/tiles/" + hazard + "/{z}/{x}/{y}.png", {
        minNativeZoom: 15, maxNativeZoom: 15, maxZoom: 18, opacity: overlayOpacity, bounds: b,
      }).addTo(overlay);
    });
  }

  // ---- area outlines -----------------------------------------------------------------------
  const outlines = {};
  fetch("/api/area").then((r) => r.json()).then((fc) => {
    fc.features.forEach((f) => { outlines[f.properties.id] = L.geoJSON(f).addTo(map); });
    styleOutlines();
  });
  function styleOutlines() {
    Object.entries(outlines).forEach(([id, layer]) => layer.setStyle(id === areaId
      ? { color: "#0b5cad", weight: 3, fill: false, dashArray: null, opacity: 0.9 }
      : { color: "#667085", weight: 1.5, fill: false, dashArray: "6 4", opacity: 0.6 }));
  }

  // ---- designated sites for the selected area and hazard -----------------------------------
  const siteLayer = L.layerGroup().addTo(map);
  let siteRequest = 0;
  function drawSites() {
    const ticket = ++siteRequest;
    siteLayer.clearLayers();
    fetch("/api/sites?area=" + encodeURIComponent(areaId) + "&hazard=" + encodeURIComponent(hazard))
      .then((r) => r.json()).then((sites) => {
        if (ticket !== siteRequest || !Array.isArray(sites)) return;
        sites.forEach((s) => {
          const tip = el("span", null, s.name);
          L.circleMarker([s.lat, s.lon], { radius: 5, color: "#ffffff", weight: 1.5, fillColor: "#1f7a4d", fillOpacity: 0.9 })
            .bindTooltip(tip, { direction: "top" }).addTo(siteLayer);
        });
      });
  }

  // ---- map controls: hazard map toggle + opacity, and legend --------------------------------
  const Panel = L.Control.extend({
    onAdd() {
      const box = el("div", "map-ctl");
      const label = el("label", "ctl-row");
      const cb = el("input"); cb.type = "checkbox"; cb.checked = true; cb.id = "overlay-toggle";
      label.append(cb, el("span", null, "ハザードマップを表示"));
      const range = el("input"); range.type = "range"; range.min = "0.2"; range.max = "0.9"; range.step = "0.1"; range.value = String(overlayOpacity);
      range.setAttribute("aria-label", "ハザードマップの濃さ");
      const rangeRow = el("label", "ctl-row"); rangeRow.append(el("span", null, "濃さ"), range);
      cb.addEventListener("change", () => { overlayOn = cb.checked; drawOverlay(); updateLegend(); });
      range.addEventListener("input", () => { overlayOpacity = +range.value; overlay.eachLayer((l) => l.setOpacity(overlayOpacity)); });
      box.append(label, rangeRow);
      L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box);
      return box;
    },
  });
  new Panel({ position: "topright" }).addTo(map);

  const Legend = L.Control.extend({
    onAdd() {
      const box = el("div", "map-legend"); box.id = "legend";
      L.DomEvent.disableClickPropagation(box);
      return box;
    },
  });
  new Legend({ position: "bottomleft" }).addTo(map);
  function updateLegend() {
    const box = $("legend"); box.replaceChildren();
    if (!cfg.overlayHazards.includes(hazard)) {
      box.append(el("div", "lg-title", "地震"), el("div", "lg-note", "浸水の想定はありません。避難場所だけを表示します。"));
      return;
    }
    box.append(el("div", "lg-title", "想定浸水深（" + cfg.hazardLabels[hazard] + "）"));
    if (!overlayOn) { box.append(el("div", "lg-note", "ハザードマップは非表示です。")); return; }
    cfg.legend.forEach((item) => {
      const row = el("div", "lg-row"); const sw = el("span", "lg-sw");
      sw.style.background = "rgb(" + item.rgb.join(",") + ")"; // CSSOM, allowed by the CSP
      row.append(sw, el("span", null, item.label)); box.append(row);
    });
    const site = el("div", "lg-row"); const dot = el("span", "lg-dot"); site.append(dot, el("span", null, "対応する避難場所"));
    box.append(site);
  }

  // ---- step 1: area selection --------------------------------------------------------------
  function updateCounts() {
    document.querySelectorAll("[data-count-for]").forEach((span) => {
      const a = areaById[span.dataset.countFor];
      span.textContent = cfg.hazardLabels[hazard] + "の避難場所 " + a.counts[hazard] + "件";
    });
  }
  function showOffice(office) {
    $("office").hidden = false;
    $("office-name").textContent = office.name;
    $("office-note").textContent = office.note;
    $("office-tel").textContent = office.phone;
    $("office-tel").href = "tel:" + office.phone.replace(/-/g, "");
  }
  function selectArea(id, fit) {
    areaId = id;
    showOffice(areaById[id].office); // the contact list always follows the selected area
    document.querySelectorAll(".area-card").forEach((b) => {
      const on = b.dataset.area === id; b.classList.toggle("on", on); b.setAttribute("aria-checked", on ? "true" : "false");
    });
    styleOutlines(); drawSites();
    if (fit) map.fitBounds(toLatLngBounds(areaById[id].bounds), { padding: [20, 20] });
  }
  document.querySelectorAll(".area-card").forEach((b) => b.addEventListener("click", () => {
    selectArea(b.dataset.area, true);
    clearResult();
    setStatus(areaById[b.dataset.area].name + "を表示しています。現在地を使うか、地図をクリックしてください。");
  }));

  // ---- step 2: hazard selection ------------------------------------------------------------
  document.querySelectorAll(".hz").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".hz").forEach((x) => { x.classList.remove("on"); x.setAttribute("aria-checked", "false"); });
    b.classList.add("on"); b.setAttribute("aria-checked", "true");
    hazard = b.dataset.hazard;
    drawOverlay(); updateLegend(); updateCounts(); drawSites();
    if (point) lookup(point.lat, point.lon);
  }));

  // ---- step 3: point and guide ---------------------------------------------------------------
  const resultLayer = L.layerGroup().addTo(map);

  function post(url, data) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(data) }).then((r) => r.json().then((j) => ({ ok: r.ok, body: j })));
  }
  function setStatus(text, err) { const s = $("status"); s.textContent = text; s.classList.toggle("err", !!err); }
  function clearResult() { resultLayer.clearLayers(); $("result").hidden = true; point = null; $("ask").disabled = true; }

  function render(r) {
    resultLayer.clearLayers();
    L.marker([r.lat, r.lon], { icon: L.divIcon({ className: "", html: '<div class="here"></div>', iconSize: [16, 16] }), title: "今いる場所" }).addTo(resultLayer);
    $("ask").disabled = r.status !== "ok";
    if (r.status === "out_of_area") {
      $("result").hidden = true;
      setStatus(r.message, true);
      return;
    }
    if (r.area_id !== areaId) selectArea(r.area_id, false); // a click in another area switches the selection
    setStatus(r.area_name + "・" + r.hazard_label + "：この地点を調べました。");
    $("result").hidden = false;
    $("area-name").textContent = r.area_name;
    showOffice(r.contacts[r.contacts.length - 1]);

    const depths = $("depths"); depths.replaceChildren();
    Object.entries(r.depths).forEach(([key, d]) => {
      const li = el("li", (key === r.hazard ? "sel " : "") + (d.min_m >= 3 ? "deep" : ""));
      li.append(el("span", null, d.layer), el("span", "v", d.depth_label));
      depths.append(li);
    });

    const note = $("note"); note.hidden = !r.message; note.textContent = r.message || "";
    $("sites-title").textContent = r.hazard_label + "に対応する指定緊急避難場所（徒歩で近い順）";
    const sites = $("sites"); sites.replaceChildren();
    const bounds = L.latLngBounds([[r.lat, r.lon]]);
    r.candidates.forEach((c, i) => {
      const li = el("li");
      li.append(el("span", "name", c.name), el("br"),
        el("span", "meta", "徒歩 約" + c.distance_m.toLocaleString() + "m・約" + c.minutes + "分　" + c.address));
      li.addEventListener("click", () => map.setView([c.lat, c.lon], 17));
      sites.append(li);
      L.polyline(c.route, i === 0 ? { color: "#1f7a4d", weight: 6, opacity: 0.9 } : { color: "#0b5cad", weight: 3, opacity: 0.8, dashArray: "6 6" }).addTo(resultLayer);
      L.marker([c.lat, c.lon], { icon: L.divIcon({ className: "", html: '<div class="pin' + (i === 0 ? " first" : "") + '">' + c.rank + "</div>", iconSize: [26, 26] }), title: c.name }).addTo(resultLayer);
      bounds.extend([c.lat, c.lon]);
    });
    if (r.candidates.length) map.fitBounds(bounds.pad(0.25), { maxZoom: 17 });
  }

  function lookup(lat, lon, then) {
    point = { lat, lon };
    setStatus("調べています…");
    post("/api/guide", { lat, lon, hazard }).then(({ ok, body }) => {
      if (!ok) return setStatus(body.error || "エラーが発生しました。", true);
      render(body);
      if (then) then(body);
    }).catch(() => setStatus("サーバーに接続できませんでした。", true));
  }

  map.on("click", (e) => lookup(e.latlng.lat, e.latlng.lng));
  $("locate").addEventListener("click", () => {
    if (!navigator.geolocation) return setStatus("この端末では位置情報を使えません。地図をクリックしてください。", true);
    setStatus("現在地を取得しています…");
    navigator.geolocation.getCurrentPosition(
      (p) => { map.setView([p.coords.latitude, p.coords.longitude], 16); lookup(p.coords.latitude, p.coords.longitude); },
      () => setStatus("現在地を取得できませんでした。地図をクリックして地点を選んでください。", true),
      { enableHighAccuracy: true, timeout: 10000 });
  });

  // ---- AI assistant: "what to do now" and free questions share one message log ----------------
  const history = [];
  function bubble(role, text) {
    const b = el("div", "msg " + role); if (text != null) b.append(el("p", null, text));
    $("chat-log").append(b); scrollChat(); return b;
  }
  function scrollChat() { const box = document.querySelector(".chat-body"); box.scrollTop = box.scrollHeight; }
  function openChat(open) {
    $("chat-panel").hidden = !open;
    $("chat-launcher").setAttribute("aria-expanded", open ? "true" : "false");
    $("chat-launcher").lastElementChild.textContent = open ? "閉じる" : "AIに質問";
    if (open) { scrollChat(); $("chat-input").focus(); }
  }
  $("chat-launcher").addEventListener("click", () => openChat($("chat-panel").hidden));
  $("chat-close").addEventListener("click", () => { openChat(false); $("chat-launcher").focus(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("chat-panel").hidden) { openChat(false); $("chat-launcher").focus(); } });
  function sourcesList(sources) {
    const ul = el("ul", "sources");
    sources.forEach((s) => { const li = el("li", null, s.id + "：" + s.source + " "); const link = el("a", null, "出典"); link.href = s.url; link.rel = "noreferrer"; link.target = "_blank"; li.append(link); ul.append(li); });
    return ul;
  }
  function consentGiven() { return external ? $("consent").checked : true; }
  function busy(on) { $("chat-send").disabled = on; $("ask").disabled = on || !point; }

  function ask() {
    if (!point) return;
    bubble("user", "今やることを教えてください");
    const box = bubble("bot", "AIが説明を作っています…（数秒〜十数秒）");
    busy(true);
    post("/api/advice", { lat: point.lat, lon: point.lon, hazard, consent: consentGiven() }).then(({ ok, body }) => {
      box.replaceChildren();
      if (!ok) { box.classList.add("err"); box.append(el("p", null, body.error || "AIの説明を作れませんでした。")); return; }
      const a = body.advice;
      box.append(el("p", "headline", a.headline));
      const ol = el("ol");
      a.steps.forEach((s) => { const li = el("li", null, s.text + " "); li.append(el("span", "src", "［" + s.source_ids.join("・") + "］")); ol.append(li); });
      box.append(ol, el("p", "caution", a.caution), sourcesList(body.sources));
      history.push({ role: "user", text: "今やることを教えてください" }, { role: "assistant", text: a.headline + " " + a.steps.map((s) => s.text).join(" ") });
    }).catch(() => { box.replaceChildren(el("p", null, "サーバーに接続できませんでした。")); box.classList.add("err"); })
      .finally(() => busy(false));
  }
  $("ask").addEventListener("click", ask);

  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const question = $("chat-input").value.trim();
    if (!question) return;
    $("chat-input").value = "";
    bubble("user", question);
    const box = bubble("bot", "考えています…");
    busy(true);
    const payload = { area: areaId, hazard, question, history: history.slice(-6), consent: consentGiven() };
    if (point) { payload.lat = point.lat; payload.lon = point.lon; }
    post("/api/chat", payload).then(({ ok, body }) => {
      box.replaceChildren();
      if (!ok) { box.classList.add("err"); box.append(el("p", null, body.error || "AIが答えられませんでした。")); return; }
      box.append(el("p", null, body.answer));
      if (!body.in_scope) box.append(el("p", "src", "（避難・防災に関する質問に答えます）"));
      if (body.sources.length) box.append(sourcesList(body.sources));
      history.push({ role: "user", text: question }, { role: "assistant", text: body.answer });
    }).catch(() => { box.replaceChildren(el("p", null, "サーバーに接続できませんでした。")); box.classList.add("err"); })
      .finally(() => busy(false));
  });
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("chat-form").requestSubmit(); }
  });

  // ---- initial state and deep link: ?area=..&hazard=..&lat=..&lon=..[&ask=1] -------------------
  // ask only runs if consent is already given on screen.
  const q = new URLSearchParams(location.search);
  if (q.get("chat") === "1") openChat(true);
  if (q.has("hazard")) { const b = document.querySelector('.hz[data-hazard="' + q.get("hazard") + '"]'); if (b) { b.classList.add("on"); hazard = b.dataset.hazard; } }
  document.querySelectorAll(".hz").forEach((x) => { const on = x.dataset.hazard === hazard; x.classList.toggle("on", on); x.setAttribute("aria-checked", on ? "true" : "false"); });
  const startArea = areaById[q.get("area")] ? q.get("area") : areaId;
  selectArea(startArea, true);
  drawOverlay(); updateLegend(); updateCounts();
  const lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon"));
  if (isFinite(lat) && isFinite(lon)) {
    map.setView([lat, lon], 16);
    lookup(lat, lon, (r) => { if (q.get("ask") === "1" && r.status === "ok" && (!external || $("consent").checked)) { openChat(true); ask(); } });
  } else {
    setStatus(areaById[startArea].name + "を表示しています。現在地を使うか、地図をクリックしてください。");
  }
})();
