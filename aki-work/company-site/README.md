# CRESCENT コーポレートサイト

Crescent株式会社（クレッセント）の会社サイト。**静的HTML/CSS/JS**（ビルド不要・外部CDNなし）。

```
company-site/
├── index.html              1ページ完結（TOP / ABOUT / BUSINESS / COMPANY / ACCESS / CONTACT）
└── assets/
    ├── css/style.css       デザイントークン＋全スタイル
    ├── js/main.js          ヘッダー制御・モバイルメニュー・スクロール表示
    └── img/
        ├── ogp.jpg         SNSシェア用画像（1200×630）
        ├── favicon.svg
        └── logo.svg
```

## ローカル確認

```bash
# そのまま開く
open company-site/index.html

# ローカルサーバ経由（推奨：相対パス・地図の挙動が本番に近い）
cd company-site && python3 -m http.server 8000
# → http://localhost:8000/
```

## 公開前に必ず差し替える箇所

| 箇所 | 現在の値 | 対応 |
|---|---|---|
| メールアドレス | `info@example.com` | 実際のアドレスへ |
| OGP / canonical のURL | `https://example.com/` | 本番ドメインへ（`index.html` の `og:*` と JSON-LD の `url`） |
| 取扱いアイテム数 | `1000+`（累計） | 実数に合わせる（ABOUT の `stats`） |
| 交通案内 | 飯田橋駅 徒歩3〜4分 | 実際の最寄りに合わせて確認 |
| 地図 | Google Maps 埋め込み | 表示されない場合は枠下の「Googleマップで見る」で代替 |

## 内容の編集ポイント

- **会社概要**：`index.html` の `<section id="company">` 内 `<table class="table">`
  - 商号 / 設立 / 代表取締役社長 / 所在地 / 電話番号 / 事業内容
- **英文住所**：同セクションの `.company-en`（`CRESCENT CO.,LTD` / 住所）
- **ヒーローコピー**：`.hero__title`（`<span class="hl">` がゴールドのハイライト）
- **色・余白**：`assets/css/style.css` 冒頭 `:root` のトークン
  - `--ink` 文字色（濃紺） / `--paper` 背景 / `--gold` アクセント
  - `--w` コンテンツ幅 / `--sec` セクション余白 / `--serif-en`・`--serif-ja` 書体

## 実装メモ

- レイアウトは CSS Grid / `clamp()` による流体サイズ。ブレークポイントは 980px・760px。
- アニメーションは `[data-reveal]` + IntersectionObserver。
  **JS 無効時は `html.no-js` により全コンテンツが表示される**（`head` 内のインラインスクリプトで `js` クラスへ切替）。
- `prefers-reduced-motion` を尊重。
- 使用書体はOS標準（Didot / Bodoni 72 / ヒラギノ明朝 / ヒラギノ角ゴシック）でフォールバックあり。
  Webフォントを当てる場合は `:root` の `--serif-en` / `--serif-ja` を差し替える。
- 電話番号は `tel:` リンク、`format-detection` でiOSの自動リンク化を無効化。

## デプロイ

そのまま `company-site/` の中身を任意の静的ホスティングへ配置（Netlify / Vercel / GitHub Pages / レンタルサーバのFTP）。
サーバ設定例：

- `index.html` をディレクトリインデックスに
- HTTPS 化（`http://` → `https://`）
- 404 ページ（任意）
- 圧縮（gzip / brotli）とキャッシュ（`assets/` は長期キャッシュ可、`index.html` は短め）

## 注意

- 会社概要の代表者氏名・生年月日などの個人情報は、公開範囲を社内で確認のうえ掲載してください。
- 地図の埋め込みは Google の利用規約に従ってください。
