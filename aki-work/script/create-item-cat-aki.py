#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
既存の item-cat_aki.csv をベースに、COCOMOMO のカテゴリCSV
(item-cat_cocomomo.csv) を取り込み、AKI 用のカテゴリ一括登録CSVを作成する。
カテゴリURLの置換（COCOMOMO ID → AKI ID）はこのツール内で行うため、
単体で実行すれば最終CSVが完成する。

  - ベース行はそのまま（順序・優先度を維持）
  - 追加行は「商品管理番号 × AKIカテゴリID」が未登録のものだけ
  - 表示先カテゴリ名は category.xlsx の表記（ベースの区切り文字）に統一

使い方:
  python3 script/create-item-cat-aki.py
  python3 script/create-item-cat-aki.py --check-only
  python3 script/create-item-cat-aki.py --out items/category/item-cat_aki.csv --overwrite
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

DEFAULT_BASE = CAT_DIR / "item-cat_aki.csv"
DEFAULT_ADD = CAT_DIR / "item-cat_cocomomo.csv"
DEFAULT_MAPPING = CAT_DIR / "category.xlsx"
DEFAULT_OUT = CAT_DIR / "item-cat_aki-merged.csv"
DEFAULT_REPORT = CAT_DIR / "report-item-cat-aki-merge.csv"

URL_RE = re.compile(
    r"^(?P<base>https?://item\.rakuten\.co\.jp/)(?P<shop>[^/]+)(?P<rest>/c/(?P<code>\d+)/?)$"
)


# ---------------------------------------------------------------- 共通処理


def normalize_category(name: str) -> str:
    """カテゴリ名の比較用正規化（区切り・波ダッシュ・全半角・空白）。"""
    s = unicodedata.normalize("NFKC", str(name))
    for ch in ("¥", "￥", "＼"):
        s = s.replace(ch, "\\")
    for ch in ("~", "～", "〜", "∼"):
        s = s.replace(ch, "~")
    s = re.sub(r"[\s\u3000]+", "", s)
    return s.strip("\\")


def parse_url(url: str):
    m = URL_RE.match((url or "").strip())
    if not m:
        return None
    return m.group("shop"), m.group("code")


def category_code(url: str) -> str | None:
    p = parse_url(url)
    return p[1] if p else None


def build_url(shop: str, code: str) -> str:
    return f"https://item.rakuten.co.jp/{shop}/c/{code}/"


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


def priority_of(row: list[str]) -> int:
    try:
        return int(str(row[4]).strip())
    except (TypeError, ValueError, IndexError):
        return 10**9


def load_mapping(path: Path):
    """category.xlsx → (名前→行, COCOMOMO ID→行, AKI ID→行)"""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["カテゴリ"] if "カテゴリ" in wb.sheetnames else wb.worksheets[0]
    by_name: dict[str, dict] = {}
    by_coco: dict[str, dict] = {}
    by_aki: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name, coco, aki = row[1], row[2], row[3]
        if not name or not coco or not aki:
            continue
        entry = {
            "name": str(name).strip(),
            "coco": str(coco).strip(),
            "aki": str(aki).strip(),
        }
        by_name[normalize_category(entry["name"])] = entry
        by_coco[entry["coco"]] = entry
        by_aki[entry["aki"]] = entry
    wb.close()
    if not by_name:
        raise SystemExit(f"[ERROR] 対応表が空です: {path}")
    return by_name, by_coco, by_aki


def resolve_category(cat_name: str, coco_code: str | None, by_name, by_coco):
    """カテゴリ名／COCOMOMO ID から対応表の行を探す。"""
    key = normalize_category(cat_name)
    if key in by_name:
        return by_name[key], "name"
    parts = key.split("\\")
    for i in range(len(parts) - 1, 0, -1):  # 親カテゴリへ遡る
        parent = "\\".join(parts[:i])
        if parent in by_name:
            return by_name[parent], "parent:" + parent
    if coco_code and coco_code in by_coco:
        return by_coco[coco_code], "code"
    return None, "none"


# ---------------------------------------------------------------- 本体


def merge(
    base_rows: list[list[str]],
    add_rows: list[list[str]],
    by_name,
    by_coco,
    by_aki,
    target_shop: str,
    only_base_items: bool = False,
) -> tuple[list[list[str]], list[list[str]], dict]:
    header = base_rows[0]
    ncol = len(header)

    # ベースの階層区切り（\ か ¥）に合わせる。既存名があればその表記を流用する
    sep = "\\" if sum(r[3].count("\\") for r in base_rows[1:]) >= sum(
        r[3].count("¥") for r in base_rows[1:]
    ) else "¥"
    base_name_by_norm: dict[str, str] = {}
    for row in base_rows[1:]:
        if len(row) > 3:
            base_name_by_norm.setdefault(normalize_category(row[3]), row[3])

    def canonical_name(entry) -> str:
        name = base_name_by_norm.get(normalize_category(entry["name"]))
        if name is None:
            name = entry["name"].replace("¥", sep).replace("￥", sep)
        return name

    out: list[list[str]] = []
    report: list[list[str]] = [
        ["行番号", "商品管理番号", "表示先カテゴリ", "結果", "一致方法", "URL"]
    ]
    stats = Counter()
    unmapped_cats: Counter[str] = Counter()
    registered: dict[tuple[str, str], tuple[int, str]] = {}

    # 1) ベースをそのまま採用（商品×カテゴリの登録済み集合を作る）
    for idx, row in enumerate(base_rows[1:], start=2):
        row = list(row) + [""] * (ncol - len(row))
        code = category_code(row[5])
        if not code:
            stats["base_bad_url"] += 1
            report.append([idx, row[1], row[3], "ベース(URL形式不正)", "-", row[5]])
            continue
        key = (row[1], code)
        if key in registered:
            stats["base_dup"] += 1
        else:
            registered[key] = (len(out), "base")
        out.append(row)
    stats["base_rows"] = len(out)

    # 2) 追加分（COCOMOMO）を取り込み
    base_items = {r[1] for r in base_rows[1:] if len(r) > 1}
    for idx, row in enumerate(add_rows[1:], start=2):
        row = list(row) + [""] * (ncol - len(row))

        if only_base_items and row[1] not in base_items:
            # 既存AKIの商品だけを対象にする（COCOMOMO固有の商品は追加しない）
            stats["skip_not_in_base"] += 1
            continue

        shop, code = parse_url(row[5]) or (None, None)

        if shop == target_shop and code in by_aki:
            # 既にAKI形式のCSVを渡された場合はカテゴリIDだけ利用
            entry, how = by_aki[code], "already-aki"
        else:
            entry, how = resolve_category(row[3], code, by_name, by_coco)

        if entry is None or not entry["aki"]:
            stats["unmapped"] += 1
            unmapped_cats[row[3]] += 1
            report.append([idx, row[1], row[3], "追加せず(対応表に無し)", how, row[5]])
            continue

        key = (row[1], entry["aki"])
        if key in registered:
            pos, origin = registered[key]
            if origin == "base":
                stats["add_dup_base"] += 1
                report.append([idx, row[1], row[3], "追加せず(既存)", how, row[5]])
                continue
            # 追加分どうしの重複 → 優先度が小さい方を残す
            stats["add_dup_add"] += 1
            if priority_of(row) < priority_of(out[pos]):
                out[pos] = row
                out[pos][3] = canonical_name(entry)
                out[pos][5] = build_url(target_shop, entry["aki"])
            report.append([idx, row[1], row[3], "重複統合", how, row[5]])
            continue

        row[3] = canonical_name(entry)
        row[5] = build_url(target_shop, entry["aki"])
        registered[key] = (len(out), "add")
        out.append(row)
        stats["added"] += 1
        stats[f"how_{how.split(':')[0]}"] += 1
        report.append([idx, row[1], row[3], "追加", how, row[5]])

    # 3) 参考情報：同一カテゴリ内で優先度1が重複している件数
    by_cat: dict[str, Counter[int]] = {}
    for row in out:
        by_cat.setdefault(normalize_category(row[3]), Counter())[priority_of(row)] += 1
    ties = {c: v[1] for c, v in by_cat.items() if v.get(1, 0) > 1}
    stats["priority_1_ties"] = sum(v - 1 for v in ties.values())

    stats["total_out"] = len(out)
    stats["items"] = len({r[1] for r in out})
    stats["cats"] = len(by_cat)

    meta = {"stats": stats, "ties": ties, "unmapped_cats": unmapped_cats}
    return [header] + out, report, meta


def main() -> int:
    ap = argparse.ArgumentParser(
        description="item-cat_aki.csv をベースに COCOMOMO のカテゴリを統合し、AKI用CSVを作成する"
    )
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE, help="ベースCSV（既定: item-cat_aki.csv）")
    ap.add_argument("--add", type=Path, default=DEFAULT_ADD, help="取り込むCSV（既定: item-cat_cocomomo.csv）")
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="対応表 xlsx")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="出力CSV")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="レポートCSV")
    ap.add_argument(
        "--target-shop", default="aki-select", help="出力URLのショップコード（既定: aki-select）"
    )
    ap.add_argument("--overwrite", action="store_true", help="ベースを .bak 退避して上書き")
    ap.add_argument(
        "--include-all-items",
        action="store_true",
        help="既存AKIに無い商品（COCOMOMO固有）も追加する（既定は追加しない）",
    )
    ap.add_argument("--check-only", action="store_true", help="検証のみ")
    ap.add_argument("--no-backup", action="store_true", help="--overwrite 時に .bak を作らない")
    args = ap.parse_args()

    for p in (args.base, args.add, args.mapping):
        if not p.exists():
            print(f"[ERROR] 見つかりません: {p}", file=sys.stderr)
            return 1

    base_rows, base_enc = read_csv_auto(args.base)
    add_rows, add_enc = read_csv_auto(args.add)
    if base_rows[0] != add_rows[0]:
        print("[WARN] ヘッダーが一致しません。ベースのヘッダーを使用します", file=sys.stderr)

    by_name, by_coco, by_aki = load_mapping(args.mapping)
    only_base_items = not args.include_all_items
    out_rows, report, meta = merge(
        base_rows, add_rows, by_name, by_coco, by_aki, args.target_shop, only_base_items
    )
    s, ties, unmapped_cats = meta["stats"], meta["ties"], meta["unmapped_cats"]

    print("=== 作成結果 ===")
    print(f"ベース      : {args.base}  ({base_enc}, {len(base_rows) - 1}行)")
    print(f"取り込み    : {args.add}  ({add_enc}, {len(add_rows) - 1}行)")
    print(f"出力        : {args.out}")
    print(f"  ベース行    : {s['base_rows']}")
    print(f"  追加行      : {s['added']}  (名前一致 {s['how_name']} / 親一致 {s['how_parent']} / "
          f"ID一致 {s['how_code']} / 変換済 {s['how_already-aki']})")
    print(f"  既存と重複  : {s['add_dup_base']}")
    print(f"  追加内重複  : {s['add_dup_add']}")
    if only_base_items:
        print(f"  対象外商品  : {s['skip_not_in_base']}  (既存AKIに無い商品のため追加せず)")
    print(f"  未対応      : {s['unmapped']}")
    print(f"  合計        : {s['total_out']}行 / {s['items']}商品 / {s['cats']}カテゴリ")
    if s["base_bad_url"]:
        print(f"[WARN] ベースのURL形式不正: {s['base_bad_url']}行")

    if unmapped_cats:
        print("\n--- 対応表に無いカテゴリ（追加せず） ---")
        for name, n in unmapped_cats.most_common():
            print(f"  {n:5d}行  {name}")

    # 検証：出力URLがすべて対応表のAKIカテゴリIDか
    bad = []
    for r in out_rows[1:]:
        p = parse_url(r[5])
        if p is None or p[0] != args.target_shop or p[1] not in by_aki:
            bad.append(r)
    if bad:
        print(f"\n[NG] AKIカテゴリURLでない行: {len(bad)}", file=sys.stderr)
        for r in bad[:5]:
            print(f"  {r[1]} {r[3]} {r[5]}", file=sys.stderr)
    else:
        print(f"\n[OK] 出力URLはすべて {args.target_shop} のAKIカテゴリIDです")

    if ties:
        print(f"[INFO] 同一カテゴリ内で優先度1が重複: {sum(ties.values())}件（ベース由来を含む）")

    if args.check_only:
        print("\n(--check-only のため書き出しなし)")
        return 0 if not bad else 1

    if args.overwrite and args.out.resolve() == args.base.resolve() and not args.no_backup:
        backup = args.base.with_suffix(
            f".bak-{datetime.now():%Y%m%d%H%M%S}{args.base.suffix}"
        )
        shutil.copy2(args.base, backup)
        print(f"バックアップ: {backup}")

    write_csv(args.out, out_rows)
    write_report(args.report, report)
    print(f"\n書き出し: {args.out}")
    print(f"レポート: {args.report}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
