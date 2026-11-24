// EDEN SYSTEM: camera view with floating comments, map, photo recognition, comments. Text goes in via textContent.
(function () {
  "use strict";
  const csrf = document.body.dataset.csrf;
  const cfg = JSON.parse(document.getElementById("cfg").textContent);
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const FOV = 60; // degrees shown across the camera view

  let user = cfg.users[0].id;
  let here = { lat: cfg.center[0], lon: cfg.center[1] };
  let heading = 0;
  let visibility = "private";
  let recognition = null; // { token, label, matched }
  let nearby = [];

  // ---- map --------------------------------------------------------------------------------
  const map = L.map("map").setView([here.lat, here.lon], 17);
  L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html">地理院タイル</a>',
  }).addTo(map);
  const me = L.marker([here.lat, here.lon], { icon: L.divIcon({ className: "", html: '<div class="me"></div>', iconSize: [16, 16] }), title: "今いる場所" }).addTo(map);
  const writeCircle = L.circle([here.lat, here.lon], { radius: cfg.writeRadius, color: "#7c3aed", weight: 2, fillOpacity: 0.06 }).addTo(map);
  const camCircle = L.circle([here.lat, here.lon], { radius: cfg.cameraRadius, color: "#64748b", weight: 1, dashArray: "4 4", fill: false }).addTo(map);
  const commentLayer = L.layerGroup().addTo(map);
  map.on("click", (e) => setHere(e.latlng.lat, e.latlng.lng, "地図で指定した地点"));

  function setHere(lat, lon, label) {
    here = { lat, lon };
    me.setLatLng([lat, lon]); writeCircle.setLatLng([lat, lon]); camCircle.setLatLng([lat, lon]);
    $("here").textContent = label + "（" + lat.toFixed(5) + ", " + lon.toFixed(5) + "）";
    recognition = null; aiTag = null; showTarget(); $("recog").hidden = true;
    refresh();
  }

  // ---- users ------------------------------------------------------------------------------
  const nameOf = Object.fromEntries(cfg.users.map((u) => [u.id, u.name]));
  cfg.users.forEach((u) => {
    const b = el("button", "u" + (u.id === user ? " on" : ""), u.name); b.type = "button"; b.dataset.user = u.id;
    b.setAttribute("role", "radio"); b.setAttribute("aria-checked", u.id === user ? "true" : "false");
    b.addEventListener("click", () => {
      user = u.id;
      document.querySelectorAll(".u").forEach((x) => { const on = x.dataset.user === user; x.classList.toggle("on", on); x.setAttribute("aria-checked", on ? "true" : "false"); });
      showFriends(); recognition = null; showTarget(); $("recog").hidden = true; refresh();
    });
    $("users").append(b);
  });
  function showFriends() {
    const u = cfg.users.find((x) => x.id === user);
    $("friends").textContent = u.friends.length ? "友達：" + u.friends.map((f) => nameOf[f]).join("、") + "（プライベートのコメントを見られます）" : "友達はいません（自分のプライベートと、パブリックだけが見えます）";
  }

  // ---- comments: fetch, map, list, camera tags ------------------------------------------------
  function refresh() {
    const q = "user=" + encodeURIComponent(user) + "&lat=" + here.lat + "&lon=" + here.lon + "&radius=" + cfg.cameraRadius;
    fetch("/api/comments?" + q).then((r) => r.json()).then((list) => {
      nearby = Array.isArray(list) ? list : [];
      drawMap(); drawList(); drawTags();
    });
  }
  function drawMap() {
    commentLayer.clearLayers();
    nearby.forEach((c) => {
      const tip = el("span", null, (c.visibility === "private" ? "🔒 " : "") + c.author_name + "：" + c.text);
      L.circleMarker([c.lat, c.lon], { radius: 7, color: "#fff", weight: 2, fillColor: c.visibility === "private" ? "#15803d" : "#2563eb", fillOpacity: 0.95 })
        .bindTooltip(tip, { direction: "top" }).addTo(commentLayer);
    });
  }
  function drawList() {
    const ul = $("list"); ul.replaceChildren();
    if (!nearby.length) { ul.append(el("li", "empty", "見えるコメントはありません。")); return; }
    nearby.forEach((c) => {
      const li = el("li", c.visibility);
      li.append(el("span", "badge", c.visibility === "private" ? "🔒 プライベート" : "パブリック"), el("span", "text", c.text));
      const meta = c.author_name + "・約" + c.distance_m + "m" + (c.anchor_label ? "・対象：" + c.anchor_label : "") +
        (c.expires_at ? "・あと" + Math.max(0, Math.round((c.expires_at - Date.now() / 1000) / 3600)) + "時間" : "");
      li.append(el("span", "meta", meta));
      if (c.author === user) {
        const del = el("button", "del", "削除"); del.type = "button";
        del.addEventListener("click", () => {
          if (!confirm("このコメントを削除しますか？（元に戻せません）")) return;
          del.disabled = true;
          post("/api/comments/" + c.id + "/delete", { user }).then(({ ok, body }) => {
            if (!ok) { del.disabled = false; return say(body.error || "削除できませんでした。", true); }
            say("コメントを削除しました。"); refresh();
          }).catch(() => { del.disabled = false; say("サーバーに接続できませんでした。", true); });
        });
        li.append(del);
      }
      ul.append(li);
    });
  }
  let aiTag = null; // the AI's recognition, shown as its own bubble on the photo
  function drawTags() {
    const box = $("tags"); box.replaceChildren();
    if (aiTag) {
      const t = el("div", "tag ai");
      t.append(el("span", "badge", "AI"), el("span", "t", aiTag.label), el("span", "m", aiTag.note));
      t.style.left = "50%"; t.style.top = "46%";
      box.append(t);
    }
    nearby.forEach((c) => {
      let rel = ((c.bearing - heading + 540) % 360) - 180; // -180..180, 0 = straight ahead
      if (c.distance_m < 8) rel = 0; // right here: show in front
      if (Math.abs(rel) > FOV / 2) return;
      const tag = el("div", "tag " + c.visibility);
      tag.append(el("span", "t", (c.visibility === "private" ? "🔒 " : "") + c.text), el("span", "m", c.author_name + "・" + c.distance_m + "m" + (c.anchor_label ? "・" + c.anchor_label : "")));
      tag.style.left = (50 + (rel / FOV) * 100) + "%";
      tag.style.top = Math.min(78, 18 + (c.distance_m / cfg.cameraRadius) * 55) + "%";
      box.append(tag);
    });
  }

  // ---- camera and heading -----------------------------------------------------------------------
  $("heading").addEventListener("input", (e) => { heading = +e.target.value; $("heading-v").textContent = heading + "°"; drawTags(); });
  $("cam-start").addEventListener("click", () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return say("この端末ではカメラを使えません。", true);
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false }).then((stream) => {
      $("video").srcObject = stream; $("camera-empty").hidden = true; $("cam-start").hidden = true;
    }).catch(() => say("カメラを起動できませんでした。写真を選んで認識することもできます。", true));
  });
  $("compass").addEventListener("click", () => {
    const start = () => window.addEventListener("deviceorientation", (e) => {
      const h = e.webkitCompassHeading != null ? e.webkitCompassHeading : (e.alpha != null ? 360 - e.alpha : null);
      if (h == null) return;
      heading = Math.round(h) % 360; $("heading").value = heading; $("heading-v").textContent = heading + "°"; drawTags();
    });
    if (typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function") {
      DeviceOrientationEvent.requestPermission().then((s) => (s === "granted" ? start() : say("方位センサーを使えませんでした。", true)));
    } else { start(); }
  });
  $("locate").addEventListener("click", () => {
    if (!navigator.geolocation) return say("位置情報を使えません。地図をクリックしてください。", true);
    navigator.geolocation.getCurrentPosition((p) => { map.setView([p.coords.latitude, p.coords.longitude], 17); setHere(p.coords.latitude, p.coords.longitude, "現在地"); },
      () => say("現在地を取得できませんでした。地図をクリックしてください。", true), { enableHighAccuracy: true, timeout: 10000 });
  });

  // ---- recognition ----------------------------------------------------------------------------------
  function post(url, body, isForm) {
    const headers = { "X-CSRF-Token": csrf }; if (!isForm) headers["Content-Type"] = "application/json";
    return fetch(url, { method: "POST", headers, body: isForm ? body : JSON.stringify(body) }).then((r) =>
      r.json().then((j) => ({ ok: r.ok, body: j }), () => ({ ok: false, body: { error: "サーバーがエラーを返しました（HTTP " + r.status + "）。" } })));
  }
  // Shrink photos in the browser before upload: phone photos are often over 10 MB, and the server
  // only keeps a 1024 px version anyway. If the browser cannot decode the file, send it as is.
  const UPLOAD_SIDE = 1600;
  function shrink(blob) {
    if (typeof createImageBitmap !== "function") return Promise.resolve(blob);
    return createImageBitmap(blob).then((bmp) => {
      const scale = Math.min(1, UPLOAD_SIDE / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas"); c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      return new Promise((res) => c.toBlob((b) => res(b || blob), "image/jpeg", 0.88));
    }).catch(() => blob);
  }
  function showStill(blob) {
    const img = $("still");
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    img.dataset.url = URL.createObjectURL(blob); img.src = img.dataset.url;
    img.hidden = false; $("still-close").hidden = false; $("camera-empty").hidden = true;
  }
  $("still-close").addEventListener("click", () => {
    $("still").hidden = true; $("still-close").hidden = true; aiTag = null; drawTags();
    if (!$("video").srcObject) $("camera-empty").hidden = false;
  });
  function recognize(original) {
    showStill(original);
    const box0 = $("recog"); box0.hidden = false; box0.className = "recog"; box0.textContent = "写真を準備しています…";
    shrink(original).then((blob) => send(blob));
  }
  function send(blob) {
    const fd = new FormData();
    fd.append("user", user); fd.append("lat", here.lat); fd.append("lon", here.lon); fd.append("photo", blob, "photo.jpg");
    if (cfg.external) fd.append("consent", $("consent").checked ? "yes" : "no");
    const box = $("recog"); box.hidden = false; box.className = "recog"; box.textContent = "AIが写真の対象を見分けています…";
    post("/api/recognize", fd, true).then(({ ok, body }) => {
      box.replaceChildren();
      if (!ok) { box.className = "recog err"; box.textContent = body.error || "認識できませんでした。"; return; }
      if (body.person) { box.className = "recog err"; box.textContent = body.message; recognition = null; aiTag = null; drawTags(); showTarget(); return; }
      recognition = { token: body.token, label: body.label, matched: body.matched };
      aiTag = { label: body.matched ? body.matched.label : body.label,
                note: body.matched ? "登録済みの対象・コメント" + body.comments.length + "件" : "まだコメントのない対象です" };
      drawTags();
      box.append(el("p", "label", "見分けた対象：" + body.label), el("p", "sub", body.description));
      if (body.matched) {
        box.append(el("p", "hit", "この対象は登録済みです（" + body.matched.label + "）。結び付いたコメント：" + body.comments.length + "件"));
        const ul = el("ul", "list"); body.comments.forEach((c) => { const li = el("li", c.visibility); li.append(el("span", "text", c.text), el("span", "meta", c.author_name)); ul.append(li); });
        box.append(ul);
      } else {
        box.append(el("p", "sub", "まだコメントのない対象です。最初のコメントを残せます。"));
      }
      showTarget();
    }).catch(() => { box.className = "recog err"; box.textContent = "サーバーに接続できませんでした。"; });
  }
  $("snap").addEventListener("click", () => {
    const v = $("video");
    if (!v.srcObject || !v.videoWidth) { $("file").click(); return; }
    const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0); c.toBlob((b) => recognize(b), "image/jpeg", 0.9);
  });
  $("file").addEventListener("change", (e) => { if (e.target.files[0]) recognize(e.target.files[0]); e.target.value = ""; });

  // ---- posting --------------------------------------------------------------------------------------
  function showTarget() {
    $("target").textContent = recognition ? "対象：" + (recognition.matched ? recognition.matched.label : recognition.label) + "（写真で見分けた対象に結び付けます）" : "対象：今いる場所（写真で見分けると、その対象に結び付きます）";
  }
  document.querySelectorAll(".v").forEach((b) => b.addEventListener("click", () => {
    visibility = b.dataset.vis;
    document.querySelectorAll(".v").forEach((x) => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-checked", on ? "true" : "false"); });
  }));
  function say(text, err) { const m = $("post-msg"); m.textContent = text; m.classList.toggle("err", !!err); }
  $("post").addEventListener("click", () => {
    const text = $("text").value.trim();
    if (!text) return say("コメントを入力してください。", true);
    $("post").disabled = true; say(visibility === "public" ? "内容を確認しています…" : "残しています…");
    const body = { user, lat: here.lat, lon: here.lon, text, visibility };
    if (recognition) body.token = recognition.token;
    post("/api/comments", body).then(({ ok, body: res }) => {
      if (!ok) return say(res.error || "残せませんでした。", true);
      $("text").value = ""; say(visibility === "private" ? "残しました（友達だけに見え、24時間で消えます）。" : "残しました（誰でも見られます）。");
      refresh();
    }).catch(() => say("サーバーに接続できませんでした。", true)).finally(() => { $("post").disabled = false; });
  });

  // ---- deep link for demos: ?user=..&lat=..&lon=..&heading=.. ------------------------------------------------
  const q = new URLSearchParams(location.search);
  if (q.get("user") && nameOf[q.get("user")]) document.querySelector('.u[data-user="' + q.get("user") + '"]').click();
  if (q.has("heading")) { heading = (+q.get("heading") || 0) % 360; $("heading").value = heading; $("heading-v").textContent = heading + "°"; }
  showFriends(); showTarget();
  const lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon"));
  if (isFinite(lat) && isFinite(lon)) { map.setView([lat, lon], 17); setHere(lat, lon, "指定した地点"); } else { refresh(); }
})();
