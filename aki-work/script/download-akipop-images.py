#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
楽天GOLD画像サーバ（cabinet）から、指定した商品コードの画像を「漏れなく」取得する。

  https://image.rakuten.co.jp/{shop}/cabinet/{cabinet}/{code}/...

画像フォルダは一覧取得ができない（フォルダURLは404）ため、次の3経路を統合する。

  1) 商品ページのHTML解析
     https://item.rakuten.co.jp/{shop}/{code}/
     ページ内の /cabinet/{cabinet}/{code}/... を全ホスト分（image/tshop/shop.r10s.jp）抽出
  2) 命名規則の総当たり
     連番 1.jpg〜 / {code}_{n}.jpg / {code}{word}.jpg / {code}_{word}{n}.jpg など
  3) 見つかった名前からの規則展開
     例）sa10899_lp_01.jpg → sa10899_lp_02..99.jpg
         sa10899_sku_01.jpg → sa10899_sku_02..99.jpg
         sa10899_color01.jpg → sa10899_color02..99.jpg

ダウンロード対象は --list（既定: img/aki01/akipop/item_list）に書かれた商品コードのみ。
保存先は --out/{code}/{ファイル名}。

使い方:
  python3 script/download-akipop-images.py --dry-run      # 対象URLの洗い出しだけ
  python3 script/download-akipop-images.py                # ダウンロード
  python3 script/download-akipop-images.py --force        # 既存も取り直す
  python3 script/download-akipop-images.py --deep         # 探索範囲を広げる
"""

from __future__ import annotations

import argparse
import csv
import datetime
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_LIST = ROOT / "img" / "aki01" / "akipop" / "item_list"
DEFAULT_OUT = ROOT / "img" / "aki01" / "akipop"
DEFAULT_REPORT = ROOT / "output" / "download_images_akipop.csv"

DEFAULT_SHOP = "sljapan1"
DEFAULT_CABINET = "07985602"

IMG_HOST = "image.rakuten.co.jp"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

EXTS = ("jpg", "jpeg", "png", "gif")

# 命名規則の辞書（実際のフォルダで確認した color / sku / lp 系を含む）
WORDS = [
    "", "main", "sub", "top", "bottom", "detail", "size", "model", "sp", "pc",
    "thumb", "thumbnail", "img", "image", "photo", "pic", "zoom", "lp", "pop",
    "color", "colour", "sku", "variation", "vari", "set", "item", "bn", "banner",
    "recommend", "review", "point", "campaign", "sale", "new", "rank", "gift",
    "s", "m", "l", "ll", "xl", "1", "2", "3",
]

MIN_BYTES = 1024  # 404ページ（135バイト程度）を画像と誤認しないため


# ---------------------------------------------------------------- 基本処理


def http(url: str, method: str = "GET", retry: int = 3, timeout: int = 30):
    """戻り値: (bytes | None, content_type, size)"""
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                size = int(r.headers.get("Content-Length") or 0)
                data = r.read() if method == "GET" else None
                if data is not None:
                    size = len(data)
                return data, ctype, size
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                return None, "", 0
            if e.code >= 500 and i < retry - 1:
                time.sleep(1.5 * (i + 1))
                continue
            return None, "", 0
        except Exception:
            if i < retry - 1:
                time.sleep(1.5 * (i + 1))
                continue
            return None, "", 0
    return None, "", 0


def is_image_file(path: Path) -> bool:
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    return (
        head.startswith(b"\xff\xd8\xff")          # JPEG
        or head.startswith(b"\x89PNG\r\n\x1a\n")   # PNG
        or head.startswith(b"GIF8")                # GIF
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    )


def head_ok(url: str) -> tuple[bool, int]:
    _, ctype, size = http(url, method="HEAD", retry=2, timeout=20)
    if size < MIN_BYTES:
        return False, size
    if ctype and not ctype.lower().startswith("image/"):
        return False, size
    return True, size


def safe_name(url: str) -> str:
    name = urllib.parse.unquote(url.split("?")[0].rsplit("/", 1)[-1])
    name = name.replace("/", "_").replace("\\", "_").strip()
    return name or "image"


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 入力


def read_codes(path: Path) -> list[str]:
    """1行1コード。カンマ・空白区切り、BOM、#コメントにも対応。"""
    text = path.read_bytes().decode("utf-8-sig", errors="ignore")
    codes: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        for token in re.split(r"[,\s]+", line):
            token = token.strip()
            if token:
                codes.append(token)
    return list(dict.fromkeys(codes))


# ---------------------------------------------------------------- 1) 商品ページ


def urls_from_item_page(shop: str, cabinet: str, code: str) -> list[str]:
    """商品ページHTMLから、この商品のcabinet画像URLを抽出する。"""
    html = b""
    for suffix in ("", "?scid=af_pc_etc"):
        data, _ctype, _size = http(
            f"https://item.rakuten.co.jp/{shop}/{code}/{suffix}", timeout=30
        )
        if data:
            html = data
            break
    if not html:
        return []

    text = None
    for enc in ("euc-jp", "utf-8", "cp932"):
        try:
            text = html.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = html.decode("euc-jp", errors="replace")

    # ホスト違い・バッククォートのエスケープを吸収して、パス部分だけ拾う
    text = text.replace("\\/", "/")
    pat = re.compile(
        rf"/(?P<shop>{re.escape(shop)})/cabinet/(?P<cab>{re.escape(cabinet)})/"
        rf"(?P<rest>[^\"'\s<>()]+)",
        re.I,
    )
    out: list[str] = []
    code_l = code.lower()
    for m in pat.finditer(text):
        rest = m.group("rest").split("?")[0].split("#")[0].rstrip("\\")
        if "\\" in rest or not rest.lower().endswith(tuple("." + e for e in EXTS)):
            continue
        rest_l = rest.lower()
        # この商品のフォルダ配下、またはファイル名が商品コードで始まるものだけ
        if rest_l.startswith(code_l + "/") or rest_l.startswith(code_l + "_") \
                or rest_l.startswith(code_l + "."):
            out.append(f"https://{IMG_HOST}/{shop}/cabinet/{cabinet}/{rest}")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 2) 総当たり


def probe_candidates(code: str, max_n: int, deep: bool) -> list[str]:
    """命名規則から候補URLを組み立てる（重複なし）。"""
    words = WORDS if not deep else WORDS + [
        "a", "b", "c", "d", "front", "back", "side", "up", "down", "flat",
        "wearing", "coord", "coordinate", "styling", "look", "cat", "rank1",
        "osusume", "tokuten", "fair", "coupon", "sp1", "pc1", "smartphone",
    ]
    nums = max_n
    cands: list[str] = []

    def add(name: str) -> None:
        cands.append(name)

    # 連番のみ（1.jpg 〜）
    for n in range(1, nums + 1):
        add(f"{n}.jpg")

    # コード単体・コード+連番
    for ext in ("jpg", "jpeg", "png", "gif"):
        add(f"{code}.{ext}")
    for n in range(1, nums + 1):
        add(f"{code}_{n}.jpg")
        add(f"{code}-{n}.jpg")
    for n in range(1, nums + 1):
        add(f"{code}_{n:02d}.jpg")
        add(f"{code}_{n:03d}.jpg")

    # コード+単語 / コード_単語 / コード_単語+連番 / コード_単語_連番
    for w in words:
        if not w:
            continue
        add(f"{code}{w}.jpg")
        add(f"{code}_{w}.jpg")
        add(f"{code}-{w}.jpg")
        for ext in ("png", "gif"):
            add(f"{code}_{w}.{ext}")
        for n in (1, 2, 3, 4, 5):
            add(f"{code}_{w}{n}.jpg")
            add(f"{code}_{w}{n:02d}.jpg")
            add(f"{code}_{w}_{n}.jpg")
            add(f"{code}_{w}_{n:02d}.jpg")
            add(f"{code}-{w}-{n}.jpg")
    return list(dict.fromkeys(cands))


def probe_folder(shop: str, cabinet: str, code: str, max_n: int, deep: bool,
                 workers: int) -> tuple[dict[str, int], int]:
    """候補URLをHEADで確認し、{url: size} と試行数を返す。"""
    base = f"https://{IMG_HOST}/{shop}/cabinet/{cabinet}/{code}/"
    cands = probe_candidates(code, max_n, deep)
    found: dict[str, int] = {}

    def check(name: str):
        url = base + name
        ok, size = head_ok(url)
        return url, ok, size

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for url, ok, size in ex.map(check, cands):
            if ok and url not in found:
                found[url] = size
    return found, len(cands)


# ---------------------------------------------------------------- 3) 規則展開


def expand_from_found(found: dict[str, int], shop: str, cabinet: str, code: str,
                      max_n: int, gap: int, workers: int) -> tuple[dict[str, int], int]:
    """見つかったファイル名の数字部分を伸ばして、続きの連番を探す。

    例）sa10899_lp_01.jpg → sa10899_lp_02..99.jpg
        sa10899_color01.jpg → sa10899_color02..99.jpg
        sa10899_sku_02.jpg → sa10899_sku_03..99.jpg
    """
    base = f"https://{IMG_HOST}/{shop}/cabinet/{cabinet}/{code}/"
    # pattern（数字を{n}に置換） -> {桁数: 開始番号}
    patterns: dict[str, dict[int, int]] = {}

    for url in found:
        name = safe_name(url)
        for m in re.finditer(r"\d+", name):
            digits = m.group(0)
            pattern = name[: m.start()] + "{n}" + name[m.end():]
            widths = patterns.setdefault(pattern, {})
            widths.setdefault(len(digits), int(digits))

    candidates: list[str] = []
    for pattern, widths in patterns.items():
        head_part, tail_part = pattern.split("{n}", 1)
        for width, start in widths.items():
            misses = 0
            n = start + 1
            while n <= max_n and misses < gap:
                text = f"{n:0{width}d}" if width > 1 else str(n)
                cand = base + head_part + text + tail_part
                if cand not in found:
                    ok, _size = head_ok(cand)
                    if ok:
                        candidates.append(cand)
                        misses = 0
                    else:
                        misses += 1
                else:
                    misses = 0
                n += 1

    extra: dict[str, int] = {}
    for c in dict.fromkeys(candidates):
        extra[c] = 0
    return extra, len(extra)


# ---------------------------------------------------------------- ダウンロード


def download_all(shop: str, cabinet: str, code: str, sources: dict[str, str],
                 out_dir: Path, force: bool, workers: int) -> list[dict]:
    rows: list[dict] = []

    def work(url: str):
        name = safe_name(url)
        dst = out_dir / name
        if not force and dst.exists() and dst.stat().st_size >= MIN_BYTES and is_image_file(dst):
            return dict(filename=name, url=url, source=sources[url],
                        bytes=dst.stat().st_size, status="skipped")
        data, ctype, _size = http(url, timeout=60)
        if not data:
            return dict(filename=name, url=url, source=sources[url], bytes=0, status="failed(取得不可)")
        tmp = dst.with_suffix(dst.suffix + ".part")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        if len(data) < MIN_BYTES or not is_image_file(tmp):
            tmp.unlink(missing_ok=True)
            return dict(filename=name, url=url, source=sources[url], bytes=len(data),
                        status=f"failed(画像でない ctype={ctype})")
        os.replace(tmp, dst)
        return dict(filename=name, url=url, source=sources[url], bytes=len(data), status="saved")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(work, sources.keys()))
    return rows


# ---------------------------------------------------------------- main


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="cabinetフォルダから指定商品コードの画像を漏れなくダウンロードする"
    )
    ap.add_argument("--list", type=Path, default=DEFAULT_LIST, help="商品コード一覧ファイル")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="保存先ルート（<out>/<code>/）")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="取得ログCSV")
    ap.add_argument("--shop", default=DEFAULT_SHOP)
    ap.add_argument("--cabinet", default=DEFAULT_CABINET)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-n", type=int, default=200, help="連番の上限")
    ap.add_argument("--gap", type=int, default=5, help="規則展開で連続未検出を打ち切る数")
    ap.add_argument("--deep", action="store_true", help="辞書・探索範囲を広げる")
    ap.add_argument("--force", action="store_true", help="既存ファイルも再取得する")
    ap.add_argument("--dry-run", action="store_true", help="URLの洗い出しのみ（保存しない）")
    args = ap.parse_args()

    list_path = args.list
    if not list_path.exists():
        # 旧配置（img/item_list）に置かれている場合のフォールバック
        alt = ROOT / "img" / "item_list"
        if alt.exists():
            print(f"[WARN] {list_path} が無いため {alt} を使用します", file=sys.stderr)
            list_path = alt
        else:
            print(f"[ERROR] 商品コード一覧が見つかりません: {args.list}", file=sys.stderr)
            return 1

    codes = read_codes(list_path)
    if not codes:
        print(f"[ERROR] 商品コードが空です: {args.list}", file=sys.stderr)
        return 1

    print(f"商品コード: {len(codes)} 件  ({', '.join(codes)})")
    print(f"cabinet   : https://{IMG_HOST}/{args.shop}/cabinet/{args.cabinet}/<code>/")
    print(f"保存先    : {args.out}/<code>/")
    print(f"モード    : {'dry-run' if args.dry_run else 'download'} / "
          f"max-n={args.max_n} gap={args.gap} deep={args.deep}\n")

    all_rows: list[dict] = []
    summary: list[dict] = []
    ng = False

    for code in codes:
        t0 = time.time()
        page = urls_from_item_page(args.shop, args.cabinet, code)
        probed, tried = probe_folder(args.shop, args.cabinet, code, args.max_n, args.deep, args.workers)
        derived, tried2 = expand_from_found(probed, args.shop, args.cabinet, code,
                                            args.max_n, args.gap, args.workers)

        sources: dict[str, str] = {}
        for u in page:
            sources[u] = "item-page"
        for u in probed:
            sources.setdefault(u, "probe")
        for u in derived:
            sources.setdefault(u, "derive")

        page_status = "ok" if page else "参照なし(page404等)"
        print(f"--- {code}: 商品ページ {len(page)}枚 ({page_status}) / "
              f"総当たり {len(probed)}枚 (試行{tried}) / 規則展開 {len(derived)}枚 (試行{tried2}) "
              f"→ 合計 {len(sources)}枚")

        if args.dry_run:
            for u in sorted(sources, key=lambda x: natural_key(safe_name(x))):
                print(f"    [{sources[u]:<9}] {u}")
            summary.append(dict(code=code, page=len(page), probe=len(probed),
                                derived=len(derived), total=len(sources),
                                saved=0, skipped=0, failed=0, seconds=time.time() - t0))
            if not sources:
                ng = True
            continue

        rows = download_all(args.shop, args.cabinet, code, sources, args.out / code,
                            args.force, args.workers)
        rows.sort(key=lambda r: natural_key(r["filename"]))
        for r in rows:
            r["code"] = code
            r["page"] = "item-page" in (r["source"] or "")
        all_rows.extend(rows)

        saved = sum(1 for r in rows if r["status"] == "saved")
        skipped = sum(1 for r in rows if r["status"] == "skipped")
        failed = [r for r in rows if r["status"].startswith("failed")]
        summary.append(dict(code=code, page=len(page), probe=len(probed),
                            derived=len(derived), total=len(sources),
                            saved=saved, skipped=skipped, failed=len(failed),
                            seconds=time.time() - t0))
        print(f"    保存 {saved} / 既存スキップ {skipped} / 失敗 {len(failed)} "
              f"({time.time() - t0:.1f}s)")
        for r in failed:
            print(f"    [NG] {r['filename']} {r['status']} {r['url']}", file=sys.stderr)
        if failed or not sources:
            ng = True

    # ---- ログ
    if not args.dry_run:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        new_file = not args.report.exists()
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with args.report.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["datetime", "code", "filename", "source", "bytes", "status", "url"])
            for r in all_rows:
                w.writerow([ts, r["code"], r["filename"], r["source"],
                            r["bytes"], r["status"], r["url"]])

    print("\n=== まとめ ===")
    print(f"{'code':<10} {'page':>5} {'probe':>6} {'derive':>7} {'total':>6} "
          f"{'保存':>5} {'skip':>5} {'失敗':>4}")
    for s in summary:
        print(f"{s['code']:<10} {s['page']:>5} {s['probe']:>6} {s['derived']:>7} "
              f"{s['total']:>6} {s['saved']:>5} {s['skipped']:>5} {s['failed']:>4}")
    total = sum(s["total"] for s in summary)
    saved = sum(s["saved"] for s in summary)
    skipped = sum(s["skipped"] for s in summary)
    failed = sum(s["failed"] for s in summary)
    print(f"合計: {total}枚（保存 {saved} / 既存 {skipped} / 失敗 {failed}）")
    if not args.dry_run:
        print(f"ログ: {args.report}")
    if ng:
        print("\n[NG] 未取得または画像0枚の商品があります（上記ログを確認）", file=sys.stderr)
        return 1
    print("\n[OK] 全商品で画像を取得しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
