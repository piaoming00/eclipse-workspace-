#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
item-cat_cocomomo.csv のカテゴリURL（COCOMOMO = sljapan1 のカテゴリID）を、
category.xlsx の対応表を使って AKI（aki-select）のカテゴリURLへ置換する。

使い方:
  python3 script/convert-category-cocomomo-to-aki.py
  python3 script/convert-category-cocomomo-to-aki.py --check-only
  python3 script/convert-category-cocomomo-to-aki.py --unmapped drop
  python3 script/convert-category-cocomomo-to-aki.py --keep-shop

判定の流れ（1行ごと）:
  1. 「表示先カテゴリ」を正規化して対応表と完全一致
  2. 無ければ親カテゴリへ遡って一致（例: グッズ\\アクセサリー\\指輪 → グッズ\\アクセサリー）
  3. それでも無ければ URL のカテゴリID（COCOMOMO列）で一致
  4. 決まらない行は --unmapped の指定に従う（既定 keep = 元のまま残す）
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
CAT_DIR = ROOT / "items" / "category"

DEFAULT_MAPPING = CAT_DIR / "category.xlsx"
DEFAULT_SRC = CAT_DIR / "item-cat_cocomomo.csv"
DEFAULT_OUT = CAT_DIR / "item-cat_cocomomo-to-aki.csv"
DEFAULT_REPORT = CAT_DIR / "report-category-convert.csv"

URL_RE = re.compile(r"^(?P<base>https?://item\.rakuten\.co\.jp/)(?P<shop>[^/]+)(?P<rest>/c/(?P<code>\d+)/?)$")

CSV_HEADER = [
    "コントロールカラム",
    "商品管理番号（商品URL）",
    "商品名",
    "表示先カテゴリ",
    "優先度",
    "URL",
    "1ページ複数形式",
]


# ---------------------------------------------------------------- 正規化


def normalize_category(name: str) -> str:
    """カテゴリ名を比較用に正規化する。

    - NFKC（全角英数記号 → 半角）
    - 階層区切り ¥ / ￥ / \\ / ／ / スラッシュ を \\ に統一
    - 波ダッシュ・全角チルダ・チルダ を ~ に統一（NFKC では ～ が ~ にならないため）
    - 空白（全角含む）を除去
    """
    s = unicodedata.normalize("NFKC", str(name))
    for ch in ("¥", "￥", "＼"):
        s = s.replace(ch, "\\")
    for ch in ("~", "～", "〜", "∼"):
        s = s.replace(ch, "~")
    s = re.sub(r"[\s\u3000]+", "", s)
    return s.strip("\\")


def parse_url(url: str) -> tuple[str, str, str] | None:
    """カテゴリURLを (base, shop, code) に分解。形式外は None。"""
    m = URL_RE.match(url.strip())
    if not m:
        return None
    return m.group("base"), m.group("shop"), m.group("code")


def build_url(shop: str, code: str) -> str:
    return f"https://item.rakuten.co.jp/{shop}/c/{code}/"


# ---------------------------------------------------------------- 入出力


def read_csv_auto(path: Path) -> tuple[list[list[str]], str]:
    """Shift_JIS(cp932) → utf-8-sig の順で読み込み、使用エンコーディングも返す。"""
    raw = path.read_bytes()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"[ERROR] 文字コードを判定できません: {path}")
    rows = list(csv.reader(io.StringIO(text)))
    return rows, enc


def write_csv(path: Path, rows: list[list[str]], encoding: str = "cp932") -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue().encode(encoding, errors="replace"))


def write_report(path: Path, rows: list[list[str]]) -> None:
    # Excel でそのまま開けるよう UTF-8 BOM + CRLF
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def load_mapping(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """category.xlsx を読み、(名前→行, COCOMOMOコード→行) を返す。"""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["カテゴリ"] if "カテゴリ" in wb.sheetnames else wb.worksheets[0]
    by_name: dict[str, dict] = {}
    by_coco: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name, coco, aki = row[1], row[2], row[3]
        if not name or not coco or not aki:
            continue
        entry = {
            "name": str(name).strip(),
            "coco": str(coco).strip(),
            "aki": str(aki).strip(),
        }
        key = normalize_category(entry["name"])
        if key in by_name and by_name[key]["aki"] != entry["aki"]:
            raise SystemExit(f"[ERROR] 対応表の重複: {entry['name']} ({key})")
        by_name[key] = entry
        by_coco[entry["coco"]] = entry
    wb.close()
    if not by_name:
        raise SystemExit(f"[ERROR] 対応表が空です: {path}")
    return by_name, by_coco


# ---------------------------------------------------------------- 変換


def resolve_category(
    cat_name: str, code: str | None, by_name: dict[str, dict], by_coco: dict[str, dict]
) -> tuple[dict | None, str]:
    """カテゴリを特定する。戻り値は (対応表の行, 一致方法)。"""
    key = normalize_category(cat_name)

    if key in by_name:
        return by_name[key], "name"

    # 親カテゴリへ遡って一致（サブカテゴリを親へ寄せる）
    parts = key.split("\\")
    for i in range(len(parts) - 1, 0, -1):
        parent = "\\".join(parts[:i])
        if parent in by_name:
            return by_name[parent], f"parent:{parent}"

    if code and code in by_coco:
        return by_coco[code], "code"

    return None, "none"


def convert(
    rows: list[list[str]],
    by_name: dict[str, dict],
    by_coco: dict[str, dict],
    target_shop: str,
    unmapped: str,
    dedupe: bool,
) -> tuple[list[list[str]], list[list[str]], dict]:
    header, body = rows[0], rows[1:]
    out_header = header if header else CSV_HEADER

    out_rows: list[list[str]] = []
    report: list[list[str]] = [
        ["行番号", "商品管理番号", "表示先カテゴリ", "結果", "一致方法", "元URL", "出力URL"]
    ]
    stats = Counter()
    unmapped_cats: Counter[str] = Counter()
    seen: dict[tuple[str, str], int] = OrderedDict()

    for idx, row in enumerate(body, start=2):
        row = list(row) + [""] * (len(out_header) - len(row))
        item_id, cat_name, url = row[1], row[3], row[5]
        parsed = parse_url(url)
        code = parsed[2] if parsed else None

        entry, how = resolve_category(cat_name, code, by_name, by_coco)

        if entry is None:
            stats["unmapped"] += 1
            unmapped_cats[cat_name] += 1
            if unmapped == "drop":
                stats["dropped_unmapped"] += 1
                report.append([idx, item_id, cat_name, "除外(未対応)", "none", url, ""])
                continue
            if unmapped == "fail":
                report.append([idx, item_id, cat_name, "エラー(未対応)", "none", url, ""])
                continue
            # keep: 変換できない行は元のまま残す
            out_rows.append(row)
            stats["kept_original"] += 1
            report.append([idx, item_id, cat_name, "元のまま", "none", url, url])
            continue

        new_url = build_url(target_shop, entry["aki"])

        if dedupe:
            key = (item_id, entry["aki"])
            if key in seen:
                # 優先度が小さい方（＝優先）を残す
                stats["duplicate"] += 1
                prev_pos = seen[key]
                prev_row = out_rows[prev_pos]
                try:
                    prev_pri = int(prev_row[4])
                except (TypeError, ValueError):
                    prev_pri = 10**9
                try:
                    cur_pri = int(row[4])
                except (TypeError, ValueError):
                    cur_pri = 10**9
                report.append(
                    [idx, item_id, cat_name, "重複除外", how, url, prev_row[5]]
                )
                if cur_pri < prev_pri:
                    out_rows[prev_pos] = row
                continue
            seen[key] = len(out_rows)

        row[5] = new_url
        out_rows.append(row)
        stats["converted"] += 1
        stats[f"how_{how.split(':')[0]}"] += 1
        report.append([idx, item_id, cat_name, "変換", how, url, new_url])

    stats["total_in"] = len(body)
    stats["total_out"] = len(out_rows)
    return [out_header] + out_rows, report, {"stats": stats, "unmapped_cats": unmapped_cats}


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(
        description="COCOMOMO のカテゴリURLを AKI のカテゴリURLへ置換する"
    )
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="対応表 xlsx")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="変換元 CSV")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="変換後 CSV")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="レポート CSV")
    ap.add_argument(
        "--target-shop",
        default="aki-select",
        help="出力URLのショップコード（既定: aki-select）",
    )
    ap.add_argument(
        "--keep-shop",
        action="store_true",
        help="元URLのショップコードを維持する（カテゴリIDだけ差し替え）",
    )
    ap.add_argument(
        "--unmapped",
        choices=("keep", "drop", "fail"),
        default="keep",
        help="対応表に無いカテゴリの扱い: keep=元のまま / drop=除外 / fail=エラー扱い(元のまま)",
    )
    ap.add_argument(
        "--no-dedupe", action="store_true", help="同一商品×同一カテゴリの重複を統合しない"
    )
    ap.add_argument("--check-only", action="store_true", help="検証のみ（ファイルを書かない）")
    args = ap.parse_args()

    if not args.mapping.exists():
        print(f"[ERROR] 対応表が見つかりません: {args.mapping}", file=sys.stderr)
        return 1
    if not args.src.exists():
        print(f"[ERROR] 変換元が見つかりません: {args.src}", file=sys.stderr)
        return 1
    if args.out.resolve() == args.src.resolve():
        print("[ERROR] --out に変換元と同じファイルは指定できません", file=sys.stderr)
        return 1

    by_name, by_coco = load_mapping(args.mapping)
    rows, enc = read_csv_auto(args.src)
    if not rows:
        print("[ERROR] 変換元 CSV が空です", file=sys.stderr)
        return 1

    # 出力URLのショップを決める
    shop = args.target_shop
    if args.keep_shop:
        sample = next((parse_url(r[5]) for r in rows[1:] if len(r) > 5), None)
        if sample is None:
            print("[ERROR] URL列の形式を判定できません", file=sys.stderr)
            return 1
        shop = sample[1]

    out_rows, report, meta = convert(
        rows, by_name, by_coco, shop, args.unmapped, not args.no_dedupe
    )
    stats, unmapped_cats = meta["stats"], meta["unmapped_cats"]

    valid_aki = {e["aki"] for e in by_name.values()}
    bad = []
    for r in out_rows[1:]:
        if normalize_category(r[3]) not in by_name:
            continue  # 未対応カテゴリは元URLのまま（意図的）
        p = parse_url(r[5])
        if p is None or p[2] not in valid_aki:
            bad.append(r)

    print("=== 変換結果 ===")
    print(f"対応表        : {args.mapping}  ({len(by_name)}カテゴリ)")
    print(f"変換元        : {args.src}  ({enc})")
    print(f"出力          : {args.out}  (shop={shop})")
    print(f"行数          : {stats['total_in']} → {stats['total_out']}")
    print(f"  変換        : {stats['converted']}")
    print(f"    ├ 名前一致 : {stats['how_name']}")
    print(f"    ├ 親一致   : {stats['how_parent']}")
    print(f"    └ コード一致: {stats['how_code']}")
    print(f"  未対応(保持) : {stats['kept_original']}")
    print(f"  未対応(除外) : {stats['dropped_unmapped']}")
    print(f"  重複統合     : {stats['duplicate']}")

    if unmapped_cats:
        print("\n--- 対応表に無いカテゴリ ---")
        for name, n in unmapped_cats.most_common():
            print(f"  {n:5d}行  {name}")

    if bad:
        print(f"\n[NG] AKI カテゴリIDになっていない行: {len(bad)}", file=sys.stderr)
        for r in bad[:5]:
            print(f"  {r[1]} {r[3]} {r[5]}", file=sys.stderr)
        ok = False
    else:
        print("\n[OK] 出力URLはすべて対応表のAKIカテゴリIDです")
        ok = True

    if args.check_only:
        print("\n(--check-only のため書き出しは行っていません)")
        return 0 if ok else 1

    write_csv(args.out, out_rows, encoding="cp932")
    write_report(args.report, report)
    print(f"\n書き出し: {args.out}")
    print(f"レポート: {args.report}")
    if args.unmapped == "fail" and stats["unmapped"]:
        print("[WARN] 未対応カテゴリがあります（--unmapped fail）", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
