#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
トップバナーの背景を「きれいな単色（元画像のベージュ）」に整え、4K（幅3840）で書き出す。

- 背景紙のテクスチャ・キズ・シミを除去し、元画像の背景色（中央値）で塗り直す
- 写真コラージュとロゴ文字は保持（高品位アップスケール + 軽いアンシャープ）
- AI生成は使わない（Pillow の決定論的処理のみ）
- 既存ファイルは上書きしない

使用例:
  python3 script/upscale-4k-cleanbg.py --input img/top/IMG_1674.JPG --width 3840
"""
import argparse
import os
from datetime import datetime
from importlib import util

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = util.spec_from_file_location(
    "banner_bg_retouch", os.path.join(HERE, "banner-bg-retouch.py"))
_retouch = util.module_from_spec(_spec)
_spec.loader.exec_module(_retouch)


def build_foreground(src, tolerance=62):
    """前景（写真＋文字）をアルファ付きで返す"""
    rgb = np.asarray(src.convert("RGB"), dtype=np.uint8)
    alpha, bg, rect = _retouch.background_mask(rgb, tolerance=tolerance, feather=0)
    a = (np.clip(1.0 - alpha, 0.0, 1.0) * 255).astype(np.uint8)  # 前景アルファ
    a = np.asarray(Image.fromarray(a, "L").filter(ImageFilter.GaussianBlur(0.6)))
    fg = Image.fromarray(rgb, "RGB").convert("RGBA")
    fg.putalpha(Image.fromarray(a, "L"))
    return fg, tuple(int(v) for v in bg), rect


def unsharp(img, radius=1.6, percent=70, threshold=2):
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b)).filter(
        ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))
    r2, g2, b2 = rgb.split()
    return Image.merge("RGBA", (r2, g2, b2, a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", default="img/top")
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--tolerance", type=int, default=62)
    ap.add_argument("--suffix", default="-4k")
    ap.add_argument("--bg-style", default="flat", choices=["flat", "wall"],
                    help="flat: 元色の単色 / wall: 漆喰壁スタイル（参考画像風）")
    ap.add_argument("--quality", type=int, default=95)
    ap.add_argument("--wall-light", type=float, default=1.0)
    ap.add_argument("--wall-texture", type=float, default=1.0)
    args = ap.parse_args()

    _retouch.WALL_LIGHT = args.wall_light
    _retouch.WALL_TEXTURE = args.wall_texture

    src = Image.open(args.input).convert("RGB")
    w0, h0 = src.size
    scale = args.width / float(w0)
    w1, h1 = args.width, int(round(h0 * scale))

    fg, bg, rect = build_foreground(src, tolerance=args.tolerance)

    # 前景をアップスケール（LANCZOS）＋軽くアンシャープ
    fg_big = fg.resize((w1, h1), Image.LANCZOS)
    fg_big = unsharp(fg_big, radius=1.6, percent=65, threshold=3)

    if args.bg_style == "wall":
        rect_big = tuple(int(round(v * scale)) for v in rect)
        out = Image.alpha_composite(
            _retouch.make_background((w1, h1), variant="d", rect=rect_big), fg_big
        ).convert("RGB")
        os.makedirs(args.outdir, exist_ok=True)
        stem0 = os.path.splitext(os.path.basename(args.input))[0]
        final = os.path.join(args.outdir, f"{stem0}{args.suffix}-wall.jpg")
        n = 1
        base = final[:-4]
        while os.path.exists(final):
            n += 1
            final = f"{base}_{n:02d}.jpg"
        out.save(final, quality=args.quality, subsampling=1, optimize=True, dpi=(300, 300))
        prev = out.copy()
        prev.thumbnail((1600, 1600), Image.LANCZOS)
        prev_path = os.path.join("/tmp", f"preview-{stem0}{args.suffix}-wall.jpg")
        prev.save(prev_path, quality=90)
        log = "output/image_edit_log.csv"
        os.makedirs(os.path.dirname(log), exist_ok=True)
        new = not os.path.exists(log)
        with open(log, "a", encoding="utf-8") as fh:
            if new:
                fh.write("datetime,source,output,variant,note\n")
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{args.input},{final},"
                     f"4k-wall-bg,漆喰壁スタイル背景で{args.width}px幅に拡大\n")
        print(f"{final}  {out.size[0]}x{out.size[1]}  "
              f"{os.path.getsize(final)/1024/1024:.2f}MB  背景色={bg}  写真矩形={rect}")
        print(f"preview -> {prev_path}")
        return

    # 背景：元画像の背景色でクリーンに塗り直し（テクスチャ・キズ無し）
    canvas = Image.new("RGBA", (w1, h1), bg + (255,))
    # ごく淡い光沢だけ残す（のっぺり防止・色味は変えない）
    yy, xx = np.mgrid[0:h1, 0:w1].astype(np.float32)
    cx, cy = w1 * 0.72, h1 * 0.28
    r = np.sqrt(((xx - cx) / (w1 * 0.8)) ** 2 + ((yy - cy) / (h1 * 0.9)) ** 2)
    glow = (np.clip(1.0 - r, 0.0, 1.0) ** 2 * 7.0)[..., None]
    arr = np.asarray(canvas.convert("RGB"), dtype=np.float32) + glow
    canvas = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

    out = Image.alpha_composite(canvas, fg_big).convert("RGB")

    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.input))[0]
    final = os.path.join(args.outdir, f"{stem}{args.suffix}.jpg")
    n = 1
    base = final[:-4]
    while os.path.exists(final):
        n += 1
        final = f"{base}_{n:02d}.jpg"
    out.save(final, quality=args.quality, subsampling=1, optimize=True,
             dpi=(300, 300))

    # 確認用プレビュー（長辺1600px）
    prev = out.copy()
    prev.thumbnail((1600, 1600), Image.LANCZOS)
    prev_path = os.path.join("/tmp", f"preview-{stem}{args.suffix}.jpg")
    prev.save(prev_path, quality=90)

    log = "output/image_edit_log.csv"
    os.makedirs(os.path.dirname(log), exist_ok=True)
    new = not os.path.exists(log)
    with open(log, "a", encoding="utf-8") as fh:
        if new:
            fh.write("datetime,source,output,variant,note\n")
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{args.input},{final},"
                 f"4k-clean-bg,背景を元色{bg}でクリーン化し{args.width}px幅に拡大\n")

    print(f"{final}  {out.size[0]}x{out.size[1]}  "
          f"{os.path.getsize(final)/1024/1024:.2f}MB  背景色={bg}  写真矩形={rect}")
    print(f"preview -> {prev_path}")


if __name__ == "__main__":
    main()
