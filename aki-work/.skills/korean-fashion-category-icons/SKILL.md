---
name: korean-fashion-category-icons
description: |
  韓国スタイル（K-fashion）の婦人服を販売するECサイト（aki-select）の
  カテゴリーアイコンメニュー画像を SVG/HTML/CSS で生成するスキル。
  カテゴリごとの配色・図形モチーフ・サイズ・文字位置を統一し、
  楽天RMSのコンテンツページ／カテゴリメニューへ貼り付け可能なHTMLを出力する。
  カテゴリアイコン、カテゴリメニュー、SVGアイコン生成、韓国風アイコンの依頼で使う。
---

## 環境（パス）

- プロジェクトルート: `/Users/mingpiao/EC_work/eclipse-workspace/aki-work`
- 以下、`resources/`・`output/`・`work/`・`img/`・`design/` 等の相対パスはすべて上記ルート配下を指す

# カテゴリアイコン生成スキル（SVG/HTML/CSS）

韓国スタイル（K-fashion）の婦人服ECサイト（aki-select）の**カテゴリーアイコンメニュー画像**を、
SVG/HTML/CSS で生成するためのスキル。

## 1. 目的

- 楽天店舗（aki-select）のカテゴリーメニューに使う**シンプルな図形アイコン**をコード（SVG/HTML/CSS）で生成する。
- 外部画像生成AIを使わず、**再現可能・差し替え可能**な形で管理する。
- 生成物は RMS のコンテンツページ／カテゴリメニューへ貼り付け可能な形にする。

## 2. いつ使うか

- カテゴリーメニュー（トップス / ワンピース / ボトムス / アウター 等）のアイコンが必要なとき
- 新カテゴリ追加・季節キャンペーン（SALE・新作）のアイコンを作るとき
- 既存アイコンの配色・サイズを統一したいとき

## 3. デザイン仕様（韓国スタイル）

### 3.1 基本サイズ

| 項目 | 値 |
|------|-----|
| 推奨サイズ | 500×500 px（SVGは `viewBox="0 0 500 500"`） |
| メニュー表示 | 250×250 / 150×150 に縮小しても崩れないこと |
| 背景 | 単色ベタ（透過は使わない） |

### 3.2 配色（韓国風パステル・ニュートラル）

**背景色（カテゴリごとに使い分ける）：**

| 用途 | カラー | コード |
|------|--------|--------|
| ベース（デフォルト） | オートミール | `#F2EDE4` |
| トップス | クリーム | `#F7F3EC` |
| ワンピース | 淡ピンク | `#F5E0E0` |
| ボトムス | ライトベージュ | `#EFE6D8` |
| アウター | ライトグレー | `#E6E4E1` |
| インナー | 淡ラベンダー | `#E9E4EF` |
| グッズ | セージ | `#DCE4D8` |
| オフィスカジュアル | ライトブルーグレー | `#E0E4E8` |
| SALE / セール | 淡レッド | `#F5DEDE` |
| 新作 | 淡イエロー | `#F6EFD9` |
| その他 | ライトグレー | `#EDEDED` |

**線・文字色：**

| 用途 | コード |
|------|--------|
| 図形の線（メイン） | `#8A7F70`（ブラウングレー） |
| 図形の塗り（メイン） | `#B7A99A`（ベージュグレー） |
| 文字（カテゴリ名） | `#5A5048`（ダークブラウン） |
| アクセント（SALE等） | `#BF6B6B`（くすみレッド） |

### 3.3 テイスト

- **ゆる・きれいめ・フェミニン**（韓国ファッションの定番トーン）
- 原色は使わない。すべて**くすみカラー**で統一
- 線は細め（`stroke-width: 2〜3`）、角は少し丸める（`stroke-linejoin: round`）
- 文字は細めのゴシック（`Noto Sans JP` / `Yu Gothic`）

## 4. カテゴリ一覧とアイコンコンセプト

楽天RMS（aki-select）の主要カテゴリと、アイコンの図形モチーフ。

| カテゴリ | 図形モチーフ | 背景色 |
|----------|-------------|--------|
| トップス | Tシャツ／ニット（半袖トップの輪郭） | `#F7F3EC` |
| ワンピース | ワンピース（Aラインのドレス輪郭） | `#F5E0E0` |
| ボトムス | スカート／パンツ（台形） | `#EFE6D8` |
| アウター | コート／ジャケット（長方形＋襟） | `#E6E4E1` |
| インナー | キャミソール（細い肩紐のトップ） | `#E9E4EF` |
| グッズ | バッグ／帽子（かごバッグ形） | `#DCE4D8` |
| オフィスカジュアル | シャツ＋スカート（きれいめ） | `#E0E4E8` |
| セット売り | 上下セット（トップ＋ボトム） | `#F2EDE4` |
| 裏起毛アイテム | もこもこニット（波線の縁） | `#F2EDE4` |
| UVケアアイテム | 日傘／太陽（丸＋線） | `#F6EFD9` |
| リゾートアイテム | ワンピ＋帽子（リゾート） | `#DCE4D8` |
| SALE | 「SALE」の文字（大きめ）＋下線 | `#F5DEDE` |
| 2026新作アイテム | 星／「NEW」の文字 | `#F6EFD9` |
| その他 | 三点リーダー（…）またはハート | `#EDEDED` |

## 5. SVG生成ルール

### 5.1 共通テンプレート

```html
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500" width="500" height="500" role="img" aria-label="【カテゴリ名】">
  <!-- 背景 -->
  <rect x="0" y="0" width="500" height="500" rx="40" fill="【背景色】"/>
  <!-- 図形（カテゴリ別モチーフ） -->
  【図形パス】
  <!-- カテゴリ名テキスト -->
  <text x="250" y="440" text-anchor="middle"
        font-family="'Noto Sans JP','Yu Gothic',sans-serif"
        font-size="44" font-weight="500" fill="#5A5048">【カテゴリ名】</text>
</svg>
```

### 5.2 図形の描き方（基本パス）

線は `stroke="#8A7F70" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" fill="none"` を基本にする。

**例：トップス（半袖Tシャツ）**
```html
<g stroke="#8A7F70" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" fill="none">
  <path d="M170 200 L155 250 L175 340 L325 340 L345 250 L330 200 Z"/>
  <path d="M205 200 Q250 230 295 200"/>
  <path d="M170 200 L130 255 M330 200 L370 255"/>
</g>
```

**例：ワンピース（Aラインドレス）**
```html
<g stroke="#8A7F70" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" fill="none">
  <path d="M210 190 L195 200 L170 360 L330 360 L305 200 L290 190 Z"/>
  <path d="M220 190 Q250 210 280 190"/>
  <path d="M215 190 L185 245 M285 190 L315 245"/>
</g>
```

**例：ボトムス（スカート）**
```html
<g stroke="#8A7F70" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" fill="none">
  <path d="M200 200 L320 200 L350 370 L150 370 Z"/>
  <path d="M220 200 L240 240 M280 200 L260 240"/>
</g>
```

**例：SALE（文字ベース）**
```html
<text x="250" y="250" text-anchor="middle" font-family="'Arial Black','Noto Sans JP',sans-serif"
      font-size="130" font-weight="900" fill="#BF6B6B">SALE</text>
<line x1="150" y1="285" x2="350" y2="285" stroke="#BF6B6B" stroke-width="6" stroke-linecap="round"/>
```

## 6. HTML/CSSメニューの実装

### 6.1 メニュー構造（カテゴリグリッド）

```html
<style>
  .cat-menu { display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; }
  .cat-item { width: 150px; text-align: center; text-decoration: none; }
  .cat-item img { width: 150px; height: 150px; border-radius: 12px; display: block; }
  .cat-item span { display: block; margin-top: 6px; color: #5A5048; font-size: 13px; }
  .cat-item:hover img { opacity: .85; }
</style>

<div class="cat-menu">
  <a class="cat-item" href="https://item.rakuten.co.jp/aki-select/c/0000000005/">
    <img src="【アイコンURL】/tops.svg" alt="トップス"><span>トップス</span>
  </a>
  <!-- 各カテゴリを繰り返す -->
</div>
```

### 6.2 RMSへ貼り付ける場合

1. SVG を PNG 化（500×500）するか、そのまま `<img>` の `src` にSVG URLを指定
2. RMS の「コンテンツページ編集」→ HTMLパーツ に上記HTMLを貼り付け
3. リンク先は各カテゴリのURL（`https://item.rakuten.co.jp/aki-select/c/【カテゴリ(AKI)】/`）を指定

## 7. 出力規約

| 項目 | 値 |
|------|-----|
| 保存先 | `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/output/category_icons/` |
| ファイル名 | `<カテゴリ英字>_<サイズ>.svg`（例：`tops_500.svg`, `sale_500.svg`） |
| 一覧生成 | カテゴリ一覧は `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/resources/カテゴリ.md` の「カテゴリ(AKI)」を正とする |
| 検証 | 生成後、全アイコンが同一 `viewBox`・同一文字位置であることを確認 |

## 8. カテゴリ(AKI) ID対応表（リンク用）

| 表示先カテゴリ | カテゴリ(AKI) | URL |
|----------------|---------------|-----|
| トップス | 0000000005 | https://item.rakuten.co.jp/aki-select/c/0000000005/ |
| ワンピース | 0000000006 | https://item.rakuten.co.jp/aki-select/c/0000000006/ |
| ボトムス | 0000000007 | https://item.rakuten.co.jp/aki-select/c/0000000007/ |
| アウター | 0000000008 | https://item.rakuten.co.jp/aki-select/c/0000000008/ |
| インナー | 0000000009 | https://item.rakuten.co.jp/aki-select/c/0000000009/ |
| グッズ | 0000000010 | https://item.rakuten.co.jp/aki-select/c/0000000010/ |
| オフィスカジュアル | 0000000011 | https://item.rakuten.co.jp/aki-select/c/0000000011/ |
| セット売り | 0000000015 | https://item.rakuten.co.jp/aki-select/c/0000000015/ |
| SALE | 0000000019 | https://item.rakuten.co.jp/aki-select/c/0000000019/ |

> 注：`カテゴリ.md`（または `カテゴリ.xlsx`）が最新の正。ここは主要カテゴリのみ抜粋。

## 9. 生成手順（エージェント向け）

1. `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/resources/カテゴリ.md` を読んで対象カテゴリを確定する
2. 各カテゴリについて §5 のテンプレートに従い SVG を生成する
3. §3.2 の配色・§4 のモチーフ表に従う（勝手に色を変えない）
4. 出力は `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/output/category_icons/` へ保存
5. §6 の HTML/CSS でメニューを組み立て、リンクは §8 の URL を使う
6. 完成後、`/Users/mingpiao/EC_work/eclipse-workspace/aki-work/output/category_icons/README.md` に生成物一覧を書く
