# 商品画像ダウンロードツール 使い方

スクリプト: `script/download-akipop-images.py`

楽天GOLD画像サーバの cabinet フォルダから、**指定した商品コードの画像だけ**を漏れなく取得する。

```
https://image.rakuten.co.jp/sljapan1/cabinet/07985602/{商品コード}/...
  → img/aki01/akipop/{商品コード}/{ファイル名}
```

---

## 1. クイックスタート

```bash
cd /Users/mingpiao/EC_work/eclipse-workspace/aki-work

# ① 対象URLの洗い出しだけ（ダウンロードしない・約2分）
python3 script/download-akipop-images.py --dry-run

# ② ダウンロード（既にある画像はスキップ）
python3 script/download-akipop-images.py

# ③ 結果確認
ls img/aki01/akipop/sa10899 | wc -l
open output/download_images_akipop.csv
```

## 2. 対象商品の指定

`img/aki01/akipop/item_list` に商品コードを書く（このファイルのコードだけが対象）。

```
sa10899
sa10949
```

- 1行1コード／カンマ・空白区切りも可／`#` 以降はコメント／BOM付きも可
- 保存先が `img/item_list` の場合は自動でそちらを使う（`[WARN]` 表示）
- 一時的に別リストを使うときは `--list path/to/list.txt`

## 3. オプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--list` | `img/aki01/akipop/item_list` | 商品コード一覧 |
| `--out` | `img/aki01/akipop` | 保存先ルート（`<out>/<code>/<ファイル名>`） |
| `--report` | `output/download_images_akipop.csv` | 取得ログ（追記） |
| `--shop` | `sljapan1` | 店舗コード |
| `--cabinet` | `07985602` | cabinetフォルダ番号 |
| `--workers` | `8` | 並列数（速くしたいとき上げる） |
| `--max-n` | `200` | 連番の上限（`1.jpg〜200.jpg` まで確認） |
| `--gap` | `5` | 規則展開で「連続○回なし」で打ち切る数 |
| `--deep` | off | 辞書と探索範囲を広げる（見つからないとき） |
| `--force` | off | 既存ファイルも取り直す |
| `--dry-run` | off | URLの洗い出しのみ（保存しない） |

## 4. 動作の流れ（1商品ごと）

1. **商品ページ解析** … `https://item.rakuten.co.jp/sljapan1/{code}/` を取得し、
   `/cabinet/07985602/{code}/` 配下の画像を全ホスト分（image / tshop / shop.r10s.jp）抽出
   - `_color01` や `_sku_01` のように、命名規則では推測しづらいファイルはここで拾う
   - 商品ページが404の商品はこの経路が0枚になる（次の2・3で補完）
2. **命名規則の総当たり** … `1.jpg〜` / `{code}.jpg` / `{code}_{n}` / `{code}_{word}` /
   `{code}_{word}{n}` / `{code}_{word}_{nn}` などをHEADで確認（約2,000パターン）
3. **規則展開** … 見つかった名前の連番を延長
   - `sa10899_lp_05.jpg` → `lp_06, 07, 08…` / `sa10899_sku_02.jpg` → `sku_03…`
4. **ダウンロード** … 画像と確認できたものだけ保存（JPEG/PNG/GIF/WEBPのマジックバイト検査、
   1KB未満やHTMLは保存しない）
5. **ログ** … 1URL=1行で `output/download_images_akipop.csv` に追記

同じ商品を再実行しても、既存ファイルは `skipped` になり二重取得しない（`--force` で再取得）。

## 5. 出力

**画像**: `img/aki01/akipop/{code}/{ファイル名}`（サーバー上のファイル名をそのまま使用）

**ログ**: `output/download_images_akipop.csv`

| 列 | 内容 |
|---|---|
| datetime | 実行日時 |
| code | 商品コード |
| filename | 保存ファイル名 |
| source | `item-page` / `probe` / `derive`（どこで見つけたか） |
| bytes | サイズ |
| status | `saved` / `skipped` / `failed(…)` |
| url | 取得元URL |

**画面のまとめ**: コードごとに `page / probe / derive / total / 保存 / skip / 失敗` を表示。

## 6. よくある使い方

```bash
# 商品を追加したとき … item_list に追記して実行
python3 script/download-akipop-images.py

# 画像を差し替えたので取り直したい
python3 script/download-akipop-images.py --force

# いつもの命名で見つからない商品がある
python3 script/download-akipop-images.py --deep --max-n 400

# 速くしたい（並列数を上げる）
python3 script/download-akipop-images.py --workers 16

# 別店舗・別cabinetを対象にする
python3 script/download-akipop-images.py --shop sljapan1 --cabinet 07922356 --out /tmp/imgs

# 対象URLだけ確認（1件ずつ表示）
python3 script/download-akipop-images.py --dry-run --list /tmp/one.txt
```

## 7. 判定と終了コード

- 全商品で1枚以上の画像が取得でき、失敗0 → `[OK]`（終了コード 0）
- 画像0枚の商品がある、または取得失敗がある → `[NG]`（終了コード 1）
  - NGのURLは `[NG] …` として標準エラーに表示され、ログの `status` にも残る

## 8. トラブルシューティング

| 症状 | 対処 |
|---|---|
| 画像が0枚 | 商品コードの綴り、`--shop`/`--cabinet` を確認。`--dry-run` で対象URLが出るか見る |
| 一部しか取れない | 独自命名の可能性。`--deep --max-n 400` を試す。それでも出ない場合は `script/download-akipop-images.py` の `WORDS` に語句を追加 |
| `failed(取得不可)` | 一時的な通信エラーか、URLが古い。再実行（既存はスキップされる） |
| `failed(画像でない)` | 画像URLではなくHTMLが返っている。cabinetパスを確認 |
| 実行が遅い | 総当たりで約2分/2コード。`--workers` を上げる、`--max-n` を下げる（探索範囲は狭くなる） |
| `[ERROR] 商品コード一覧が見つかりません` | `img/aki01/akipop/item_list` を用意する（`img/item_list` があれば自動使用） |

## 9. 注意

- cabinetフォルダは **一覧取得ができない**（フォルダURLは404）。そのため
  「商品ページ参照＋命名規則の総当たり＋規則展開」で取得しており、
  辞書に無い独自命名のファイルは原理的に検出できない
- 商品ページが404の商品は、連番・命名規則の探索のみになる
- 画像は再配布しない前提の作業用コピー。`--report` のログは追記式なので、
  実行回数分だけ行が増える
