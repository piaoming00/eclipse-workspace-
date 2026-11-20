#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
item-cat_aki.csv のカテゴリURLを、category.xlsx を正として AKI（aki-select）の
カテゴリIDに揃える（行の追加・削除はしない。URL列のみ更新）。

  - 行数・行順・商品・優先度・カテゴリ名は変更しない
  - カテゴリ名 → 対応表の AKI ID に正規化（親カテゴリ一致も可）
  - 名前で引けない行は、現在のカテゴリIDから対応表を逆引き
  - 差分が無い場合は書き出さない（--force で強制書き出し）

使い方:
  python3 script/normalize-item-cat-aki-url.py            # 差分があれば書き出し
  python3 script/normalize-item-cat-aki-url.py --check-only
  python3 script/normalize-item-cat-aki-url.py --force    # 差分0でも書き出し
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
CAT_DIR = ROOT / "items" / "category"

DEFAULT_SRC = CAT_DIR / "item-cat_aki.csv"
DEFAULT_MAPPING = CAT_DIR / "category.xlsx"
DEFAULT_REPORT = CAT_DIR / "report-item-cat-aki-normalize.csv"

URL_RE = re.compile(
    r"^https?://item\.rakuten\.co\.jp/(?P<shop>[^/]+)/c/(?P<code>\d+)/?$"
)


def normalize_category(name: str) -> str:
    s = unicodedata.normalize("NFKC", str(name))
    for ch in ("¥", "￥", "＼"):
        s = s.replace(ch, "\\")
    for ch in ("~", "～", "〜", "∼"):
        s = s.replace(ch, "~")
    s = re.sub(r"[\s\u3000]+", "", s)
    return s.strip("\\")


def parse_url(url: str):
    m = URL_RE.match((url or "").strip())
    return (m.group("shop"), m.group("code")) if m else (None, None)


def read_csv_auto(path: Path) -> tuple[list[list[str]], str]:
    raw = path.read_bytes()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return list(csv.reader(io.StringIO(raw.decode(enc)))), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[ERROR] 文字コードを判定できません: {path}")


def write_csv(path: Path, rows: list[list[str]], encoding: str = "cp932") -> None:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue().encode(encoding, errors="replace"))


def write_report(path: Path, rows: list[list[str]]) -> None:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def load_mapping(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["カテゴリ"] if "カテゴリ" in wb.sheetnames else wb.worksheets[0]
    by_name: dict[str, dict] = {}
    by_aki: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name, coco, aki = row[1], row[2], row[3]
        if not name or not aki:
            continue
        entry = {"name": str(name).strip(), "aki": str(aki).strip(), "coco": str(coco).strip()}
        by_name[normalize_category(entry["name"])] = entry
        by_aki[entry["aki"]] = entry
    wb.close()
    if not by_name:
        raise SystemExit(f"[ERROR] 対応表が空です: {path}")
    return by_name, by_aki


def resolve(cat_name: str, code: str | None, by_name, by_aki):
    key = normalize_category(cat_name)
    if key in by_name:
        return by_name[key], "name"
    parts = key.split("\\")
    for i in range(len(parts) - 1, 0, -1):
        parent = "\\".join(parts[:i])
        if parent in by_name:
            return by_name[parent], "parent:" + parent
    if code and code in by_aki:
        return by_aki[code], "code"
    return None, "none"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="item-cat_aki.csv のカテゴリURLを AKI のカテゴリIDに揃える（行は増減しない）"
    )
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="対象CSV（既定: item-cat_aki.csv）")
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="対応表 xlsx")
    ap.add_argument("--out", type=Path, default=None, help="出力CSV（既定: --src を上書き）")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="レポートCSV")
    ap.add_argument("--target-shop", default="aki-select", help="出力URLのショップコード")
    ap.add_argument("--force", action="store_true", help="差分0でも書き出す")
    ap.add_argument("--check-only", action="store_true", help="検証のみ")
    ap.add_argument("--no-backup", action="store_true", help="上書き時に .bak を作らない")
    args = ap.parse_args()

    if not args.src.exists() or not args.mapping.exists():
        print("[ERROR] 入力ファイルが見つかりません", file=sys.stderr)
        return 1

    out_path = args.out or args.src
    rows, enc = read_csv_auto(args.src)
    by_name, by_aki = load_mapping(args.mapping)

    header, body = rows[0], rows[1:]
    ncol = len(header)
    stats = Counter()
    report: list[list[str]] = [
        ["行番号", "商品管理番号", "表示先カテゴリ", "結果", "一致方法", "変更前URL", "変更後URL"]
    ]
    out: list[list[str]] = []
    unmatched: Counter[str] = Counter()

    for idx, row in enumerate(body, start=2):
        row = list(row) + [""] * (ncol - len(row))
        shop, code = parse_url(row[5])
        entry, how = resolve(row[3], code, by_name, by_aki)

        if entry is None:
            stats["unmatched"] += 1
            unmatched[row[3]] += 1
            report.append([idx, row[1], row[3], "未対応(変更なし)", how, row[5], row[5]])
            out.append(row)
            continue

        new_url = f"https://item.rakuten.co.jp/{args.target_shop}/c/{entry['aki']}/"
        if new_url == row[5]:
            stats["same"] += 1
            report.append([idx, row[1], row[3], "変更なし", how, row[5], new_url])
        else:
            stats["changed"] += 1
            report.append([idx, row[1], row[3], "URL変更", how, row[5], new_url])
        row[5] = new_url
        out.append(row)

    stats["total"] = len(out)
    stats["items"] = len({r[1] for r in out})
    stats["cats"] = len({normalize_category(r[3]) for r in out})

    print("=== 正規化結果 ===")
    print(f"対象        : {args.src}  ({enc}, {stats['total']}行)")
    print(f"出力        : {out_path}")
    print(f"  変更なし    : {stats['same']}")
    print(f"  URL変更     : {stats['changed']}")
    print(f"  未対応      : {stats['unmatched']}")
    print(f"  合計        : {stats['total']}行 / {stats['items']}商品 / {stats['cats']}カテゴリ")

    if unmatched:
        print("\n--- 対応表に無いカテゴリ（URL変更なし） ---")
        for name, n in unmatched.most_common():
            print(f"  {n:5d}行  {name}")

    bad = [r for r in out if parse_url(r[5])[0] != args.target_shop]
    if bad:
        print(f"\n[NG] {args.target_shop} 以外のURL: {len(bad)}行", file=sys.stderr)
        for r in bad[:5]:
            print(f"  {r[1]} {r[3]} {r[5]}", file=sys.stderr)
    else:
        print(f"\n[OK] 全行が {args.target_shop} のカテゴリURLです")

    if args.check_only:
        print("\n(--check-only のため書き出しなし)")
        return 0 if not bad else 1

    if stats["changed"] == 0 and not args.force:
        print("\n差分がないため書き出しをスキップしました（--force で強制書き出し）")
        write_report(args.report, report)
        return 0 if not bad else 1

    if out_path.resolve() == args.src.resolve() and not args.no_backup:
        backup = args.src.with_suffix(
            f".bak-{datetime.now():%Y%m%d%H%M%S}{args.src.suffix}"
        )
        shutil.copy2(args.src, backup)
        print(f"バックアップ: {backup}")

    write_csv(out_path, out)
    write_report(args.report, report)
    print(f"\n書き出し: {out_path}")
    print(f"レポート: {args.report}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
