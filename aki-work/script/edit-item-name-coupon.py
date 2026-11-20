#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normal-item CSV の商品名のクーポン表記を差し替える。

  変更前: 【11/18！クーポンで3,648円, 40%OFF】ワンピース ...
  変更後: 【11/21！クーポンで3,645円, 40%OFF】ワンピース ...

参照元（02.AKI単価設定.xlsx）
  - 日付      : 指定セル（既定 F2）
  - 単価      : 価格表の M列（40%OFF後価格）。行は「主SKU」で商品と突き合わせ
  - OFF率     : 指定セル（既定 F4 = 0.4 → 40%OFF）
  - 【】が無い商品名には 【】 を付けて差し替え
  - 商品名は cp932 換算で最大255byteに切り詰め（--max-bytes / --no-truncate）

主なオプション
  --dry-run            変更内容の確認のみ（ファイルを書かない）
  --date 11/21         F2が空のときの日付指定
  --shape full         常に「日付！クーポンで価格円, 40%OFF」に揃える（既定）
  --preserve-shape     元の形を保つ（OFF表記が無ければ追加しない / OUTLET維持）
  --multi min|max|first|closest   1商品に複数SKU行がある場合の単価の選び方（既定 min）
  --max-bytes 255      商品名の上限バイト数（cp932換算）
  --in-place           CSVを上書き（.bak 自動作成）

使い方:
  python3 script/edit-item-name-coupon.py --dry-run
  python3 script/edit-item-name-coupon.py
  python3 script/edit-item-name-coupon.py --in-place
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import sys
import math
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, date
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string
from openpyxl.utils.datetime import from_excel

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CSV = ROOT / "items" / "item_name" / "normal-item.csv"
DEFAULT_XLSX = ROOT / "items" / "02.AKI単価設定.xlsx"
DEFAULT_SHEET = "価格表"
DEFAULT_DATE_CELL = "F2"
DEFAULT_OFF_CELL = "F4"
DEFAULT_PRICE_COL = "M"

NAME_COL = 2  # 商品名（0始まり）

# 【11/18！クーポンで3,648円, 40%OFF】
BRACKET_RE = re.compile(r"^【(?P<inner>[^】]*)】")
INNER_RE = re.compile(
    r"^(?:(?P<date>\d{1,2}/\d{1,2})|(?P<label>[^！]+))"
    r"！クーポンで(?P<price>[\d,]+)円(?P<tilde>[～〜~∼])?"
    r"(?:,\s*(?P<off>\d+(?:\.\d+)?)%OFF)?$"
)


# ---------------------------------------------------------------- ユーティリティ


def norm_key(code: str) -> str:
    """商品コードの突き合わせキー。

    CSV:  a0523 / sa10326 / sjk19051
    xlsx: sa0523-a / sa0523-b / sa2450短款 / sa9560不加绒 石斑纹
    → 先頭の「英字+数字」だけ取り出し、a1234 は sa1234 に寄せる
    """
    c = str(code).strip().lower()
    m = re.match(r"[a-z]+\d+", c)
    base = m.group(0) if m else c
    if re.fullmatch(r"a\d+", base):
        return "sa" + base[1:]
    return base


def fmt_price(value) -> str:
    return f"{int(round(float(value))):,}"


def fmt_off(value) -> str:
    """0.4 → '40' / 40 → '40' / '40%' → '40'"""
    if isinstance(value, str):
        s = value.strip().replace("%", "").replace("％", "")
        num = float(s)
    else:
        num = float(value)
    pct = num * 100 if num <= 1 else num
    if abs(pct - round(pct)) < 0.01:
        return str(int(round(pct)))
    return f"{pct:.1f}"


def fmt_date(value) -> str:
    """F2 の値を「11/21」形式にする。"""
    if isinstance(value, datetime):
        return f"{value.month}/{value.day}"
    if isinstance(value, date):
        return f"{value.month}/{value.day}"
    if isinstance(value, (int, float)):
        try:
            d = from_excel(value)
            return f"{d.month}/{d.day}"
        except Exception:
            pass
    text = str(value).strip()
    m = re.search(r"(?<!\d)(\d{1,2})\s*[/\-月]\s*(\d{1,2})", text)
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    raise ValueError(f"日付として解釈できません: {value!r}（例: 11/21 または 2026/11/21）")


# cp932 に無い文字の置換表（見た目が近い文字へ寄せる）
CP932_MAP = {
    "\u203e": "～",  # ‾ (OVERLINE) → ～
    "\u301c": "～",  # 〜 (WAVE DASH) → ～
    "\u00a5": "\\",  # ¥ → \
}


def sanitize(text: str) -> str:
    for src, dst in CP932_MAP.items():
        if src in text:
            text = text.replace(src, dst)
    return text


def truncate_cp932(text: str, limit: int) -> tuple[str, int, bool]:
    """cp932換算で limit バイトを超える場合に末尾を切り詰める。

    戻り値: (切り詰め後テキスト, 元のバイト数, 切り詰めたか)
    2バイト文字の途中では切らない。
    """
    data = text.encode("cp932", errors="replace")
    if len(data) <= limit:
        return text, len(data), False
    cut = limit
    while cut > 0:
        try:
            out = data[:cut].decode("cp932")
            break
        except UnicodeDecodeError:
            cut -= 1
    else:
        out = ""
    out = out.rstrip(" 　")
    # 末尾が単語の途中にならないよう、直近のスペースまで戻す（短くなりすぎない範囲で）
    pos = max(out.rfind(" "), out.rfind("　"))
    if pos > 0:
        cand = out[:pos].rstrip(" 　")
        if len(cand.encode("cp932")) >= int(limit * 0.8):
            out = cand
    return out, len(data), True


def read_csv_auto(path: Path) -> tuple[list[list[str]], str]:
    raw = path.read_bytes()
    encs = ("utf-8-sig",) if raw[:3] == b"\xef\xbb\xbf" else ("cp932", "utf-8-sig", "utf-8")
    for enc in encs:
        try:
            label = "utf-8" if enc == "utf-8-sig" and raw[:3] != b"\xef\xbb\xbf" else enc
            return list(csv.reader(io.StringIO(raw.decode(enc)))), label
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[ERROR] 文字コードを判定できません: {path}")


def write_csv_rms(path: Path, rows: list[list[str]], encoding: str = "cp932") -> None:
    """RMSのダウンロードCSVと同じ形式（ヘッダーのみ最小クォート、データは全項目クォート）。"""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerow(rows[0])
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_ALL).writerows(
        [[sanitize(c) for c in row] for row in rows[1:]]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(buf.getvalue().encode(encoding, errors="replace"))
    os.replace(tmp, path)


def write_report(path: Path, rows: list[list[str]]) -> None:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


# ---------------------------------------------------------------- 単価表


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def detect_price_base(ws_raw, row: int) -> str:
    """M列の数式から、元になっている価格の列（J or K）を判定する。

    =ROUNDDOWN(J12*(1-F12),0)  → J
    =ROUNDDOWN(K12*(1-F12),0)  → K
    """
    formula = ws_raw.cell(row=row, column=column_index_from_string("M")).value
    if isinstance(formula, str):
        m = re.match(r"=\s*ROUNDDOWN\(\s*\$?([A-Z]{1,2})\$?\d+", formula.upper())
        if m:
            return m.group(1)
    return "J"


def compute_m(ws, row: int, base: dict, base_col: str = "J") -> float | None:
    """M列（40%OFF後価格）の数式を再現する。

    H = ROUND(D*(1+E),2)
    I = ROUND(H/(1-F)/(1-G),2)
    J = 丸め方法(B2)・丸め単位(B3) を I に適用
    K = ROUND(J/10,0)*10
    M = ROUNDDOWN((K or J)*(1-F),0)   ← 数式が K を参照している場合は K
    """
    def cell(col: str):
        return ws.cell(row=row, column=column_index_from_string(col)).value

    d = _num(cell("D"))
    e = _num(cell("E"), base.get("e"))
    f = _num(cell("F"), base.get("f"))
    g = _num(cell("G"), base.get("g", 0.0))
    if d is None or e is None or f is None or g is None:
        return None
    if f >= 1 or g >= 1:
        return None

    h = round(d * (1 + e), 2)
    i = round(h / (1 - f) / (1 - g), 2)

    unit = _num(base.get("unit"), 1.0) or 1.0
    method = str(base.get("method") or "切上げ")
    x = i / unit
    if method == "切捨て":
        j = math.floor(x + 1e-9)
    elif method == "四捨五入":
        j = math.floor(x + 0.5 + 1e-9)
    else:  # 切上げ
        j = math.ceil(x - 1e-9)
    j *= unit

    k = math.floor(j / 10 + 0.5 + 1e-9) * 10  # Excel ROUND(J/10,0)*10

    base_value = k if base_col == "K" else j
    m = (Decimal(str(base_value)) * (Decimal(1) - Decimal(str(f)))).quantize(
        Decimal(1), rounding=ROUND_DOWN
    )
    return float(m)


def load_price_table(xlsx: Path, sheet: str, price_col: str):
    """{key: [ {row, sku, price, off}, ... ]} を返す。

    M列の計算結果が保存されていない（Excelで開いて保存していない）場合は
    数式を再現して求める。
    """
    wb_val = openpyxl.load_workbook(xlsx, data_only=True, read_only=False)
    wb_raw = openpyxl.load_workbook(xlsx, data_only=False)
    if sheet not in wb_val.sheetnames:
        raise SystemExit(f"[ERROR] シートがありません: {sheet} / {wb_val.sheetnames}")
    ws_val, ws_raw = wb_val[sheet], wb_raw[sheet]

    price_idx = column_index_from_string(price_col)
    f_idx = column_index_from_string("F")

    # 共通パラメータ（丸め方法・単位・利益率/OFF率/手数料率）
    base = dict(
        method=ws_val["B2"].value,
        unit=_num(ws_val["B3"].value, 1.0),
        e=_num(ws_val["E4"].value),
        f=_num(ws_val["F4"].value),
        g=_num(ws_val["G4"].value, 0.0),
    )

    table: dict[str, list[dict]] = defaultdict(list)
    missing_price: list[tuple[int, str]] = []
    computed = 0

    for r in range(6, ws_val.max_row + 1):
        sku = ws_val.cell(row=r, column=2).value
        if sku is None or not str(sku).strip():
            continue
        price = ws_val.cell(row=r, column=price_idx).value
        off = ws_val.cell(row=r, column=f_idx).value
        if price is None:
            price = compute_m(ws_val, r, base, detect_price_base(ws_raw, r))
            if price is not None:
                computed += 1
        if price is None:
            missing_price.append((r, str(sku)))
            continue
        table[norm_key(sku)].append(
            dict(row=r, sku=str(sku).strip(), price=float(price),
                 off=_num(off))
        )

    if computed:
        print(f"[INFO] M列の計算結果が未保存のため数式から再計算: {computed}行", file=sys.stderr)

    return table, missing_price


def read_cell(xlsx: Path, sheet: str, coord: str):
    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    ws = wb[sheet] if sheet in wb.sheetnames else wb.worksheets[0]
    value = ws[coord].value
    wb.close()
    return value


def pick_price(rows: list[dict], policy: str, current: int | None) -> dict:
    if policy == "min":
        return min(rows, key=lambda x: x["price"])
    if policy == "max":
        return max(rows, key=lambda x: x["price"])
    if policy == "first":
        return rows[0]
    # closest
    if current is None:
        return min(rows, key=lambda x: x["price"])
    return min(rows, key=lambda x: abs(x["price"] - current))


# ---------------------------------------------------------------- 商品名の組み立て


def build_inner(date_text: str, price_text: str, off_text: str, tilde: bool) -> str:
    return f"{date_text}！クーポンで{price_text}円" + ("～" if tilde else "") + f", {off_text}%OFF"


def edit_name(name: str, date_text: str, off_text: str, price_text: str | None,
              shape: str, keep_outlet: bool) -> tuple[str, dict]:
    """商品名を1件処理して (新しい商品名, 詳細) を返す。"""
    info = dict(kind="", old_inner="", new_inner="", old_price=None, tilde=False, label="")
    m = BRACKET_RE.match(name)
    if not m:
        info["kind"] = "追加"
        info["new_inner"] = build_inner(date_text, price_text or "0", off_text, False)
        return f"【{info['new_inner']}】{name}", info

    inner = m.group("inner")
    info["old_inner"] = inner
    im = INNER_RE.match(inner)
    if not im:
        raise ValueError(f"クーポン表記を解釈できません: 【{inner}】")

    old_price = int(im.group("price").replace(",", ""))
    tilde = bool(im.group("tilde"))
    label = im.group("label") or ""
    info.update(old_price=old_price, tilde=tilde, label=label)

    new_price = price_text or fmt_price(old_price)
    use_date = date_text
    if keep_outlet and label and label != "" and not im.group("date"):
        use_date = label  # OUTLET などをそのまま残す

    if shape == "preserve":
        has_off = im.group("off") is not None
        new_inner = f"{use_date}！クーポンで{new_price}円"
        if tilde:
            new_inner += "～"
        if has_off:
            new_inner += f", {off_text}%OFF"
    else:
        new_inner = build_inner(use_date, new_price, off_text, tilde)

    info["new_inner"] = new_inner
    info["kind"] = "更新" if new_inner != inner else "変更なし"
    return f"【{new_inner}】{name[m.end():]}", info


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description="商品名のクーポン表記（日付・単価・OFF率）を差し替える")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="normal-item CSV")
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX, help="02.AKI単価設定.xlsx")
    ap.add_argument("--sheet", default=DEFAULT_SHEET, help="単価表のシート名")
    ap.add_argument("--date-cell", default=DEFAULT_DATE_CELL, help="日付セル（既定 F2）")
    ap.add_argument("--off-cell", default=DEFAULT_OFF_CELL, help="OFF率セル（既定 F4）")
    ap.add_argument("--price-col", default=DEFAULT_PRICE_COL, help="単価の列（既定 M）")
    ap.add_argument("--date", default=None, help="日付を直接指定（F2が空のとき）")
    ap.add_argument("--out", type=Path, default=None, help="出力CSV（既定 <元名>_namefix-<日時>.csv）")
    ap.add_argument("--report", type=Path, default=None, help="変更レポートCSV")
    ap.add_argument("--shape", choices=("full", "preserve"), default="full",
                    help="full=常に日付/単価/40%%OFFの形に揃える（既定） / preserve=元の形を保つ")
    ap.add_argument("--multi", choices=("min", "max", "first", "closest"), default="min",
                    help="1商品に複数SKU行がある場合の単価（既定 min）")
    ap.add_argument("--keep-outlet", action="store_true", help="OUTLET 表記を日付に置き換えない")
    ap.add_argument("--max-bytes", type=int, default=255,
                    help="商品名の上限バイト数（cp932換算・既定255）")
    ap.add_argument("--no-truncate", action="store_true", help="255byte超でも切り詰めない")
    ap.add_argument("--out-encoding", default="cp932",
                    choices=("cp932", "utf-8-sig", "utf-8"),
                    help="出力CSVの文字コード（既定 cp932 = RMS用）")
    ap.add_argument("--in-place", action="store_true", help="元CSVを上書き（.bak作成）")
    ap.add_argument("--dry-run", action="store_true", help="書き出しせず結果だけ表示")
    args = ap.parse_args()

    for p in (args.csv, args.xlsx):
        if not p.exists():
            print(f"[ERROR] 見つかりません: {p}", file=sys.stderr)
            return 1

    # ---- パラメータ（日付 / OFF率）
    if args.date:
        date_text = fmt_date(args.date)
        date_src = f"--date {args.date}"
    else:
        raw_date = read_cell(args.xlsx, args.sheet, args.date_cell)
        if raw_date is None or str(raw_date).strip() == "":
            print(f"[ERROR] {args.date_cell} が空です。クーポン期限（例: 11/21）を入力するか、"
                  f"--date 11/21 を指定してください", file=sys.stderr)
            return 1
        date_text = fmt_date(raw_date)
        date_src = f"{args.date_cell} = {raw_date!r}"

    raw_off = read_cell(args.xlsx, args.sheet, args.off_cell)
    if raw_off is None or str(raw_off).strip() == "":
        print(f"[ERROR] {args.off_cell} が空です（OFF率）", file=sys.stderr)
        return 1
    off_text = fmt_off(raw_off)

    table, missing = load_price_table(args.xlsx, args.sheet, args.price_col)

    # ---- CSV 読み込み
    rows, enc = read_csv_auto(args.csv)
    header, body = rows[0], rows[1:]
    if len(header) <= NAME_COL:
        print("[ERROR] 商品名の列が見つかりません", file=sys.stderr)
        return 1

    report: list[list[str]] = [[
        "行番号", "商品管理番号", "商品番号", "シート行", "旧日付/ラベル", "旧単価", "旧OFF",
        "新日付", "新単価", "新OFF", "区分", "元byte", "新byte", "切詰め",
        "商品名(変更前)", "商品名(変更後)",
    ]]
    stats = Counter()
    examples: list[tuple[str, str, str]] = []
    out_rows: list[list[str]] = [header]
    name_items = 0
    limit = args.max_bytes

    def finalize(text: str) -> tuple[str, int, int, bool]:
        """255byteに切り詰める。戻り値: (text, 元byte, 後byte, 切詰めたか)"""
        before = len(text.encode("cp932", errors="replace"))
        if args.no_truncate or limit <= 0:
            return text, before, before, False
        out, _orig, cut = truncate_cp932(text, limit)
        return out, before, len(out.encode("cp932", errors="replace")), cut

    for idx, row in enumerate(body, start=2):
        row = list(row)
        name = row[NAME_COL]
        if not name.strip():
            out_rows.append(row)
            continue

        name_items += 1
        item = row[0]
        orig_bytes = len(sanitize(name).encode("cp932", errors="replace"))
        key = norm_key(item)
        recs = table.get(key, [])
        cur_price = None
        bm = BRACKET_RE.match(name)
        if bm:
            im = INNER_RE.match(bm.group("inner"))
            if im:
                cur_price = int(im.group("price").replace(",", ""))

        if not recs:
            stats["skip_no_sheet"] += 1
            new_name, _ob, _nb, cut = finalize(sanitize(name))
            if cut:
                row[NAME_COL] = new_name
                stats["切詰め"] += 1
                kind = "切詰めのみ(単価表に商品なし)"
            else:
                kind = "変更なし(単価表に商品なし)"
            out_rows.append(row)
            report.append([idx, item, row[1], "", "", cur_price or "", "", date_text, "", off_text,
                           kind, orig_bytes, _nb, "✓" if cut else "", name, new_name])
            continue

        chosen = pick_price(recs, args.multi, cur_price)
        price_text = fmt_price(chosen["price"])

        try:
            new_name, info = edit_name(name, date_text, off_text, price_text,
                                       args.shape, args.keep_outlet)
        except ValueError as e:
            stats["error"] += 1
            print(f"[ERROR] 行{idx} {item}: {e}", file=sys.stderr)
            out_rows.append(row)
            report.append([idx, item, row[1], chosen["row"], "", cur_price or "", "", date_text,
                           price_text, off_text, "エラー", "", "", "", name, name])
            continue

        new_name, old_bytes, new_bytes, cut = finalize(sanitize(new_name))
        row[NAME_COL] = new_name
        out_rows.append(row)
        stats[info["kind"]] += 1
        kind = info["kind"]
        if cut:
            stats["切詰め"] += 1
            kind = f"{kind}(切詰め)" if info["kind"] != "変更なし" else "切詰めのみ"
        if new_name != name and len(examples) < 8:
            examples.append((item, name[:60], new_name[:60]))

        report.append([
            idx, item, row[1], chosen["row"],
            info["label"] or "", info["old_price"] or "", "",
            date_text, price_text, off_text, kind,
            orig_bytes, new_bytes, "✓" if cut else "",
            name, new_name,
        ])

    # ---- 検証（商品名列以外が変わっていないこと）
    changed_other = 0
    for a, b in zip(body, out_rows[1:]):
        for j, (x, y) in enumerate(zip(a, b)):
            if j != NAME_COL and x != y:
                changed_other += 1

    print("=== 商品名のクーポン表記 差し替え ===")
    print(f"CSV        : {args.csv.name}  ({enc}, {len(body)}行)")
    print(f"単価表      : {args.xlsx.name} / {args.sheet}  (単価列 {args.price_col})")
    print(f"日付        : {date_text}   ({date_src})")
    print(f"OFF率       : {off_text}%OFF   ({args.off_cell} = {raw_off!r})")
    print(f"形式        : {args.shape} / 複数SKU時 {args.multi} / OUTLET維持 {args.keep_outlet}")
    max_out = max(
        (len(r[NAME_COL].encode("cp932", errors="replace")) for r in out_rows[1:] if r[NAME_COL].strip()),
        default=0,
    )
    print(f"商品名あり  : {name_items}行")
    print(f"  更新      : {stats['更新']}")
    print(f"  【】追加   : {stats['追加']}")
    print(f"  変更なし   : {stats['変更なし'] + stats['skip_no_sheet']}"
          f"（うち単価表に商品なし {stats['skip_no_sheet']}）")
    print(f"  255byte切詰: {stats['切詰め']}件"
          + ("（--no-truncate のため無効）" if args.no_truncate else f"（上限 {limit}byte）"))
    print(f"  商品名の最大: {max_out}byte")
    if stats["error"]:
        print(f"  エラー     : {stats['error']}")

    if changed_other:
        print(f"[NG] 商品名以外の列が {changed_other} 箇所変わっています", file=sys.stderr)

    if missing:
        print(f"[WARN] 単価が空の行: {len(missing)} 件（{missing[:3]} ...）", file=sys.stderr)

    if examples:
        print("\n--- 変更例 ---")
        for item, before, after in examples:
            print(f"  {item}")
            print(f"    前: {before}")
            print(f"    後: {after}")

    ok = changed_other == 0 and stats["error"] == 0
    if args.dry_run:
        print("\n(--dry-run のため書き出しなし)")
        return 0 if ok else 1

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = args.out or args.csv.with_name(f"{args.csv.stem}_namefix-{ts}.csv")
    report_path = args.report or args.csv.with_name(f"report-item-name-coupon-{ts}.csv")

    if args.in_place:
        backup = args.csv.with_suffix(f".bak-{datetime.now():%Y%m%d%H%M%S}{args.csv.suffix}")
        shutil.copy2(args.csv, backup)
        print(f"\nバックアップ: {backup.name}")
        out_path = args.csv

    write_csv_rms(out_path, out_rows, args.out_encoding)
    write_report(report_path, report)
    print(f"\n書き出し: {out_path}")
    print(f"レポート: {report_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
