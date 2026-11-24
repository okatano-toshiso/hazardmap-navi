# OSS利用台帳

## Status

[ADR 0002](../decisions/0002-evacuation-guide-stack.md)（ハザードマップナビ）の構成として、以下を採用した（2026-11-24）。
Python 依存は `uv.lock` でハッシュ付きに固定し、`pyproject.toml` の直接依存とこの台帳の一致を確認している。

## Accepted dependencies

| Package | Version | License | Purpose / Boundary | Alternatives |
|---|---|---|---|---|
| `flask` | 3.1.3 | BSD-3-Clause | 1画面の HTTP、JSON API、Jinja 描画。CSRF・ヘッダー・入力検証は自作の薄い層 | ユーザー指定 |
| `jinja2`（flask経由） | 3.1.6 | BSD-3-Clause | テンプレートと自動エスケープ | ユーザー指定 |
| `werkzeug`（flask経由） | 3.1.9 | BSD-3-Clause | リクエスト処理、サイズ上限、安全なファイル配信（`send_from_directory`） | Flask の必須依存 |
| `pillow` | 13.0.0 | MIT-CMU | 浸水想定タイル（PNG）の画素色の読み取り | 自作の PNG デコーダ。非現実的 |
| `pydantic` | 2.14.4 | MIT | AI 出力スキーマ（`Advice`）の生成と検証。数値・施設名の根拠検査は自作 | 手書き JSON 検証 |
| `osmnx`（data） | 2.2.0 | MIT | 開発時のデータ取得専用。対象地域の境界（Nominatim）と歩行者ネットワーク（Overpass）を取得・単純化する。geopandas・shapely・pandas・NetworkX（BSD-3-Clause）等を伴うため、実行時の依存に入れない。実行時の経路計算は保存済みグラフに対する自作の Dijkstra（`data.WalkGraph`、テスト済み）で、依存を増やさない | Overpass を直接叩いて自作でグラフ化。OSMnx は道路網の単純化と検証済みの取得処理を持つため採用 |
| `pytest`（dev） | 9.2.0 | MIT | テスト | unittest |

### EDEN SYSTEM（`apps/eden-system/`、独自の `uv.lock`）

補足の試作。直接依存は `flask` 3.1.3・`pillow` 13.0.0・`pydantic` 2.14.4・`pytest` 9.2.0（dev）で、上表と同じ版・ライセンス。
Leaflet 1.9.4 も同じ検証済みの配布物を同梱。追加の依存はない。

### 同梱するフロントエンド

| Package | Version | License | Purpose | Integrity |
|---|---|---|---|---|
| Leaflet | 1.9.4 | BSD-2-Clause | 地図表示、浸水想定タイルの重ね表示、経路・避難場所の描画。CDN を使わず `src/hinan/static/vendor/leaflet-1.9.4/` に同梱（LICENSE 同梱） | npm レジストリの `sha512-nxS1ynzJOmOlHp+iL3FyWqK89GtNL8U8rvlMOsQdTTssxZwCXh8N2NB3GDQOL+YR3XnWyZAxwQixURb+FA74PA==` と一致を確認 |

### Security

- 2026-11-24 `uv run --with pip-audit pip-audit --skip-editable`: **No known vulnerabilities found**（本構成で実行）。
- CSP で外部スクリプトを禁止し、画像は自サーバーと地理院タイルのみ許可。

### Verification

- `uv run --frozen pytest -q`
- `uv run --with pip-audit pip-audit --skip-editable`

## Required record per dependency

| 項目 | 記録内容 |
|---|---|
| Purpose | 解決する問題と、プロダクト価値に必要な理由 |
| Upstream | 正式名称、公式リポジトリ、配布元 |
| Version | 固定バージョンとロック方法 |
| License | SPDX識別子、商用・改変・再配布・表示義務、互換性 |
| Maintenance | 最終リリース、保守状況、バス係数、廃止予定 |
| Security | 既知の脆弱性、推移的依存、署名・ハッシュ、監査結果 |
| Alternatives | 標準機能、自作、別OSS、外部サービスとの比較 |
| Boundary | OSSへ任せる範囲、自作する範囲、置換インターフェース |
| Changes | 設定、パッチ、フォーク、上流との差分 |
| Verification | 動作、ライセンス、脆弱性、フォールバックの検証コマンド |

## Approval gate

各行の証拠を公式上流情報で確認し、ADRレビューが終わるまでパッケージやモデルを追加しない。
実装開始後は、ロックファイルと依存監査の出力をこの台帳へ接続する。
