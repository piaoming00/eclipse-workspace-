---
name: image-edit
description: aki-select 用の画像編集スキル。背景削除（透過PNG化）、画像の取得（URL/ローカル）、複数画像の1枚への合成、背景画像の作成（くすみカラーパレット対応）を Python/Pillow スクリプトで行う。商品画像の加工・バナー素材作成・商品ページ用画像の準備に使用する。
---

## 環境（パス）

- プロジェクトルート: `/Users/mingpiao/EC_work/eclipse-workspace/aki-work`
- 以下、`resources/`・`output/`・`work/`・`img/`・`design/` 等の相対パスはすべて上記ルート配下を指す

# Image Edit（aki-select 画像編集）

AI画像生成は使わない。**決定論的な画像処理**（Pillow）で行う。
店舗デザイン規約は `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/AGENTS.md` に従う。

## 鉄則（ハード制約）

1. `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/resources/` は**読み取り専用**。書き込みは `output/` か `work/` のみ
   （スクリプトは resources/ への書き込みを拒否する）
2. **既存ファイルの上書き禁止**。出力先が存在する場合はスクリプトがエラーを出すので
   `<用途>_<YYYYMMDD>_<連番>.png` の連番を進める
3. 生成物は `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/output/` 配下を基本とする
4. 加工ログは自動で `output/image_edit_log.csv` に追記される（元画像名・加工内容が残る）
5. 背景色・文字色は §くすみカラーパレット を使う（原色・蛍光色は禁止）

## Setup

- Python 3.12 + Pillow + numpy（この環境には導入済み）
- スクリプト: `/Users/mingpiao/EC_work/eclipse-workspace/aki-work/.skills/image-edit/scripts/image_edit.py`（SKILL.md からの相対パス: `scripts/image_edit.py`）

## 1. 背景削除（remove-bg）

端から連結した背景色領域を検出して透明化する。**白い服など内部の類似色は残る**（連結判定のため）。

```bash
# 自動判定（4隅から背景色を推定）
python scripts/image_edit.py remove-bg --input <元画像> --out <出力.png>

# 許容差・背景色を明示
python scripts/image_edit.py remove-bg --input <元画像> --out <出力.png> --tolerance 40 --color "#FFFFFF"
```

| オプション | 既定 | 説明 |
|---|---|---|
| `--tolerance` | 30 | 背景とみなす色差。取り残しがあれば上げる（40〜60） |
| `--color` | 自動（4隅） | 背景色。パレット名 / `#RRGGBB` / `R,G,B` |
| `--feather` | 1 | エッジのぼかしpx。0で無効 |

出力は常に**透過PNG**。結果は必ず目視確認する（髪の毛・細部の取り残しが無いか）。

## 2. 画像を取得（fetch）

URLからダウンロード、またはローカル原本（resources/ 等）を**複製**する。原本は変更されない。

```bash
python scripts/image_edit.py fetch --source https://... --out <出力.jpg>
python scripts/image_edit.py fetch --source /Users/mingpiao/EC_work/eclipse-workspace/aki-work/resources/aki01/akipop/<画像>.jpg --out <出力.jpg>
```

## 3. 複数の画像を1つに（combine）

```bash
# グリッド（既定: 1列に自動詰め、背景 oatmeal）
python scripts/image_edit.py combine A.jpg B.jpg C.jpg --out <出力.png> --mode grid --cols 3

# 縦連結 / 横連結
python scripts/image_edit.py combine A.jpg B.jpg --out <出力.png> --mode vertical
python scripts/image_edit.py combine A.jpg B.jpg --out <出力.png> --mode horizontal

# カットアウト（透過PNG）を背景に並べる（商品コレクション用）
python scripts/image_edit.py combine a.png b.png c.png --out <出力.png> --mode paste --height 800 --background beige
```

| オプション | 既定 | 説明 |
|---|---|---|
| `--mode` | grid | `grid` / `vertical` / `horizontal` / `paste` |
| `--cols` | 自動 | grid の列数 |
| `--gap` | 20 | 余白px |
| `--background` | oatmeal | 背景色（paste モードでは必須推奨） |
| `--size` | 自動 | grid のセルサイズ `WxH` |

## 4. 背景を作成（background）

```bash
# 単色（500x500 のカテゴリアイコン用下地など）
python scripts/image_edit.py background --size 500x500 --color oatmeal --out <出力.png>

# 縦グラデーション（バナー用）
python scripts/image_edit.py background --size 980x400 --color cream --color2 beige --out <出力.png>
```

## くすみカラーパレット（AGENTS.md §4.1 と同じ。パレット名で指定可能）

| パレット名 | 色 | 用途 |
|---|---|---|
| `oatmeal` | `#F2EDE4` | ベース（デフォルト） |
| `cream` | `#F7F3EC` | トップス |
| `pink` | `#F5E0E0` | ワンピース |
| `beige` | `#EFE6D8` | ボトムス |
| `gray` | `#E6E4E1` | アウター |
| `lavender` | `#E9E4EF` | インナー |
| `sage` | `#DCE4D8` | グッズ |
| `bluegray` | `#E0E4E8` | オフィスカジュアル |
| `softred` | `#F5DEDE` | SALE |
| `softyellow` | `#F6EFD9` | 新作 |
| `linegray` | `#8A7F70` | 線（メイン） |
| `fillbeige` | `#B7A99A` | 塗り（メイン） |
| `textbrown` | `#5A5048` | 文字 |
| `accentred` | `#BF6B6B` | アクセント |

## よくある作業の型

**商品画像をRMS用に整える:**
1. `fetch` で原本を複製 → `output/`
2. `remove-bg` で透過PNG化 → 目視確認
3. `background` で店舗用背景（oatmeal 等）を作成
4. `combine --mode paste` で背景にカットアウトを配置

**Before/After の提示:** RMSへ反映する成果物は、加工前後を並べて人間の承認を得てから確定する（AGENTS.md §7）。
