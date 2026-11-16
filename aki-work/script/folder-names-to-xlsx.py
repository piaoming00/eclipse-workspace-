#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フォルダ内の「名前」を取り出して Excel(.xlsx) を作成する一時スクリプト。

使い方:
  # 1) フォルダを走査して一覧化（サブフォルダも含む）
  python3 script/folder-names-to-xlsx.py -d ~/Downloads/対象フォルダ -o names.xlsx

  # 2) テキスト（1行1名）から一覧化
  python3 script/folder-names-to-xlsx.py -t names.txt -o names.xlsx

  # 3) 一覧だけ確認（Excel を作らない）
  python3 script/folder-names-to-xlsx.py -d ~/Downloads/対象フォルダ --dry-run
"""
import argparse
import os
import sys
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADERS = ["No", "種類", "名前", "拡張子", "相対パス", "サイズ(KB)", "更新日時"]


def human_size(num):
    if num is None:
        return None
    return round(num / 1024, 1)


def scan_dir(root, recursive=True):
    rows = []
    root = os.path.abspath(os.path.expanduser(root))
    if recursive:
        walker = os.walk(root)
    else:
        walker = [
            (root, [], [e.name for e in os.scandir(root) if e.is_file()])
        ]
    for dirpath, dirnames, filenames in walker:
        dirnames.sort()
        for d in sorted(dirnames):
            full = os.path.join(dirpath, d)
            rows.append(
                ("フォルダ", d, "", os.path.relpath(full, root), None,
                 datetime.fromtimestamp(os.path.getmtime(full)))
            )
        for f in sorted(filenames):
            if f.startswith(".") or f == ".DS_Store":
                continue
            full = os.path.join(dirpath, f)
            stem, ext = os.path.splitext(f)
            rows.append(
                ("ファイル", stem, ext.lower(), os.path.relpath(full, root),
                 human_size(os.path.getsize(full)),
                 datetime.fromtimestamp(os.path.getmtime(full)))
            )
    rows.sort(key=lambda r: (r[0] != "フォルダ", r[3].lower(), r[1].lower()))
    return rows


def read_text(path):
    rows = []
    with open(os.path.expanduser(path), encoding="utf-8-sig") as fh:
        for line in fh:
            name = line.strip()
            if not name:
                continue
            stem, ext = os.path.splitext(name)
            rows.append(("ファイル", stem, ext, name, None, None))
    return rows


def write_xlsx(rows, out_path, title="names", name_only=False):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]

    if name_only:
        ws.append(["名前"])
        for _kind, name, ext, _relpath, _size, _mtime in rows:
            ws.append([f"{name}{ext}"])
        ws.column_dimensions["A"].width = 60
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:A{ws.max_row}"
        out_path = os.path.expanduser(out_path)
        wb.save(out_path)
        return out_path

    ws.append(HEADERS)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="4F81BD")
    for cell in ws[1]:
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for i, (kind, name, ext, relpath, size, mtime) in enumerate(rows, start=1):
        ws.append([i, kind, name, ext, relpath, size, mtime])

    widths = [6, 10, 46, 10, 52, 12, 20]
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    for row in ws.iter_rows(min_row=2):
        row[6].number_format = "yyyy-mm-dd hh:mm"
        row[5].alignment = Alignment(horizontal="right")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{ws.max_row}"

    out_path = os.path.expanduser(out_path)
    wb.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("-d", "--dir", help="走査するフォルダ")
    src.add_argument("-t", "--text", help="1行1名のテキストファイル")
    ap.add_argument("-o", "--out", default="names.xlsx", help="出力 xlsx")
    ap.add_argument("--no-recursive", action="store_true", help="サブフォルダを辿らない")
    ap.add_argument("--dry-run", action="store_true", help="一覧表示のみ（Excel を作らない）")
    ap.add_argument("--name-only", action="store_true", help="Excel に「名前」列だけを出力")
    args = ap.parse_args()

    if args.dir:
        if not os.path.isdir(os.path.expanduser(args.dir)):
            sys.exit(f"フォルダが見つかりません: {args.dir}")
        rows = scan_dir(args.dir, recursive=not args.no_recursive)
    else:
        rows = read_text(args.text)

    if not rows:
        sys.exit("対象が 0 件でした。")

    for i, (kind, name, ext, relpath, size, _mtime) in enumerate(rows, start=1):
        print(f"{i:>3}  {kind:<6} {relpath}")

    if args.dry_run:
        print(f"\n合計 {len(rows)} 件（--dry-run のため Excel 未作成）")
        return

    title = os.path.splitext(os.path.basename(args.out))[0] or "names"
    out = write_xlsx(rows, args.out, title=title, name_only=args.name_only)
    print(f"\n合計 {len(rows)} 件 -> {out}")


if __name__ == "__main__":
    main()
