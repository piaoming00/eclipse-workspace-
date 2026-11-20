#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
item-cat_aki.csv の各商品について、item-cat_cocomomo.csv が持っているカテゴリを
すべて（複数行で）登録し直す。商品は追加しない（aki CSV に居る商品だけ）。

  例）sa10886 は 5行に展開
    2026新作アイテム
    2026新作アイテム\\【10/26～11/1】新作UP！
    トップス
    トップス\\ニット・セーター\\長袖
    オフィスカジュアル\\ニット・セーター

  - カテゴリ名は item-cat_aki.csv / category.xlsx の AKI 表記（区切り \\）
  - URL は https://item.rakuten.co.jp/aki-select/c/{AKIカテゴリID}/
  - 優先度は item-cat_cocomomo.csv の値
  - 同じ商品×同じAKIカテゴリになる行は1つに統合（優先度が小さい方を残す）
  - 対応表に無いカテゴリは親カテゴリへ寄せる（更に無ければ除外）

使い方:
  python3 script/expand-item-cat-aki-categories.py --check-only
  python3 script/expand-item-cat-aki-categories.py --in-place
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
CAT_DIR = ROOT / "items" / "category"

DEFAULT_MAPPING = CAT_DIR / "category.xlsx"
DEFAULT_AKI = CAT_DIR / "item-cat_aki.csv"
DEFAULT_COCO = CAT_DIR / "item-cat_cocomomo.csv"
DEFAULT_OUT = CAT_DIR / "item-cat_aki-expanded.csv"
DEFAULT_REPORT = CAT_DIR / "report-item-cat-aki-expand.csv"

TARGET_SHOP = "aki-select"

URL_RE = re.compile(r"^https?://item\.rakuten\.co\.jp/(?P<shop>[^/]+)/c/(?P<code>\d+)/?$")


def normalize_category(name: str) -> str:
    s = unicodedata.normalize("NFKC", str(name))
    for ch in ("¥", "￥", "＼"):
        s = s.replace(ch, "\\")
    for ch in ("~", "～", "〜", "∼"):
        s = s.replace(ch, "~")
    s = re.sub(r"[\s\u3000]+", "", s)
    return s.strip("\\")


def to_aki_text(text: str) -> str:
    s = str(text)
    for ch in ("¥", "￥", "＼"):
        s = s.replace(ch, "\\")
    for ch in ("~", "〜", "∼"):
        s = s.replace(ch, "～")
    return s


def parse_url(url: str) -> tuple[str | None, str | None]:
    m = URL_RE.match((url or "").strip())
    return (m.group("shop"), m.group("code")) if m else (None, None)


def build_url(code: str) -> str:
    return f"https://item.rakuten.co.jp/{TARGET_SHOP}/c/{code}/"


def read_csv_auto(path: Path) -> tuple[list[list[str]], str]:
    raw = path.read_bytes()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return list(csv.reader(io.StringIO(raw.decode(enc)))), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[ERROR] 文字コードを判定できません: {path}")


def write_csv_shiftjis(path: Path, rows: list[list[str]]) -> None:
    """RMSのダウンロードCSVと同じ形式（ヘッダーのみ最小クォート、データは全項目クォート）。"""
    buf = io.StringIO()
    if rows:
        csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerow(rows[0])
        csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_ALL).writerows(rows[1:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue().encode("cp932", errors="replace"))


def write_report(path: Path, rows: list[list[str]]) -> None:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def priority_of(value: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 10**9


def load_mapping(path: Path) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["カテゴリ"] if "カテゴリ" in wb.sheetnames else wb.worksheets[0]
    by_name: dict[str, dict] = {}
    by_coco: dict[str, dict] = {}
    by_aki: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) < 4 or not row[1] or not row[2] or not row[3]:
            continue
        entry = {
            "name": str(row[1]).strip(),
            "coco": str(row[2]).strip(),
            "aki": str(row[3]).strip(),
        }
        by_name[normalize_category(entry["name"])] = entry
        by_coco[entry["coco"]] = entry
        by_aki[entry["aki"]] = entry
    wb.close()
    if not by_name:
        raise SystemExit(f"[ERROR] 対応表が空です: {path}")
    return by_name, by_coco, by_aki


def resolve(coco_code: str, coco_name: str, by_coco, by_name):
    if coco_code in by_coco:
        return by_coco[coco_code], "name"
    key = normalize_category(coco_name)
    parts = key.split("\\")
    for i in range(len(parts) - 1, 0, -1):
        parent = "\\".join(parts[:i])
        if parent in by_name:
            return by_name[parent], f"parent:{parent}"
    return None, "none"


def load_cocomomo(rows: list[list[str]]) -> dict[str, list[list[str]]]:
    """商品管理番号 → COCOMOMOの行（並び順維持・同じCOCOMOMO IDは1回だけ）"""
    result: dict[str, list[list[str]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if len(row) < 6:
            continue
        _, code = parse_url(row[5])
        if not code or (row[1], code) in seen:
            continue
        seen.add((row[1], code))
        result[row[1]].append(row)
    return result


def expand(
    header: list[str],
    aki_rows: list[list[str]],
    coco_by_item: dict[str, list[list[str]]],
    by_coco,
    by_name,
    by_aki,
) -> tuple[list[list[str]], list[list[str]], dict]:
    ncol = len(header)
    aki_names: dict[str, str] = {}
    aki_codes_by_code: dict[str, str] = {}
    item_order: list[str] = []
    aki_pairs: dict[tuple[str, str], str] = {}

    for row in aki_rows:
        item_id = row[1]
        if item_id not in aki_names:
            aki_names[item_id] = row[2]
            item_order.append(item_id)
        _, code = parse_url(row[5])
        if code:
            aki_codes_by_code.setdefault(code, row[3])
            aki_pairs[(item_id, code)] = row[4]

    stats = Counter()
    added: list[tuple[str, str]] = []
    priority_changed: list[tuple[str, str, str, str]] = []
    unmapped: Counter[str] = Counter()
    out: list[list[str]] = []

    for item_id in item_order:
        seen: dict[str, int] = {}
        item_rows: list[list[str]] = []
        coco_rows = coco_by_item.get(item_id, [])
        if not coco_rows:
            stats["no_cocomomo"] += 1
            continue

        for c_row in coco_rows:
            _, coco_code = parse_url(c_row[5])
            entry, how = resolve(coco_code, c_row[3], by_coco, by_name)
            if entry is None:
                stats["unmapped"] += 1
                unmapped[c_row[3]] += 1
                continue

            code = entry["aki"]
            name = aki_codes_by_code.get(code) or to_aki_text(entry["name"])
            pri = c_row[4]
            new_row = ["", item_id, aki_names[item_id], name, pri, build_url(code), ""]

            if code in seen:
                # 同じ商品×同じAKIカテゴリ（例: サンダル→シューズ）は1行に統合
                pos = seen[code]
                stats["merged"] += 1
                if priority_of(pri) < priority_of(item_rows[pos][4]):
                    item_rows[pos] = new_row
                continue

            seen[code] = len(item_rows)
            item_rows.append(new_row)

        out.extend(item_rows)

    new_pairs = {(r[1], parse_url(r[5])[1]): r[4] for r in out}
    for key, pri in aki_pairs.items():
        if key not in new_pairs:
            stats["removed"] += 1
        elif new_pairs[key] != pri:
            stats["priority_changed"] += 1
            priority_changed.append((key[0], key[1], pri, new_pairs[key]))
    added = [k for k in new_pairs if k not in aki_pairs]
    stats["added"] = len(added)
    stats["total"] = len(out)
    stats["items"] = len({r[1] for r in out})
    stats["categories"] = len({r[3] for r in out})
    stats["aki_items"] = len(item_order)
    stats["aki_rows"] = len(aki_rows)

    report: list[list[str]] = [
        ["行番号", "商品管理番号", "表示先カテゴリ", "優先度", "URL", "区分"]
    ]
    for idx, r in enumerate(out, start=2):
        key = (r[1], parse_url(r[5])[1])
        if key not in aki_pairs:
            kind = "追加"
        elif aki_pairs[key] != r[4]:
            kind = "優先度変更"
        else:
            kind = "変更なし"
        report.append([idx, r[1], r[3], r[4], r[5], kind])
        stats[f"report_{kind}"] += 1

    meta = {
        "stats": stats,
        "unmapped": unmapped,
        "priority_changed": priority_changed,
        "aki_by_code": aki_codes_by_code,
    }
    return [header] + out, report, meta


def main() -> int:
    ap = argparse.ArgumentParser(
        description="item-cat_aki.csv の商品を COCOMOMO の複数カテゴリへ展開する"
    )
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    ap.add_argument("--aki", type=Path, default=DEFAULT_AKI)
    ap.add_argument("--coco", type=Path, default=DEFAULT_COCO)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--in-place", action="store_true", help="item-cat_aki.csv を上書き（.bak作成）")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    for p in (args.mapping, args.aki, args.coco):
        if not p.exists():
            print(f"[ERROR] 見つかりません: {p}", file=sys.stderr)
            return 1

    _by_name, by_coco, by_aki = load_mapping(args.mapping)
    by_name = _by_name
    aki_rows, aki_enc = read_csv_auto(args.aki)
    coco_rows, coco_enc = read_csv_auto(args.coco)
    coco_by_item = load_cocomomo(coco_rows[1:])

    out_rows, report, meta = expand(
        aki_rows[0], aki_rows[1:], coco_by_item, by_coco, by_name, by_aki
    )
    s = meta["stats"]

    bad = [r for r in out_rows[1:] if parse_url(r[5])[0] != TARGET_SHOP or parse_url(r[5])[1] not in by_aki]
    dup = Counter((r[1], parse_url(r[5])[1]) for r in out_rows[1:])
    dup_rows = sum(v - 1 for v in dup.values() if v > 1)

    print("=== item-cat_aki.csv の複数カテゴリ展開（COCOMOMO基準） ===")
    print(f"入力        : {args.aki.name}  ({aki_enc}, {s['aki_rows']}行 / {s['aki_items']}商品)")
    print(f"COCOMOMO    : {args.coco.name}  ({coco_enc})")
    print(f"出力        : {s['total']}行 / {s['items']}商品 / {s['categories']}カテゴリ")
    print(f"  追加行      : {s['added']}  （既存に無かったカテゴリ）")
    print(f"  統合       : {s['merged']}  （同一商品×同一AKIカテゴリ）")
    print(f"  削除       : {s['removed']}")
    print(f"  優先度変更  : {s['priority_changed']}")
    print(f"  対応表に無し: {s['unmapped']}")
    print(f"  商品数      : {args.aki.name} の {s['aki_items']}商品のみ（追加なし）")

    if s["report_追加"]:
        print(f"\n  参考: 1商品あたりの行数 = {s['total'] / s['items']:.1f}行（元 {s['aki_rows'] / s['aki_items']:.1f}行）")

    if meta["unmapped"]:
        print("\n--- 対応表に無く除外したカテゴリ ---")
        for name, n in meta["unmapped"].most_common():
            print(f"  {n:4d}行  {name!r}")

    if dup_rows:
        print(f"\n[NG] 同一商品×同一カテゴリの重複: {dup_rows}行", file=sys.stderr)
    if bad:
        print(f"[NG] {TARGET_SHOP} 以外/対応表に無いURL: {len(bad)}行", file=sys.stderr)
        for r in bad[:5]:
            print(f"  {r[1]} {r[3]} {r[5]}", file=sys.stderr)
    if not bad and not dup_rows:
        print(f"\n[OK] 全URLが {TARGET_SHOP} のAKIカテゴリID・重複なし")

    ok = not bad and not dup_rows
    if args.check_only:
        print("\n(--check-only のため書き出しなし)")
        return 0 if ok else 1

    target = args.aki if args.in_place else args.out
    if args.in_place and not args.no_backup:
        backup = args.aki.with_suffix(f".bak-{datetime.now():%Y%m%d%H%M%S}{args.aki.suffix}")
        shutil.copy2(args.aki, backup)
        print(f"\nバックアップ: {backup.name}")

    write_csv_shiftjis(target, out_rows)
    write_report(args.report, report)
    print(f"\n書き出し: {target.name}")
    print(f"レポート: {args.report.name}")

    # 1商品の展開例
    sample_item = "sa10886"
    if any(r[1] == sample_item for r in out_rows[1:]):
        print(f"\n--- {sample_item} の展開結果 ---")
        for r in out_rows[1:]:
            if r[1] == sample_item:
                print(f"  {r[3]}: {r[4]}  {r[5]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
