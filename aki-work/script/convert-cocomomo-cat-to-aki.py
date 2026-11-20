#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
category.xlsx を対応表として、
  1) item-cat_cocomomo.csv のカテゴリを item-cat_aki.csv の表記に合わせ、
     カテゴリURL も AKI（aki-select）のURLへ差し替えた CSV を作る
  2) item-cat_aki.csv は URL 列のみ検証・差し替える（行の追加・削除・並替はしない）

出力:
  items/category/item-cat_cocomomo-to-aki.csv   変換後CSV（cp932 / CRLF）
  items/category/report-cocomomo-to-aki.csv     変換レポート（UTF-8 BOM）
  items/category/report-cocomomo-unmapped.csv   対応表に無く除外した行（UTF-8 BOM）
  items/category/report-item-cat-aki-url.csv    aki CSV の URL 検証レポート

使い方:
  python3 script/convert-cocomomo-cat-to-aki.py
  python3 script/convert-cocomomo-cat-to-aki.py --check-only
  python3 script/convert-cocomomo-cat-to-aki.py --force-aki-write   # 差分0でもaki CSVを書き直す
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import sys
import unicodedata
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
CAT_DIR = ROOT / "items" / "category"

DEFAULT_MAPPING = CAT_DIR / "category.xlsx"
DEFAULT_COCO = CAT_DIR / "item-cat_cocomomo.csv"
DEFAULT_AKI = CAT_DIR / "item-cat_aki.csv"
DEFAULT_OUT = CAT_DIR / "item-cat_cocomomo-to-aki.csv"
DEFAULT_REPORT = CAT_DIR / "report-cocomomo-to-aki.csv"
DEFAULT_UNMAPPED = CAT_DIR / "report-cocomomo-unmapped.csv"
DEFAULT_AKI_REPORT = CAT_DIR / "report-item-cat-aki-url.csv"

TARGET_SHOP = "aki-select"

URL_RE = re.compile(
    r"^https?://item\.rakuten\.co\.jp/(?P<shop>[^/]+)/c/(?P<code>\d+)/?$"
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


def non_cp932_chars(rows: list[list[str]]) -> Counter[str]:
    """cp932 で表現できない文字を洗い出す（文字化けの事故防止）。"""
    bad: Counter[str] = Counter()
    for row in rows:
        for cell in row:
            for ch in str(cell):
                try:
                    ch.encode("cp932")
                except UnicodeEncodeError:
                    bad[ch] += 1
    return bad


def write_csv_shiftjis(path: Path, rows: list[list[str]]) -> None:
    """楽天RMSアップロード用: cp932 / CRLF / 最小クォート。"""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue().encode("cp932", errors="replace"))


def write_report(path: Path, rows: list[list[str]]) -> None:
    """確認用レポート: Excelでそのまま開ける UTF-8 BOM / CRLF。"""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def priority_of(row: list[str]) -> int:
    try:
        return int(str(row[4]).strip())
    except (TypeError, ValueError, IndexError):
        return 10**9


def load_mapping(path: Path) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """category.xlsx → (正規化名→行, COCOMOMO ID→行, AKI ID→行)"""
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


def resolve(cat_name: str, code: str | None, by_name, by_coco):
    """カテゴリ名 → 親カテゴリ → COCOMOMO ID の順で対応表を引く。"""
    key = normalize_category(cat_name)
    if key in by_name:
        return by_name[key], "name"
    parts = key.split("\\")
    for i in range(len(parts) - 1, 0, -1):
        parent = "\\".join(parts[:i])
        if parent in by_name:
            return by_name[parent], f"parent:{parent}"
    if code and code in by_coco:
        return by_coco[code], "code"
    return None, "none"


def aki_canonical_names(aki_rows: list[list[str]]) -> dict[str, str]:
    """item-cat_aki.csv で実際に使われている「カテゴリID → 表示名」を作る。"""
    names: dict[str, str] = {}
    for row in aki_rows:
        code = parse_url(row[5])[1] if len(row) > 5 else None
        if code:
            names.setdefault(code, row[3])
    return names


def to_aki_text(text: str) -> str:
    """CSV（cp932）に載せる前提で表記をそろえる。

    - 階層区切り ¥ / ￥ / ＼ → \\（item-cat_aki.csv と同じ）
    - 波ダッシュ − 〜 ∼ → ～（RMS のCSV書き出しと同じ全角チルダ）
    """
    s = str(text)
    for ch in ("¥", "￥", "＼"):
        s = s.replace(ch, "\\")
    for ch in ("~", "〜", "∼"):
        s = s.replace(ch, "～")
    return s


def canonical_name(entry: dict, aki_names: dict[str, str]) -> str:
    """AKI側の表記に合わせる。

    1) item-cat_aki.csv に同じAKIカテゴリIDがあれば、その表示名をそのまま使う
    2) 無ければ category.xlsx の表示名を AKI の表記に直して使う
    """
    if entry["aki"] in aki_names:
        return aki_names[entry["aki"]]
    return to_aki_text(entry["name"])


# ---------------------------------------------------------------- 1) COCOMOMO 変換


def convert_cocomomo(
    header: list[str],
    rows: list[list[str]],
    by_name,
    by_coco,
    aki_names: dict[str, str],
    item_filter: set[str] | None = None,
) -> tuple[list[list[str]], list[list[str]], list[list[str]], dict]:
    ncol = len(header)
    out: list[list[str]] = []
    report: list[list[str]] = [
        ["行番号", "商品管理番号", "元カテゴリ", "出力カテゴリ", "結果", "一致方法", "変更前URL", "変更後URL"]
    ]
    unmapped: list[list[str]] = [
        ["行番号", "商品管理番号", "商品名", "元カテゴリ", "優先度", "元URL", "理由"]
    ]
    stats = Counter()
    registered: dict[tuple[str, str], int] = OrderedDict()
    parentization: Counter[str] = Counter()
    renamed: Counter[tuple[str, str]] = Counter()
    unmapped_cats: Counter[str] = Counter()
    dropped_items: Counter[str] = Counter()
    all_items = {
        r[1]
        for r in rows
        if len(r) > 1 and (item_filter is None or r[1] in item_filter)
    }

    for idx, row in enumerate(rows, start=2):
        row = list(row) + [""] * (ncol - len(row))
        item_id, cat_name, url = row[1], row[3], row[5]
        _, code = parse_url(url)

        if item_filter is not None and item_id not in item_filter:
            stats["skip_not_in_aki"] += 1
            continue

        entry, how = resolve(cat_name, code, by_name, by_coco)

        if entry is None:
            stats["unmapped"] += 1
            unmapped_cats[cat_name] += 1
            dropped_items[item_id] += 1
            unmapped.append([idx, item_id, row[2], cat_name, row[4], url, "category.xlsx に対応なし"])
            report.append([idx, item_id, cat_name, "", "除外(対応表に無し)", how, url, ""])
            continue

        out_name = canonical_name(entry, aki_names)
        new_url = build_url(entry["aki"])
        if normalize_category(out_name) != normalize_category(cat_name):
            renamed[(cat_name, out_name)] += 1
        if how.startswith("parent:"):
            parentization[cat_name] += 1

        key = (item_id, entry["aki"])
        if key in registered:
            stats["duplicate"] += 1
            pos = registered[key]
            report.append([idx, item_id, cat_name, out_name, "重複除外", how, url, out[pos][5]])
            if priority_of(row) < priority_of(out[pos]):
                row[3] = out_name
                row[5] = new_url
                out[pos] = row
            continue

        registered[key] = len(out)
        row[3] = out_name
        row[5] = new_url
        out.append(row)
        stats["converted"] += 1
        stats[f"how_{how.split(':')[0]}"] += 1
        report.append([idx, item_id, cat_name, out_name, "変換", how, url, new_url])

    stats["total_in"] = len(rows)
    stats["total_out"] = len(out)
    out_items = {r[1] for r in out}
    stats["items"] = len(out_items)
    stats["cats"] = len({normalize_category(r[3]) for r in out})
    lost_items = sorted(all_items - out_items)
    stats["lost_items"] = len(lost_items)
    meta = {
        "stats": stats,
        "parentization": parentization,
        "renamed": renamed,
        "unmapped_cats": unmapped_cats,
        "lost_items": lost_items,
    }
    return [header] + out, report, unmapped, meta


# ---------------------------------------------------------------- 2) AKI CSV のURLのみ差し替え


def normalize_aki_urls(
    rows: list[list[str]], by_name, by_aki
) -> tuple[list[list[str]], list[list[str]], dict]:
    header, body = rows[0], rows[1:]
    ncol = len(header)
    out: list[list[str]] = []
    report: list[list[str]] = [
        ["行番号", "商品管理番号", "表示先カテゴリ", "結果", "一致方法", "変更前URL", "変更後URL"]
    ]
    stats = Counter()
    unmatched: Counter[str] = Counter()

    for idx, row in enumerate(body, start=2):
        row = list(row) + [""] * (ncol - len(row))
        _, code = parse_url(row[5])
        entry, how = resolve(row[3], code, by_name, by_aki)

        if entry is None:
            stats["unmatched"] += 1
            unmatched[row[3]] += 1
            report.append([idx, row[1], row[3], "未対応(URL変更なし)", how, row[5], row[5]])
            out.append(row)
            continue

        new_url = build_url(entry["aki"])
        if new_url == row[5]:
            stats["same"] += 1
            report.append([idx, row[1], row[3], "変更なし", how, row[5], new_url])
        else:
            stats["changed"] += 1
            report.append([idx, row[1], row[3], "URL差し替え", how, row[5], new_url])
        row[5] = new_url
        out.append(row)

    stats["total"] = len(out)
    stats["items"] = len({r[1] for r in out})
    return [header] + out, report, {"stats": stats, "unmatched": unmatched}


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(
        description="COCOMOMO のカテゴリを AKI に合わせて変換し、AKI CSV は URL のみ差し替える"
    )
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    ap.add_argument("--coco", type=Path, default=DEFAULT_COCO)
    ap.add_argument("--aki", type=Path, default=DEFAULT_AKI)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--unmapped-report", type=Path, default=DEFAULT_UNMAPPED)
    ap.add_argument("--aki-report", type=Path, default=DEFAULT_AKI_REPORT)
    ap.add_argument("--check-only", action="store_true", help="検証のみ（書き出しなし）")
    ap.add_argument(
        "--only-aki-items",
        action="store_true",
        help="item-cat_aki.csv に存在する商品だけを出力（既定はCOCOMOMO全商品）",
    )
    ap.add_argument(
        "--force-aki-write",
        action="store_true",
        help="item-cat_aki.csv に差分が無くてもURL列を書き直す",
    )
    ap.add_argument("--no-backup", action="store_true", help="上書き時に .bak を作らない")
    args = ap.parse_args()

    for p in (args.mapping, args.coco, args.aki):
        if not p.exists():
            print(f"[ERROR] 見つかりません: {p}", file=sys.stderr)
            return 1
    if args.out.resolve() in (args.coco.resolve(), args.aki.resolve()):
        print("[ERROR] --out に変換元と同じファイルは指定できません", file=sys.stderr)
        return 1

    by_name, by_coco, by_aki = load_mapping(args.mapping)
    coco_rows, coco_enc = read_csv_auto(args.coco)
    aki_rows, aki_enc = read_csv_auto(args.aki)
    if coco_rows[0] != aki_rows[0]:
        print("[WARN] ヘッダーが一致しません（ベースのヘッダーを使用）", file=sys.stderr)

    aki_names = aki_canonical_names(aki_rows[1:])
    item_filter = {r[1] for r in aki_rows[1:] if len(r) > 1} if args.only_aki_items else None
    coco_out, coco_report, unmapped_rows, meta = convert_cocomomo(
        coco_rows[0], coco_rows[1:], by_name, by_coco, aki_names, item_filter
    )
    s = meta["stats"]

    aki_out, aki_report, aki_meta = normalize_aki_urls(aki_rows, by_name, by_aki)
    a = aki_meta["stats"]

    # ---- 検証：出力URLがすべて aki-select の対応表AKI IDか
    bad = []
    for r in coco_out[1:]:
        shop, code = parse_url(r[5])
        if shop != TARGET_SHOP or code not in by_aki:
            bad.append(r)
    aki_bad = [r for r in aki_out[1:] if parse_url(r[5])[0] != TARGET_SHOP]

    print("=== 1) COCOMOMO → AKI 変換 ===")
    print(f"元ファイル    : {args.coco.name}  ({coco_enc}, {s['total_in']}行 / "
          f"{len({r[1] for r in coco_rows[1:]})}商品)")
    print(f"出力          : {args.out.name}")
    print(f"  変換          : {s['converted']}行")
    print(f"    ├ 名前一致  : {s['how_name']}")
    print(f"    ├ 親に寄せ  : {s['how_parent']}")
    print(f"    └ ID一致    : {s['how_code']}")
    print(f"  重複除外      : {s['duplicate']}行（同一商品×同一AKIカテゴリ）")
    print(f"  除外(未対応)  : {s['unmapped']}行")
    if s["skip_not_in_aki"]:
        print(f"  対象外商品    : {s['skip_not_in_aki']}行（--only-aki-items）")
    print(f"  出力合計      : {s['total_out']}行 / {s['items']}商品 / {s['cats']}カテゴリ")
    if s["lost_items"]:
        print(f"  [注意] 全行除外で出力に残らない商品: {s['lost_items']}件 "
              f"({', '.join(meta['lost_items'])})")

    if meta["renamed"]:
        print("\n--- カテゴリ名をAKI表記へ変更 ---")
        for (src, dst), n in meta["renamed"].most_common():
            print(f"  {n:5d}行  {src!r} → {dst!r}")

    if meta["parentization"]:
        print("\n--- 対応表に無いため親カテゴリへ寄せたもの ---")
        for cat, n in meta["parentization"].most_common():
            entry, _ = resolve(cat, None, by_name, by_coco)
            print(f"  {n:5d}行  {cat!r} → {canonical_name(entry, aki_names)!r}")

    if meta["unmapped_cats"]:
        print("\n--- category.xlsx に対応が無く除外したカテゴリ ---")
        for cat, n in meta["unmapped_cats"].most_common():
            print(f"  {n:5d}行  {cat!r}")

    print("\n=== 2) item-cat_aki.csv（URL列のみ） ===")
    print(f"対象          : {args.aki.name}  ({aki_enc}, {a['total']}行 / {a['items']}商品)")
    print(f"  変更なし      : {a['same']}行")
    print(f"  URL差し替え   : {a['changed']}行")
    print(f"  未対応        : {a['unmatched']}行")
    print(f"  行の増減      : なし（{len(aki_rows) - 1}行 → {a['total']}行）")

    if bad:
        print(f"\n[NG] aki-select 以外/対応表に無いURL: {len(bad)}行", file=sys.stderr)
        for r in bad[:5]:
            print(f"  {r[1]} {r[3]} {r[5]}", file=sys.stderr)
    else:
        print(f"\n[OK] 変換後CSVのURLはすべて {TARGET_SHOP} のAKIカテゴリIDです")

    if aki_bad:
        print(f"[NG] item-cat_aki.csv に {TARGET_SHOP} 以外のURL: {len(aki_bad)}行", file=sys.stderr)

    ng_chars = non_cp932_chars(coco_out + aki_out)
    if ng_chars:
        print("\n[NG] cp932で保存できない文字が残っています", file=sys.stderr)
        for ch, n in ng_chars.most_common():
            print(f"  U+{ord(ch):04X} {ch!r} × {n}", file=sys.stderr)

    ok = not bad and not aki_bad and not ng_chars
    if args.check_only:
        print("\n(--check-only のため書き出しなし)")
        return 0 if ok else 1

    # ---- 書き出し
    if meta["lost_items"]:
        unmapped_rows.append([])
        unmapped_rows.append(["※ 全行が除外され、出力CSVに1行も残らない商品"])
        for item_id in meta["lost_items"]:
            unmapped_rows.append(["", item_id])

    write_csv_shiftjis(args.out, coco_out)
    write_report(args.report, coco_report)
    write_report(args.unmapped_report, unmapped_rows)

    aki_written = False
    if a["changed"] == 0 and not args.force_aki_write:
        print("\nitem-cat_aki.csv は全行URLが正しいため書き換えません"
              "（--force-aki-write で強制書き出し）")
    else:
        if not args.no_backup:
            backup = args.aki.with_suffix(
                f".bak-{datetime.now():%Y%m%d%H%M%S}{args.aki.suffix}"
            )
            shutil.copy2(args.aki, backup)
            print(f"\nバックアップ: {backup.name}")
        write_csv_shiftjis(args.aki, aki_out)
        aki_written = True
    write_report(args.aki_report, aki_report)

    print(f"書き出し      : {args.out}")
    print(f"レポート      : {args.report.name} / {args.unmapped_report.name} / {args.aki_report.name}")
    print(f"aki CSV 更新  : {'あり' if aki_written else 'なし（差分0）'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
