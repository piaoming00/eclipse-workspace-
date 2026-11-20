#!/usr/bin/env python3
"""楽天 GOLD 画像サーバから商品画像を一括ダウンロードする。

画像ファイル名はフォルダごとに不統一（16.jpg / sa9140_top.jpg / 149.jpg …）なので、
商品ページ https://item.rakuten.co.jp/{shop}/{code}/ の HTML から
そのコードのフォルダ配下の画像URLを抽出して取得する。
ページが無い場合は代表的なファイル名を総当たりする。

使い方:
  python3 script/download-item-images-sljapan1.py --codes-file script/codes.txt
  python3 script/download-item-images-sljapan1.py --code SA9140 --code a10827
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
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

SHOP = "sljapan1"
NO_SHOP_DIR = False
CABINET = "07985602"
IMG_ROOT = "img"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PROBE_SUFFIXES = (
    ["{c}.jpg", "{c}_main.jpg"]
    + [f"{{c}}_top{i}.jpg" for i in range(1, 21)]
    + ["{c}_top.jpg"]
    + [f"{{c}}_p{i}.jpg" for i in range(1, 11)]
    + [f"{{c}}_p{i}ss.jpg" for i in range(1, 4)]
    + [f"{{c}}_pc{i}.jpg" for i in range(1, 6)]
    + [f"{{c}}_lp_0{i}.jpg" for i in range(1, 6)]
    + [f"{{c}}_{i}.jpg" for i in range(1, 11)]
    + [f"{{c}}_0{i}.jpg" for i in range(1, 10)]
)
PROBE_NUMERIC_MAX = 140


def fetch(url: str, try_n: int = 3, timeout: int = 30) -> bytes | None:
    for i in range(try_n):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            if e.code >= 500 and i < try_n - 1:
                time.sleep(2 * (i + 1))
                continue
            return None
        except Exception:
            if i < try_n - 1:
                time.sleep(2 * (i + 1))
                continue
            return None
    return None


def head_ok(url: str) -> bool:
    data = fetch(url, try_n=1, timeout=20)
    return bool(data)


def images_from_item_page(code: str) -> list[str]:
    """商品ページから該当フォルダの画像URLを抽出する。"""
    html = fetch(f"https://item.rakuten.co.jp/{SHOP}/{code}/")
    if not html:
        return []
    text = html.decode("utf-8", errors="ignore")
    pat = re.compile(
        rf"https://image\.rakuten\.co\.jp/{SHOP}/cabinet/{CABINET}/{re.escape(code)}/[^\"'\\\s?<>]+",
        re.I,
    )
    seen, out = set(), []
    for m in pat.findall(text):
        u = m.strip()
        if u.lower().endswith((".jpg", ".jpeg", ".png", ".gif")) and u not in seen:
            seen.add(u)
            out.append(u)
    # ファイル名の数字を考慮して並べる（自然順）
    def natkey(u: str):
        parts = re.split(r"(\d+)", u.rsplit("/", 1)[-1])
        return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in parts if t]
    out.sort(key=natkey)
    return out


def probe_folder(code: str, numeric_max: int = PROBE_NUMERIC_MAX) -> list[str]:
    """商品ページが無い/情報不足のときにファイル名を総当たりする。

    接尾辞パターンと連番（1.jpg〜）の両方を必ず調べる
    （接尾辞が見つかっても連番の走査を打ち切らない）。
    """
    base = f"https://image.rakuten.co.jp/{SHOP}/cabinet/{CABINET}/{code}/"
    found: list[str] = []

    for name in PROBE_SUFFIXES:
        u = base + name.format(c=code)
        if head_ok(u):
            found.append(u)

    # 連番は「見つかった最大番号 + 8」までで打ち切る（無駄なリクエストを減らす）
    max_found = 0
    for i in range(1, numeric_max + 1):
        if i > max_found + 8:
            break
        u = base + f"{i}.jpg"
        if head_ok(u):
            found.append(u)
            max_found = i

    return found


def safe_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def alias_candidates(code: str) -> list[str]:
    """画像フォルダが無い場合の別名候補（例: a10827 -> sa10827）。"""
    out = []
    m = re.fullmatch(r"a(\d{4,6})", code)
    if m:
        out.append("sa" + m.group(1))
    m2 = re.fullmatch(r"sa(\d{4,6})", code)
    if m2:
        out.append("a" + m2.group(1))
    return out


def resolve(code: str, min_images: int = 0, force_probe: bool = False) -> tuple[list[str], str, str]:
    """画像URL・取得元・実際に使ったコードを返す。

    min_images: 商品ページから得られた枚数がこれ未満ならフォルダ走査も行い統合する。
    force_probe: 商品ページを使わずフォルダ走査のみ（ページが消えた商品向け）。
    """
    targets = [code] + alias_candidates(code)
    for i, t in enumerate(targets):
        suffix = "" if i == 0 else "(alias)"

        page_urls: list[str] = []
        if not force_probe:
            page_urls = images_from_item_page(t)

        probe_urls: list[str] = []
        if force_probe or len(page_urls) < max(min_images, 1):
            probe_urls = probe_folder(t)

        urls = list(dict.fromkeys(page_urls + probe_urls))
        if not urls:
            continue

        if page_urls and probe_urls:
            source = "item-page+probe" + suffix
        elif page_urls:
            source = "item-page" + suffix
        else:
            source = "probe" + suffix
        return urls, source, t
    return [], "none", code


def process_code(code_raw: str, out_root: str, min_images: int = 0,
                 force_probe: bool = False) -> dict:
    code = code_raw.strip().lower()
    if not code:
        return {}

    urls, source, real = resolve(code, min_images=min_images, force_probe=force_probe)

    saved, skipped, failed = 0, 0, 0
    folder = os.path.join(out_root, code) if NO_SHOP_DIR else os.path.join(out_root, SHOP, code)
    for u in urls:
        name = u.rsplit("/", 1)[-1]
        dst = os.path.join(folder, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            skipped += 1
            continue
        data = fetch(u)
        if not data:
            failed += 1
            continue
        safe_write(dst, data)
        saved += 1
        time.sleep(0.12)

    return dict(code=code, real=real, source=source, found=len(urls),
                saved=saved, skipped=skipped, failed=failed,
                status="ok" if urls else "not-found")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes-file", default=None)
    ap.add_argument("--code", action="append", default=[])
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--min-images", type=int, default=0,
                    help="商品ページの枚数がこれ未満ならフォルダ走査も実施して統合")
    ap.add_argument("--force-probe", action="store_true",
                    help="商品ページを使わずフォルダ走査のみ（ページが消えた商品向け）")
    ap.add_argument("--out", default=IMG_ROOT, help="保存先ルート")
    ap.add_argument("--no-shop-dir", action="store_true",
                    help="<out>/<code>/ に直接保存（店舗名フォルダを作らない）")
    ap.add_argument("--log", default="output/download_images_sljapan1.csv")
    args = ap.parse_args()

    global NO_SHOP_DIR
    NO_SHOP_DIR = args.no_shop_dir
    codes = list(args.code)
    if args.codes_file:
        with open(args.codes_file, encoding="utf-8") as f:
            codes += [ln.strip() for ln in f if ln.strip()]
    codes = [c for c in dict.fromkeys(codes) if c]

    print(f"{len(codes)} codes -> {args.out}/{SHOP}/... ")
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_code, c, args.out, args.min_images, args.force_probe): c
                   for c in codes}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if not r:
                continue
            rows.append(r)
            alias = "" if r["real"] == r["code"] else f" (-> {r['real']})"
            print(f"[{i}/{len(codes)}] {r['code']:<10} {r['status']:<10}{alias:<14} "
                  f"found={r['found']:<3} saved={r['saved']:<3} skip={r['skipped']:<3} fail={r['failed']}")

    rows.sort(key=lambda r: r["code"])
    os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_file = not os.path.exists(args.log)
    with open(args.log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["datetime", "code", "real_code", "status", "source",
                        "found", "saved", "skipped", "failed"])
        for r in rows:
            w.writerow([ts, r["code"], r.get("real", r["code"]), r["status"], r["source"],
                        r["found"], r["saved"], r["skipped"], r["failed"]])

    nf = [r["code"] for r in rows if r["status"] == "not-found"]
    print(f"\n完了: {len(rows)} コード / 画像 {sum(r['saved'] for r in rows)} 枚保存")
    if nf:
        print(f"未取得 ({len(nf)}): {' '.join(nf)}")


if __name__ == "__main__":
    sys.exit(main())
