#!/usr/bin/env python3
"""バナー内のロゴ "Aki." を "AKI楽天市場店" に差し替える（決定論的処理 / Pillow + librsvg）。

処理の流れ
  1) ロゴ（ネイビー文字 + ゴールドドット）の領域を検出
  2) その領域の背景（単色 + わずかな縦グラデーション）を再構成して消去
  3) 新ロゴを SVG で描画し、位置合わせして合成
  4) JPEG 保存（既存ファイルは上書きしない）

使い方:
  python3 script/replace-logo-aki-rakuten.py --input img/top/IMG_1674-4k.jpg \
      --out img/top/IMG_1674-4k-shop.jpg
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

NAVY = (16, 35, 65)          # 既存ロゴのインク色（実測モード値）
GOLD = (192, 165, 120)       # 既存ゴールドドットの色
FONT_LATIN = "Bodoni 72"     # 元ロゴに近い Didone 系
FONT_LATIN_STYLE = "italic"   # book / bold は --latin-weight で切替
FONT_CJK = "Hiragino Mincho ProN W6"


# ---------------------------------------------------------------- detection
def detect_logo(im: Image.Image) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """ネイビー文字とゴールドドットの bbox を返す。右半分のみを対象にする。"""
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    h, w, _ = a.shape
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    x_min = int(w * 0.5)

    navy = (b > r + 20) & (r < 90) & (b < 120)
    navy[:, :x_min] = False

    def box(mask):
        ys, xs = np.nonzero(mask)
        if not len(xs):
            raise SystemExit("ロゴ領域を検出できませんでした")
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    tbox = box(navy)

    # ゴールドドットは文字の右側・文字帯の高さ付近だけを探す（背景との誤検出を防ぐ）
    gold = (r - b > 70) & (r < 205) & (g < 175) & (b < 130)
    win = np.zeros_like(gold)
    wx0, wx1 = tbox[2] + 2, min(w, tbox[2] + int(w * 0.10))
    wy0, wy1 = max(0, tbox[1]), min(h, tbox[3] + int(0.01 * h) + 20)
    win[wy0:wy1, wx0:wx1] = True
    gold &= win

    dbox = box(gold) if gold.any() else (tbox[2], tbox[3], tbox[2], tbox[3])

    # 細いセリフ・アンチエイリアスの取り残しを拾うため、背景からの残差で bbox を広げる
    bg = np.median(a[tbox[1]:tbox[3], max(0, w - 120):w - 5].reshape(-1, 3), axis=0)
    diff = np.abs(a.astype(np.float32) - bg[None, None, :]).max(axis=2)
    resid = diff > 9
    win2 = np.zeros_like(resid)
    ry0, ry1 = max(0, tbox[1] - 40), min(h, tbox[3] + 40)
    rx0, rx1 = max(0, tbox[0] - int(0.04 * w)), min(w, max(dbox[2], tbox[2]) + 40)
    win2[ry0:ry1, rx0:rx1] = True
    resid &= win2
    if resid.any():
        rbox = box(resid)
        tbox = (min(tbox[0], rbox[0]), min(tbox[1], rbox[1]), max(tbox[2], rbox[2]), max(tbox[3], rbox[3]))

    return tbox, dbox


# ------------------------------------------------------------- background
def _coons_field(a: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """帯の上下左右の実背景から Coons パッチで内部の明るさ場を作る。

    4 辺すべてで実測値と一致するため、境界に段差が出ない。
    """
    h, w, _ = a.shape
    n, bw = y1 - y0, x1 - x0
    k = 5

    top = a[max(0, y0 - k):y0, x0:x1].mean(axis=0)                    # bw, 3
    bot = a[y1:min(h, y1 + k), x0:x1].mean(axis=0)
    left = a[y0:y1, max(0, x0 - k):x0].mean(axis=1)                   # n, 3
    right = a[y0:y1, x1:min(w, x1 + k)].mean(axis=1)

    u = np.linspace(0.0, 1.0, bw, dtype=np.float32)[:, None]
    v = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    top_b = top[:-1] if top.shape[0] != bw else top
    bot_b = bot[:-1] if bot.shape[0] != bw else bot

    tb = top_b[None, :, :] * (1 - v)[:, :, None] + bot_b[None, :, :] * v[:, :, None]      # n,bw,3
    lr = left[:, None, :] * (1 - u)[None, :, :] + right[:, None, :] * u[None, :, :]       # n,bw,3
    c00, c10 = top_b[0], top_b[-1]
    c01, c11 = bot_b[0], bot_b[-1]
    bil = ((1 - u)[None, :, :] * (1 - v)[:, :, None] * c00
           + u[None, :, :] * (1 - v)[:, :, None] * c10
           + (1 - u)[None, :, :] * v[:, :, None] * c01
           + u[None, :, :] * v[:, :, None] * c11)
    return (tb + lr - bil).astype(np.float32)


def rebuild_background(im: Image.Image, box: tuple[int, int, int, int], margin: int = 26) -> Image.Image:
    """box を背景で塗り直した画像を返す。

    4 辺の実背景から Coons パッチで明るさ場を作り、粒状感は帯の外側の
    実ピクセル（高周波成分）から借りて合成する。
    """
    x0, y0, x1, y1 = box
    w, h = im.size
    x0 = max(0, x0 - margin)
    y0 = max(0, y0 - margin)
    x1 = min(w, x1 + margin)
    y1 = min(h, y1 + margin)
    n, bw = y1 - y0, x1 - x0
    if n <= 2 or bw <= 2:
        return im

    a = np.asarray(im.convert("RGB")).astype(np.float32)
    out = a.copy()

    field = _coons_field(a, x0, y0, x1, y1)

    # 粒状感（高周波成分）を実背景から借りる
    if x1 + 40 < w:
        cs = slice(min(w, x1 + 6), w - 3)
    else:
        cs = slice(3, max(4, x0 - 6))
    patch = a[y0:y1, cs]
    if patch.shape[1] < 8:
        patch = a[y0:y1, max(0, x0 - 120):x0]
    tex = patch - patch.mean(axis=1, keepdims=True)   # 行ごとの平均を引いて高周波だけ残す
    reps = int(np.ceil(bw / tex.shape[1]))
    tex = np.concatenate([tex] * reps, axis=1)[:, :bw, :]

    band = np.clip(field + tex, 0, 255)

    # 念のため境界を 8px ブレンド
    fb = 8
    orig = a[y0:y1, x0:x1]
    wgt = np.ones((n, bw, 1), dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, fb, dtype=np.float32)[:, None, None]
    wgt[:fb] = ramp
    wgt[n - fb:] = ramp[::-1]
    rx = np.linspace(0.0, 1.0, fb, dtype=np.float32)[None, :, None]
    wgt[:, :fb] = np.minimum(wgt[:, :fb], rx)
    wgt[:, bw - fb:] = np.minimum(wgt[:, bw - fb:], rx[:, ::-1])

    out[y0:y1, x0:x1] = np.clip(band * wgt + orig * (1.0 - wgt), 0, 255)
    return Image.fromarray(np.rint(np.clip(out, 0, 255)).astype(np.uint8))


# ------------------------------------------------------------------- text
def build_svg(width: int, height: int, baseline: float, size_latin: float, size_cjk: float,
              dot: bool, tracking_cjk: float, text_latin: str, text_cjk: str,
              latin_weight: str = "normal") -> str:
    weight = ' font-weight="bold"' if latin_weight == "bold" else ""
    dot_r = size_cjk * 0.10
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<g fill="rgb({NAVY[0]},{NAVY[1]},{NAVY[2]})">',
    ]
    if text_latin:
        svg.append(
            f'<text x="0" y="{baseline:.2f}" font-family="{FONT_LATIN}"{weight} '
            f'font-style="{FONT_LATIN_STYLE}" font-size="{size_latin:.2f}">{text_latin}</text>'
        )
    if text_cjk:
        svg.append(
            f'<text x="0" y="{baseline:.2f}" font-family="{FONT_CJK}" '
            f'font-size="{size_cjk:.2f}" letter-spacing="{tracking_cjk:.2f}">{text_cjk}</text>'
        )
    svg.append("</g>")
    if dot:
        svg.append(
            f'<circle cx="0" cy="{baseline - dot_r:.2f}" r="{dot_r:.2f}" fill="rgb({GOLD[0]},{GOLD[1]},{GOLD[2]})"/>'
        )
    svg.append("</svg>")
    return "\n".join(svg)


def render_svg(svg: str) -> Image.Image:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.svg")
        dst = os.path.join(d, "t.png")
        with open(src, "w", encoding="utf-8") as f:
            f.write(svg)
        subprocess.run(["rsvg-convert", "-o", dst, src], check=True)
        return Image.open(dst).convert("RGBA")


def layout_text(text_latin: str, text_cjk: str, size_latin: float, size_cjk: float,
                tracking_cjk: float, dot: bool, latin_weight: str = "normal") -> tuple[Image.Image, int, int]:
    """テキストを描画し、横並びに連結した 1 枚の RGBA を返す。"""
    baseline = size_latin * 0.85
    canvas_w, canvas_h = int(size_latin * 7), int(size_latin * 2)
    latin = render_svg(build_svg(canvas_w, canvas_h, baseline, size_latin, 0, False, 0, text_latin, "", latin_weight))
    cjk = render_svg(build_svg(canvas_w, canvas_h, baseline, 0, size_cjk, False, tracking_cjk, "", text_cjk))

    def ink_box(img):
        al = np.asarray(img)[:, :, 3]
        ys, xs = np.nonzero(al > 8)
        return xs.min(), ys.min(), xs.max(), ys.max()

    lx0, ly0, lx1, ly1 = ink_box(latin)
    cx0, cy0, cx1, cy1 = ink_box(cjk)

    gap = size_cjk * 0.30
    total_w = int((lx1 - lx0 + 1) + gap + (cx1 - cx0 + 1)) + 2
    out = Image.new("RGBA", (total_w, canvas_h), (0, 0, 0, 0))
    out.alpha_composite(latin, (-int(lx0), 0))
    out.alpha_composite(cjk, (int(lx1 - lx0 + 1 + gap) - int(cx0), 0))

    if dot:
        a = np.asarray(out)[:, :, 3]
        ys, xs = np.nonzero(a > 8)
        r = max(2, int(size_cjk * 0.095))
        d = Image.new("RGBA", (2 * r + 3, 2 * r + 3), (0, 0, 0, 0))
        from PIL import ImageDraw
        ImageDraw.Draw(d).ellipse((1, 1, 2 * r + 1, 2 * r + 1), fill=(*GOLD, 255))
        dot_x = int(xs.max() + 1 + max(0.0, size_cjk * 0.12 - tracking_cjk))
        # 元ロゴ同様、ベースラインよりやや下に置く
        dot_y = int(baseline + r * 0.55 - r)
        new = Image.new("RGBA", (dot_x + 2 * r + 5, canvas_h), (0, 0, 0, 0))
        new.alpha_composite(out, (0, 0))
        new.alpha_composite(d, (dot_x, dot_y))
        out = new

    return out, total_w, canvas_h



def layout_stacked(text_latin: str, text_cjk: str, size_latin: float, size_cjk: float,
                   tracking_cjk: float, dot: bool, latin_weight: str = "normal",
                   gap_ratio: float = 0.20) -> Image.Image:
    """2 行組み（上: 欧文 / 下: 日本語）で右揃えのロックアップを作る。"""
    baseline = size_latin * 0.85
    canvas_w, canvas_h = int(size_latin * 7), int(size_latin * 2)
    latin = trim(render_svg(build_svg(canvas_w, canvas_h, baseline, size_latin, 0, False, 0,
                                      text_latin, "", latin_weight)))
    cjk = trim(render_svg(build_svg(canvas_w, canvas_h, baseline, 0, size_cjk, False,
                                    tracking_cjk, "", text_cjk)))

    dot_r = max(2, int(size_cjk * 0.085))
    dot_pad = int(size_cjk * 0.10)
    dot_w = (dot_pad + 2 * dot_r) if dot else 0
    gap = int(size_latin * gap_ratio)
    align_w = max(latin.width, cjk.width)          # 右揃えの基準（ドットは外側にぶら下げる）
    total_w = align_w + dot_w
    total_h = latin.height + gap + cjk.height

    out = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    out.alpha_composite(latin, (align_w - latin.width, 0))
    out.alpha_composite(cjk, (align_w - cjk.width, latin.height + gap))
    if dot:
        from PIL import ImageDraw
        d = Image.new("RGBA", (2 * dot_r + 3, 2 * dot_r + 3), (0, 0, 0, 0))
        ImageDraw.Draw(d).ellipse((1, 1, 2 * dot_r + 1, 2 * dot_r + 1), fill=(*GOLD, 255))
        out.alpha_composite(d, (total_w - 2 * dot_r - 2, total_h - 2 * dot_r - 2 - int(dot_r * 0.3)))
    return out


def trim(img: Image.Image) -> Image.Image:
    al = np.asarray(img)[:, :, 3]
    ys, xs = np.nonzero(al > 8)
    return img.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


# ------------------------------------------------------------------- main
def _resize_output(im: Image.Image, width: int | None, height: int | None, fit: str) -> Image.Image:
    """最終画像のリサイズ（fit=keep: アスペクト維持 / exact: 指定サイズに合わせる / crop: 中央クロップ）"""
    if not width and not height:
        return im
    w, h = im.size
    if fit == "exact":
        tw, th = width or w, height or h
        return im.resize((tw, th), Image.LANCZOS)
    tw = width or int(round(w * (height / h)))
    th = int(round(h * (tw / w)))
    if fit == "crop" and height:
        # 幅を基準に拡大し、上下を中央クロップ
        scale = tw / w
        im2 = im.resize((tw, int(round(h * scale))), Image.LANCZOS)
        top = max(0, (im2.height - height) // 2)
        return im2.crop((0, top, tw, top + height))
    return im.resize((tw, th), Image.LANCZOS)


def process(src: str, dst: str, dot: bool, quality: int, scale_cjk: float, latin_weight: str = "normal",
            layout: str = "inline", out_w: int | None = None, out_h: int | None = None,
            fit: str = "keep") -> dict:
    im = Image.open(src).convert("RGB")
    text_box, dot_box = detect_logo(im)
    union = (min(text_box[0], dot_box[0]), min(text_box[1], dot_box[1]),
             max(text_box[2], dot_box[2]), max(text_box[3], dot_box[3]))
    orig_w = union[2] - union[0] + 1
    orig_h = union[3] - union[1] + 1

    clean = rebuild_background(im, union)

    left_limit = int(im.width * 0.475)          # 写真コラージュ右端の目安
    max_w = min(int(im.width * 0.46), union[2] - left_limit)

    if layout == "stacked":
        # 元ロゴと同じ大きさ（高さ）に合わせた 2 行組み
        size_latin = orig_h * 0.80
        size_cjk = size_latin * scale_cjk
        lockup = layout_stacked("AKI", "楽天市場店", size_latin, size_cjk, size_cjk * 0.10, dot, latin_weight)
        if lockup.width > max_w:
            f = max_w / lockup.width
            lockup = lockup.resize((max(1, int(lockup.width * f)), max(1, int(lockup.height * f))), Image.LANCZOS)
    else:
        size_latin = orig_h * 0.80
        size_cjk = size_latin * scale_cjk
        lockup, _, _ = layout_text("AKI", "楽天市場店", size_latin, size_cjk, size_cjk * 0.04, dot, latin_weight)
        lockup = trim(lockup)
        # 幅が広すぎる場合は縮小（左の写真コラージュとの間隔を確保）
        if lockup.width > max_w:
            f = max_w / lockup.width
            lockup = lockup.resize((max(1, int(lockup.width * f)), max(1, int(lockup.height * f))), Image.LANCZOS)

    out = clean.convert("RGBA")
    px = int(union[2] - lockup.width + 1)
    py = int((union[1] + union[3]) / 2 - lockup.height / 2)
    out.alpha_composite(lockup, (px, py))

    rgb = _resize_output(out.convert("RGB"), out_w, out_h, fit)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if os.path.exists(dst):
        raise SystemExit(f"出力先が既に存在します（上書き禁止）: {dst}")
    rgb.save(dst, quality=quality, subsampling=0, optimize=True)

    return dict(src=src, dst=dst, orig_box=union, orig_wh=(orig_w, orig_h),
                logo_wh=lockup.size, pos=(px, py), text_box=text_box, dot_box=dot_box)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", action="append", required=True, help="入力画像（複数可）")
    ap.add_argument("--suffix", default="-shop", help="出力ファイル名の接尾辞")
    ap.add_argument("--outdir", default=None, help="出力先ディレクトリ（既定: 入力と同じ）")
    ap.add_argument("--no-dot", action="store_true", help="末尾のゴールドドットを付けない")
    ap.add_argument("--cjk-ratio", type=float, default=0.72, help="CJK サイズ / 欧文サイズ")
    ap.add_argument("--layout", choices=["inline", "stacked"], default="inline",
                    help="inline=1行 / stacked=2行（元ロゴと同じ大きさ）")
    ap.add_argument("--latin-weight", choices=["normal", "bold"], default="bold",
                    help="AKI のウェイト（元ロゴは bold 寄り）")
    ap.add_argument("--width", type=int, default=None, help="出力幅(px)")
    ap.add_argument("--height", type=int, default=None, help="出力高さ(px)")
    ap.add_argument("--fit", choices=["keep", "exact", "crop"], default="keep",
                    help="keep=アスペクト維持 / exact=指定サイズ / crop=中央クロップ")
    ap.add_argument("--quality", type=int, default=92)
    args = ap.parse_args()

    for src in args.input:
        base, ext = os.path.splitext(os.path.basename(src))
        outdir = args.outdir or os.path.dirname(src) or "."
        dst = os.path.join(outdir, f"{base}{args.suffix}{ext}")
        info = process(src, dst, not args.no_dot, args.quality, args.cjk_ratio, args.latin_weight,
                       args.layout, args.width, args.height, args.fit)
        print(f"[ok] {src} -> {dst}")
        print(f"     size={Image.open(dst).size}")
        print(f"     orig_box={info['orig_box']} {info['orig_wh']}px  "
              f"logo={info['logo_wh']}  pos={info['pos']}")


if __name__ == "__main__":
    sys.exit(main())
