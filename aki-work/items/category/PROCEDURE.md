# カテゴリ一括登録CSV 作成手順（item-cat_aki.csv）

`item-cat_aki.csv`（aki-select のカテゴリ一括登録CSV）を、
`item-cat_cocomomo.csv` のカテゴリ割当に合わせて**複数カテゴリへ展開**する手順。

- 商品は追加しない（`item-cat_aki.csv` に居る商品だけ）
- カテゴリ名・URL は AKI（aki-select）表記に変換
- 元ファイルは上書き前に自動バックアップ（`.bak-YYYYMMDDHHMMSS.csv`）

---

## 1. 使用するファイル

| ファイル | 役割 | 目安 |
|---|---|---|
| `items/category/category.xlsx` | **カテゴリ対応表**（COCOMOMO ID ⇔ AKI ID） | 68行 |
| `items/category/item-cat_aki.csv` | 更新対象（RMSからダウンロードしたカテゴリCSV） | 1,622行 / 423商品 |
| `items/category/item-cat_cocomomo.csv` | カテゴリ割当の正（sljapan1 のカテゴリCSV） | 8,189行 / 2,305商品 |
| `script/expand-item-cat-aki-categories.py` | 変換スクリプト | — |

対応表の列：`NO.` / `表示先カテゴリ` / `カテゴリ(COCOMOMO)` / `カテゴリ(AKI)`

```
item-cat_cocomomo.csv ──(カテゴリID)──┐
                                      ├─ category.xlsx ─→ AKI ID ─→ URL/カテゴリ名
item-cat_aki.csv（商品一覧）───────────┘
```

---

## 2. 変換ルール（1商品ずつ）

1. **カテゴリの採用元**：その商品が `item-cat_cocomomo.csv` で持つ行をすべて採用（CSVの並び順を維持）
2. **カテゴリ名**：`item-cat_aki.csv` に同じAKIカテゴリIDがあればその表記をそのまま使用。
   無ければ対応表の `表示先カテゴリ` を使い、区切りを `\`、波ダッシュを `～` に正規化
3. **URL**：`https://item.rakuten.co.jp/aki-select/c/{AKIカテゴリID}/`
4. **優先度**：COCOMOMO行の値をそのまま使用
5. **重複統合**：同じ商品×同じAKIカテゴリになる行は1行に統合（優先度が小さい方を残す）
   例）`グッズ\シューズ\サンダル` → `グッズ\シューズ`（親へ寄せた結果、既存行と重複）
6. **親カテゴリへ寄せる**：対応表に無いカテゴリは親へ遡って一致させる
   例）`トップス\ニット・セーター\ノースリーブ` が無ければ `トップス\ニット・セーター`
   それでも無ければ除外（レポートに表示）
7. **商品は増やさない**：COCOMOMO側にしか居ない商品（1,882商品）は対象外

**カテゴリ名の比較用正規化**（一致判定のみ／出力は上記2の表記）
`¥ ￥ ＼ → \`、`～ 〜 ∼ ~ → ~`、全角半角を統一、空白（全角含む）を除去

---

## 3. 作業手順

### Step 0. 作業場所

リポジトリ直下（`aki-work/`）で実行する。

```bash
cd /Users/mingpiao/EC_work/eclipse-workspace/aki-work
```

### Step 1. 素材を最新にする

- RMS からカテゴリCSVをダウンロードしたら `items/category/item-cat_aki.csv` に置く
- COCOMOMO 側も更新があれば `items/category/item-cat_cocomomo.csv` を差し替える
- 置き換えた場合は**文字コード（cp932）とヘッダー7列**が同じか確認

### Step 2. 対応表を更新する（カテゴリの追加・変更があったとき）

`category.xlsx` の `カテゴリ` シートに1行追加する。

| NO. | 表示先カテゴリ | カテゴリ(COCOMOMO) | カテゴリ(AKI) |
|---|---|---|---|
| 69 | 新カテゴリ | 0000000499 | 0000000077 |

- **COCOMOMO ID と AKI ID は必ずセット**で入れる（どちらか空の行は無視される）
- `表示先カテゴリ` の階層区切りは `¥` でも `\` でも可（比較時に正規化される）
- AKI 側にカテゴリが無い場合は、先に RMS でカテゴリを作成してから ID を記入する

### Step 3. 検証だけ実行する（書き込みなし）

```bash
python3 script/expand-item-cat-aki-categories.py --check-only
```

**確認するポイント**

| 出力 | 見方 |
|---|---|
| `出力 : N行 / M商品 / Kカテゴリ` | 商品数が元と**同じ**か（増えていないか） |
| `追加行` | 新しく増える商品×カテゴリの数 |
| `統合` | 親寄せで重複し1行になった数 |
| `優先度変更` | COCOMOMO の優先度に変わる既存行の数 |
| `対応表に無し` | 0 が望ましい。出たら Step 2 で対応表に追加 |
| `[OK]/[NG]` | NG は URL 形式か重複。NG が0になるまで進まない |

### Step 4. 本実行（`item-cat_aki.csv` を上書き）

```bash
python3 script/expand-item-cat-aki-categories.py --in-place
```

- 上書き前に `item-cat_aki.bak-YYYYMMDDHHMMSS.csv` が自動作成される
- バックアップを作らない場合は `--no-backup`（非推奨）
- 別ファイルに出力したい場合は `--in-place` を付けずに実行
  → `items/category/item-cat_aki-expanded.csv`

### Step 5. 結果を確認する

```bash
# 件数
python3 - <<'EOF'
import csv, io
from pathlib import Path
rows = list(csv.reader(io.StringIO(Path("items/category/item-cat_aki.csv").read_bytes().decode("cp932"))))
print("行数", len(rows) - 1, "商品", len({r[1] for r in rows[1:]}), "カテゴリ", len({r[3] for r in rows[1:]}))
EOF
```

- レポート `items/category/report-item-cat-aki-expand.csv` を Excel で開き、
  `区分` 列（追加／優先度変更／変更なし）を確認
- スクリプト実行時にサンプル商品 `sa10886` の展開結果が表示される

### Step 6. RMS へアップロード

- `items/category/item-cat_aki.csv`（cp932 / CRLF / データ行は全項目クォート）をそのまま使用
- アップロード後、商品ページで「その他」が消え、複数カテゴリに入っていることを数点確認

### Step 7. 元に戻す

```bash
cp items/category/item-cat_aki.bak-YYYYMMDDHHMMSS.csv items/category/item-cat_aki.csv
```

---

## 4. 現在の実行結果（2026-11-20 時点）

| 項目 | 値 |
|---|---|
| 行数 | 1,360 → **1,622**（+262） |
| 商品数 | **423**（増減なし） |
| カテゴリ数 | 57 |
| 追加した商品×カテゴリ | 339 |
| 廃止（その他 0000000001） | 77 |
| 優先度を COCOMOMO に変更 | 73 |
| 統合 | 26 |
| 対応表に無し | 0 |

展開例（`sa10886`）

```
2026新作アイテム                         9998456  .../aki-select/c/0000000002/
2026新作アイテム\【10/26～11/1】新作UP！   9998456  .../aki-select/c/0000000023/
トップス                                 9998456  .../aki-select/c/0000000005/
トップス\ニット・セーター\長袖             9998456  .../aki-select/c/0000000038/
オフィスカジュアル\ニット・セーター         9998456  .../aki-select/c/0000000067/
```

---

## 5. 注意点

- **冪等**：同じ状態で再実行しても `追加行 0 / 優先度変更 0`（二重に増えない）。安心して `--check-only` を繰り返せる
- **文字コード・書式**：cp932 / CRLF / 1行目のみ最小クォート・データ行は全項目クォート（RMSのダウンロードCSVと同じ）。Excel で開いて保存し直すと書式が変わるので、編集はスクリプト経由にする
- **「その他」が残る**：対応表に該当が無い商品。`report-item-cat-aki-expand.csv` と `report-item-cat-aki-urlfix.csv` で確認
- **週次カテゴリが親に寄る**：`2026新作アイテム\【11/9～11/15】新作UP！` `【11/16～11/22】` は対応表に無いため `2026新作アイテム` に入る。AKI側に週カテゴリを作った場合は `category.xlsx` に追記して再実行（その週の行が独立する）
- **カテゴリ名の区切り**：出力は `\`（RMSの表記）。スプレッドシート上の `¥` とは見た目が違うが同じ階層区切り
- **大量の優先度1重複**：同一カテゴリ内で優先度が同じ行が増えると表示順が不定になるため、必要なら RMS 側で優先度を調整

---

## 6. 関連スクリプト

| スクリプト | 用途 |
|---|---|
| `script/expand-item-cat-aki-categories.py` | **本手順**：COCOMOMOの複数カテゴリへ展開（行を増やす） |
| `script/fix-item-cat-aki-url-from-cocomomo.py` | 行を増やさず URL だけ差し替え（`--sync-name` でカテゴリ名も同期） |
| `script/convert-cocomomo-cat-to-aki.py` | 逆方向：COCOMOMO のCSVを AKI 用に変換（商品数はそのまま） |

いずれも `--check-only` で事前確認できる。
