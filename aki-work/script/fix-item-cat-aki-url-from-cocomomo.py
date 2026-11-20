#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
item-cat_aki.csv の URL を、「その商品が item-cat_cocomomo.csv で持っているカテゴリ」に
category.xlsx の対応表を経由して差し替える。

  - 行の追加・削除・並替なし（商品は追加しない）
  - 既定では URL 列のみ変更（表示先カテゴリはそのまま）
  - COCOMOMO 側に無いカテゴリ（＝「その他」で仮置きされている行）だけが対象
  - 差し替え先は、その商品の item-cat_cocomomo.csv 先頭行のカテゴリ
    （例: sa10886 → COCOMOMO「2026新作アイテム」0000000397 → AKI 0000000002）

使い方:
  python3 script/fix-item-cat-aki-url-from-cocomomo.py            # URLのみ
  python3 script/fix-item-cat-aki-url-from-cocomomo.py --sync-name # カテゴリ名も合わせる
  python3 script/fix-item-cat-aki-url-from-cocomomo.py --in-place  # aki CSV を上書き(.bak)
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
DEFAULT_OUT = CAT_DIR / "item-cat_aki-urlfixed.csv"
DEFAULT_OUT_SYNC = CAT_DIR / "item-cat_aki-urlfixed-namesync.csv"
DEFAULT_REPORT = CAT_DIR / "report-item-cat-aki-urlfix.csv"

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
    """楽天RMSのダウンロードCSVと同じ形式で保存する。

    - 1行目（ヘッダー）は必要最小限のクォート
    - 2行目以降（データ）は全項目をクォート
    - cp932 / CRLF
    """
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


def cocomomo_categories(rows: list[list[str]]) -> dict[str, list[tuple[str, str, str]]]:
    """商品管理番号 → [(COCOMOMO ID, 表示先カテゴリ, 優先度)] （CSVの並び順・重複なし）"""
    result: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if len(row) < 6:
            continue
        _, code = parse_url(row[5])
        if not code:
            continue
        key = (row[1], code)
        if key in seen:
            continue
        seen.add(key)
        result[row[1]].append((code, row[3], row[4]))
    return result


def fix(
    header: list[str],
    rows: list[list[str]],
    coco_by_item: dict[str, list[tuple[str, str, str]]],
    by_coco: dict[str, dict],
    by_aki: dict[str, dict],
    sync_name: bool,
) -> tuple[list[list[str]], list[list[str]], dict]:
    ncol = len(header)
    out: list[list[str]] = []
    report: list[list[str]] = [
        [
            "行番号",
            "商品管理番号",
            "表示先カテゴリ(変更前)",
            "優先度",
            "URL(変更前)",
            "URL(変更後)",
            "参照COCOMOMOカテゴリ",
            "新カテゴリ名",
            "結果",
        ]
    ]
    stats = Counter()
    changed_cat: Counter[tuple[str, str]] = Counter()
    missing_coco: list[str] = []

    for idx, row in enumerate(rows, start=2):
        row = list(row) + [""] * (ncol - len(row))
        item_id, cat_name, url = row[1], row[3], row[5]
        _, cur_code = parse_url(url)

        coco_list = coco_by_item.get(item_id)
        if not coco_list:
            stats["no_cocomomo"] += 1
            missing_coco.append(item_id)
            report.append([idx, item_id, cat_name, row[4], url, url, "", "", "変更なし(COCOMOMOに商品なし)"])
            out.append(row)
            continue

        # その商品が COCOMOMO で持っているカテゴリを AKI ID に変換した集合
        mapped = {by_coco[c]["aki"] for c, _, _ in coco_list if c in by_coco}
        if cur_code in mapped:
            stats["already_ok"] += 1
            report.append([idx, item_id, cat_name, row[4], url, url, "", "", "変更なし(一致)"])
            out.append(row)
            continue

        # 仮置き（その他 等）→ COCOMOMO 先頭カテゴリへ差し替え
        first_code, first_name, _first_pri = coco_list[0]
        entry = by_coco.get(first_code)
        if entry is None:
            stats["unmapped"] += 1
            report.append(
                [idx, item_id, cat_name, row[4], url, url, f"{first_name}({first_code})", "",
                 "変更なし(対応表に無し)"]
            )
            out.append(row)
            continue

        new_url = build_url(entry["aki"])
        new_name = to_aki_text(entry["name"])
        stats["changed"] += 1
        changed_cat[(cat_name, new_name)] += 1
        if sync_name:
            row[3] = new_name
        row[5] = new_url
        out.append(row)
        report.append(
            [idx, item_id, cat_name, row[4], url, new_url, f"{first_name}({first_code})", new_name, "URL差し替え"]
        )

    stats["total"] = len(out)
    stats["items"] = len({r[1] for r in out})
    meta = {"stats": stats, "changed_cat": changed_cat, "missing_coco": missing_coco}
    return [header] + out, report, meta


def main() -> int:
    ap = argparse.ArgumentParser(
        description="item-cat_aki.csv のURLをCOCOMOMOのカテゴリ（対応表経由）へ差し替える"
    )
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    ap.add_argument("--aki", type=Path, default=DEFAULT_AKI)
    ap.add_argument("--coco", type=Path, default=DEFAULT_COCO)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="URLのみ差し替えた出力")
    ap.add_argument("--out-sync", type=Path, default=DEFAULT_OUT_SYNC, help="カテゴリ名も合わせた出力")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--sync-name", action="store_true", help="表示先カテゴリも新しいURLに合わせる")
    ap.add_argument("--in-place", action="store_true", help="item-cat_aki.csv を上書き（.bak作成）")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    for p in (args.mapping, args.aki, args.coco):
        if not p.exists():
            print(f"[ERROR] 見つかりません: {p}", file=sys.stderr)
            return 1

    _by_name, by_coco, by_aki = load_mapping(args.mapping)
    aki_rows, aki_enc = read_csv_auto(args.aki)
    coco_rows, coco_enc = read_csv_auto(args.coco)
    coco_by_item = cocomomo_categories(coco_rows[1:])

    url_only, report, meta = fix(
        aki_rows[0], aki_rows[1:], coco_by_item, by_coco, by_aki, sync_name=False
    )
    s = meta["stats"]

    # 検証：行数維持・URLはaki-select・想定外の列変更なし
    bad_url = [r for r in url_only[1:] if parse_url(r[5])[0] != TARGET_SHOP]
    same_len = len(url_only) == len(aki_rows)
    diff_cols = Counter()
    for before, after in zip(aki_rows[1:], url_only[1:]):
        for i, (b, a) in enumerate(zip(before, after)):
            if b != a:
                diff_cols[i] += 1

    print("=== item-cat_aki.csv のURL差し替え（COCOMOMO基準） ===")
    print(f"入力          : {args.aki.name}  ({aki_enc}, {len(aki_rows) - 1}行 / {s['items']}商品)")
    print(f"COCOMOMO      : {args.coco.name}  ({coco_enc})")
    print(f"  変更なし(一致)     : {s['already_ok']}行")
    print(f"  URL差し替え        : {s['changed']}行")
    print(f"  COCOMOMOに商品なし : {s['no_cocomomo']}行")
    print(f"  対応表に無し       : {s['unmapped']}行")
    print(f"  行数              : {len(aki_rows) - 1} → {len(url_only) - 1} （増減なし: {same_len}）")
    print(f"  変更された列       : {dict(diff_cols)} （5列目=URLのみ）")

    if meta["changed_cat"]:
        print("\n--- 差し替え内容 ---")
        for (old, new), n in meta["changed_cat"].most_common():
            print(f"  {n:4d}行  {old!r} → {new!r}")

    if meta["missing_coco"]:
        print(f"\n[WARN] COCOMOMO側に無い商品: {len(meta['missing_coco'])}件")

    if bad_url:
        print(f"\n[NG] {TARGET_SHOP} 以外のURL: {len(bad_url)}行", file=sys.stderr)
        for r in bad_url[:5]:
            print(f"  {r[1]} {r[3]} {r[5]}", file=sys.stderr)
    else:
        print(f"\n[OK] 全URLが {TARGET_SHOP} のカテゴリURLです")

    ok = not bad_url and same_len and set(diff_cols) <= {5}
    if args.check_only:
        print("\n(--check-only のため書き出しなし)")
        return 0 if ok else 1

    if args.in_place:
        if not args.no_backup:
            backup = args.aki.with_suffix(
                f".bak-{datetime.now():%Y%m%d%H%M%S}{args.aki.suffix}"
            )
            shutil.copy2(args.aki, backup)
            print(f"\nバックアップ: {backup.name}")
        sync_rows = None
        if args.sync_name:
            sync_rows, _, _ = fix(
                aki_rows[0], aki_rows[1:], coco_by_item, by_coco, by_aki, sync_name=True
            )
        write_csv_shiftjis(args.aki, sync_rows if sync_rows else url_only)
        print(f"上書き: {args.aki.name}")
    else:
        write_csv_shiftjis(args.out, url_only)
        sync_rows, _, _ = fix(
            aki_rows[0], aki_rows[1:], coco_by_item, by_coco, by_aki, sync_name=True
        )
        write_csv_shiftjis(args.out_sync, sync_rows)
        print(f"\n書き出し: {args.out.name}  （URLのみ）")
        print(f"         {args.out_sync.name}  （カテゴリ名も合わせた参考版）")

    write_report(args.report, report)
    print(f"レポート: {args.report.name}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
