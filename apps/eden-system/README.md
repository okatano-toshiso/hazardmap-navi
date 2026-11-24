# EDEN SYSTEM（補足の試作）

場所（緯度経度）と、写真から AI が見分けた建物・看板・モノにコメントを残すアプリ。その場所にいる人だけが書けます。
プライベート（友達だけ・24時間で消える）とパブリック（誰でも・AI が内容を確認）の2種類があります。
メインの提出物はリポジトリ直下のハザードマップナビで、これは補足です。仕様: [eden-system-spec.md](../../docs/product/eden-system-spec.md)、構成: [ADR 0003](../../docs/decisions/0003-eden-system-stack.md)。

## 起動

```bash
cd apps/eden-system
uv sync
uv run python -m eden                               # http://127.0.0.1:8766 （モックAI: 外部送信なし）
EDEN_AI_PROVIDER=claude uv run python -m eden       # 実AI（ローカルの Claude Code の認証を CLI 経由で利用）
```

デモ利用者は「あおい」「ゆうと」（友達同士）と「さくら」（友達なし）。PC では地図をクリックして「いる場所」を決め、方角はスライダーで変えます。
`?user=yuto&lat=35.68123&lon=139.76712&heading=0` のように指定して開けます。データは `instance/eden.db`（Git 管理外）に保存されます。

## 検証

```bash
uv run --frozen pytest -q
```

## 作らないこと・限界

- 人の顔や姿からの個人の特定はしません。人物が主に写った写真にはコメントを結び付けません。
- 在場判定はブラウザが送る位置で行うため、偽装は防げません。方位センサーの精度は端末によって差があります。
- 友達登録（招待・承認）、ログイン、広告は試作に含めません。
