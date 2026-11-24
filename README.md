# ハザードマップナビ — 今いる場所から、安全な避難先へ

南国アールスタジオ株式会社 AI エンジニア採用課題の提出物です。
提出経路は **A（企画）+ B（簡易プロトタイプ）**、C（既存の開発経験）は企画書の中で短く触れています。
ローカルで動かす試作で、公開デプロイはしていません。

- **企画書**: [docs/submission/hazardmap-navi-proposal.pdf](docs/submission/hazardmap-navi-proposal.pdf)（編集用 [.pptx](docs/submission/hazardmap-navi-proposal.pptx)）
- **画面キャプチャ**: [docs/submission/screenshots/](docs/submission/screenshots/)
- **評価結果**: [実際のAI](docs/evaluation/results.md) ／ [モック](docs/evaluation/results-mock.md)
- **設計の記録**: [ADR 0002（ハザードマップナビ）](docs/decisions/0002-evacuation-guide-stack.md)、[データ台帳](docs/architecture/data-inventory.md)、[OSS台帳](docs/architecture/open-source-inventory.md)
- **補足のアプリ**: [EDEN SYSTEM](apps/eden-system/)（場所と、AIが写真から見分けたモノにコメントを残す。[仕様](docs/product/eden-system-spec.md)、[ADR 0003](docs/decisions/0003-eden-system-stack.md)）

## 何ができるか（1画面・1機能）

対象地域（**大阪市此花区・埼玉県八潮市・埼玉県三郷市**）で、①地域 → ②災害の種類（津波・高潮・洪水・地震）→ ③今いる場所（現在地か地図のクリック）を選ぶと、

1. その地点の**想定浸水深**を、ハザードマップポータルのタイルの色から読み取って表示します（地図にも凡例付きで重ねます）。
2. 選んだ災害に**対応する指定緊急避難場所**だけを、OpenStreetMap の歩道網で計算した**徒歩経路が短い順に3件**示します。対応する場所がデータにない場合（例: 3地域とも高潮は0件）は、そう表示します。
3. **連絡先**（119・110・171と、その地域の役所）を表示します。
4. 画面右下の **「AIに質問」でチャット**が開きます。AI には計算済みの事実と公式資料（気象庁など）の抜粋だけを渡し、根拠にない数値や候補にない施設名を含む回答は表示しません。避難先や経路を AI が選ぶことはありません。

## 使ったオープンデータとOSS

| 種類 | 内容 |
|---|---|
| オープンデータ | 国土地理院 指定緊急避難場所データ、ハザードマップポータルサイト（浸水想定）、OpenStreetMap、地理院タイル |
| OSS | OSMnx（データ取得）、Leaflet（地図）、Flask、Pillow、Pydantic、pytest |
| AI | Claude（ローカルの Claude Code CLI 経由。静的な API キーは使わない） |

## 起動

[uv](https://docs.astral.sh/uv/) が必要です。

```bash
uv sync
uv run python -m hinan                                   # http://127.0.0.1:8765 （モックAI: 外部送信なし）
HINAN_AI_PROVIDER=claude uv run python -m hinan          # 実AI（ローカルの Claude Code の認証を使う）
```

`http://127.0.0.1:8765/?area=yashio&hazard=flood` や `?lat=34.68241&lon=135.4705&hazard=tsunami` のように、地域や地点を指定して開けます。

## 検証

```bash
./scripts/check.sh                                       # 両アプリのテスト + モック評価
uv run python scripts/run_eval.py --provider claude      # 実AIで13ケースを評価（docs/evaluation/results.md）
uv run --frozen --group data python scripts/fetch_data.py  # オープンデータの再取得（開発時のみ）
```

## AIの使い方と安全設計

| 論点 | 設計 |
|---|---|
| 命に関わる部分 | 浸水深・避難先の絞り込み・経路は決定的に計算する。AI は説明だけ |
| 根拠 | 気象庁・防災庁の公式ページから選んだ根拠カードを、災害の種類と状況で選んで渡す（RAG）。再学習はしない |
| 出力の検査 | スキーマ、数値と施設名が事実・根拠にあるかの検査、根拠IDの検査。違反したら表示しない |
| 外部送信 | 同意したときだけ。送るのは計算結果と質問文で、座標は送らない。質問文はログに残さない |
| Web | CSRF、CSP（インラインスクリプト禁止）、入力検証、127.0.0.1 のみで待受 |

## 限界

- これは採用課題の試作です。実際の避難では、各自治体・気象庁の最新の発表と現地の状況を優先してください。
- 浸水深は想定です。避難場所の開設・収容状況、通行止めや浸水中の通行可否は考慮していません。
- AI の検査は数値と施設名に限られ、一般論の混入は検出できません。
