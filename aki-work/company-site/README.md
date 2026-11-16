# CRESCENT コーポレートサイト

Crescent株式会社（クレッセント）の会社サイト。**静的HTML/CSS/JS**（ビルド不要・外部CDNなし）。

```
company-site/
├── index.html              1ページ完結（TOP / ABOUT / BUSINESS / STORE / COMPANY / ACCESS / CONTACT）
└── assets/
    ├── css/style.css       デザイントークン＋全スタイル
    ├── js/main.js          ヘッダー制御・モバイルメニュー・スクロール表示
    └── img/
        ├── aki-shop-banner.jpg     楽天市場店「AKI」店舗バナー（1206×402）
        ├── aki-shop-banner-02.jpg  同（ワイド 1206×302）
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

## 楽天市場店「AKI」へのリンク

| 用途 | URL |
|---|---|
| 店舗トップ | https://www.rakuten.co.jp/aki-select/ |
| カテゴリ一覧 | https://item.rakuten.co.jp/aki-select/c/ |
| ショップコード | `aki-select` |

掲載箇所：`#shop`（オンラインストア）セクション、ヒーロー副CTA、ABOUT本文、BUSINESSカード02、
フッター、JSON-LD の `sameAs`。店舗URLを変更する場合はこの6箇所をまとめて置換してください。

```bash
grep -n "www.rakuten.co.jp/aki-select" index.html
```

## 公開前に必ず差し替える箇所

| 箇所 | 現在の値 | 対応 |
|---|---|---|
| メールアドレス | `info@example.com` | 実際のアドレスへ |
| OGP / canonical のURL | `https://example.com/` | 本番ドメインへ（`index.html` の `og:*` と JSON-LD の `url`） |
| 取扱いアイテム数 | `1000+`（累計） | 実数に合わせる（ABOUT の `stats`） |
| 交通案内 | 飯田橋駅 徒歩3〜4分 | 実際の最寄りに合わせて確認 |
| 地図 | Google Maps 埋め込み | 表示されない場合は枠下の「Googleマップで見る」で代替 |
| 店舗バナー | `img/top/IMG_1674-4k-shop-wall.jpg` を流用 | 差し替える場合は `assets/img/aki-shop-banner*.jpg` を上書き |

## 内容の編集ポイント

- **会社概要**：`index.html` の `<section id="company">` 内 `<table class="table">`
  - 商号 / 設立 / 代表取締役社長 / 所在地 / 電話番号 / 事業内容
- **英文住所**：同セクションの `.company-en`（`CRESCENT CO.,LTD` / 住所）
- **オンラインストア**：`<section id="shop">`
  - `shop__visuals`（2枚のバナー） / `shop__meta`（ショップ名・コード・取扱い） / `shop__url`
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

## デプロイ（公開）

> **STUDIO（studio.site）では公開できません。**
> STUDIO はノーコードのサイトビルダーで、外部で作成した静的HTML一式をそのまま取り込む機能はありません。
> STUDIO を使う場合は、本サイトのデザインを STUDIO 上で組み直す必要があります（`カスタムコード` で head/body への追記は可能）。
> 本サイト（静的HTML）は以下いずれかへ配置してください。

### 1. 一時公開（ローカルから / アカウント不要）

```bash
cd company-site
python3 -m http.server 8080 --bind 127.0.0.1
# 別ターミナルで（cloudflared のバイナリは /tmp 等に置いてOK）
cloudflared tunnel --url http://127.0.0.1:8080
# 表示された https://xxxx.trycloudflare.com が公開URL（PCを閉じると停止・URLは毎回変わる）
```

### 2. Netlify Drop（最短・無料・HTTPS）

1. https://app.netlify.com/drop を開く
2. `company-site` フォルダをドラッグ＆ドロップ
3. 発行された `https://xxxx.netlify.app` で公開（アカウント連携で保持・独自ドメイン可）

CLI 派：`npx netlify-cli deploy --dir=company-site --prod`

### 3. Vercel / Cloudflare Pages / GitHub Pages

```bash
# Vercel（静的サイトとしてそのまま配信）
npx vercel --prod company-site
```

- Cloudflare Pages：リポジトリ連携 or `npx wrangler pages deploy company-site`
- GitHub Pages：`company-site/` を `gh-pages` ブランチへ push → Settings > Pages

### 4. レンタルサーバ（Xserver / ロリポップ等）

FTP で `company-site/` の中身を公開ディレクトリ（例 `public_html/`）へアップロード。
日本語ファイル名がないため文字化けの心配はありません。

### 公開後にやること

1. `index.html` の `https://example.com/` を本番ドメインへ（`og:url` / JSON-LD `url`）
2. `og:image` を **絶対URL** に変更（例 `https://example.com/assets/img/ogp.jpg`）— 相対URLだとSNSカードで画像が出ません
3. メールアドレス `info@example.com` を実アドレスへ
4. サーバ設定：HTTPS（常時SSL）、`index.html` をディレクトリインデックスに、
   `assets/` は長期キャッシュ（`Cache-Control: max-age=31536000, immutable`）、`index.html` は短め
5. Google Search Console へサイトマップ（任意で `sitemap.xml` を作成）を送信

## 注意

- 会社概要の代表者氏名・生年月日などの個人情報は、公開範囲を社内で確認のうえ掲載してください。
- 地図の埋め込みは Google の利用規約に従ってください。
