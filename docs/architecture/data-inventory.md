# データ利用台帳

ハザードマップナビが使うデータの出典、規約、取得日、加工内容。取得は `scripts/fetch_data.py`、結果は `data/areas/<id>/`（konohana・yashio・misato）と共有の `data/hazard/`。
取得日時は各 `data/areas/<id>/meta.json` の `fetched_at`（2026-11-24）。

| データ | 提供元・URL | 規約・出典表示 | 取得方法 | 加工 | 確認した事実 |
|---|---|---|---|---|---|
| 指定緊急避難場所 | 国土地理院 https://www.gsi.go.jp/bousaichiri/hinanbasho.html （地理院タイル `skhb01`〜`skhb08`） | 公共データ利用規約 第1.0版（PDL1.0）。「出典：国土地理院ウェブサイト」と、加工した旨を表示。ご利用上の注意（最新でない場合がある・災害種別ごとに指定・随時更新）を利用者に伝える | z10 の GeoJSON タイルを災害種別ごとに取得 | 各地域の境界内だけを残し、同じ施設の災害種別フラグを統合 | 此花区139件（洪水80・地震59・津波80・高潮0）、八潮市27件（洪水27・地震27・内水27・火山16）、三郷市36件（洪水33・地震36・大規模な火事36・内水33）。3地域とも高潮・津波対応は0件。電話番号の属性はない |
| 浸水想定（津波・高潮・洪水 想定最大規模） | ハザードマップポータルサイト https://disaportal.gsi.go.jp/hazardmapportal/hazardmap/copyright/opendata.html | PDL1.0。「出典：ハザードマップポータルサイト」と、加工した旨を表示。宅建業の重要事項説明には使えない。最新は各市町村のハザードマップを確認 | z15 の PNG タイル（区の範囲） | 画素色を凡例 `shinsui_legend3.png` の色で浸水深の区分に変換。凡例は粗い区分と細かい区分の2列で、(255,216,192) は両方で誤らない「0.5〜3m」と表示 | 共有で415枚（此花区: 津波112・高潮114・洪水40、八潮市: 高潮20・洪水63、三郷市: 津波2・高潮32・洪水77。重複は共有）。404 のタイルは「浸水の想定なし」として扱う |
| 区の境界・歩行者ネットワーク | OpenStreetMap（Nominatim・Overpass、OSMnx 経由） https://www.openstreetmap.org/copyright | ODbL 1.0。「© OpenStreetMap contributors」を表示。派生データベースを公開配布する場合は ODbL の継承条件に注意（本提出はローカル提示） | `osmnx.geocode_to_gdf`、`graph_from_polygon(network_type="walk")` | 無向グラフ化し、区間長（m）だけを保持 | 此花区 5,558ノード、八潮市 10,599ノード、三郷市 13,259ノード（各境界から約400m広げた範囲） |
| 地図の背景 | 地理院タイル（淡色地図） https://maps.gsi.go.jp/development/ichiran.html | 地理院タイルの規約に従い「地理院タイル」と出典表示 | ブラウザが表示時に取得（保存しない） | なし | — |
| AI の根拠カード | 気象庁「津波から身を守るために」「防災気象情報と警戒レベルとの対応について」、防災庁「避難情報に関するガイドライン」 | 気象庁は PDL1.0（出典：気象庁ホームページ）。防災庁サイトは利用規約の記載を確認できなかったため、図の区分の短い要約とリンクに限る | 2026-11-24 に一次情報を確認して `src/hinan/knowledge.py` に記載 | 気象庁は原文の引用、防災庁は要約 | 此花区の資料にあるとされた「3階以上なら自宅で避難」等は、原文で確認できなかったため使わない |
| 連絡先 | 此花区役所 https://www.city.osaka.lg.jp/konohana/ 、八潮市役所 https://www.city.yashio.lg.jp/ 、三郷市役所 https://www.city.misato.lg.jp/ 、NTT西日本 https://www.ntt-west.co.jp/dengon/ | — | 2026-11-24 に公式サイトで確認 | 此花区役所 06-6466-9986、八潮市役所 048-996-2111（危機管理防災課も同番号の内線）、三郷市役所 048-953-1111 | 此花区・三郷市の防災担当の直通番号は見つからなかった |

## 再取得

```bash
uv run --frozen --group data python scripts/fetch_data.py            # 全地域
uv run --frozen --group data python scripts/fetch_data.py yashio     # 地域を指定
```

データは随時更新される。再取得したら `meta.json` の件数とテストの期待値（施設数・浸水深）を確認する。
