#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
トップバナー（ベージュ紙背景 + 写真コラージュ + ロゴ文字）の背景だけを
上品なくすみカラー背景に差し替える一時スクリプト。

- 縁から連結した「紙背景」領域のみを検出して差し替え（写真・文字はそのまま）
- AI生成は使わず Pillow/numpy の決定論的処理のみ
- 既存ファイルは上書きしない（連番付与）

使用例:
  python3 script/banner-bg-retouch.py --input img/top/IMG_1674.JPG --outdir img/top
"""
import argparse
import os
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# くすみカラーパレット（AGENTS.md / SKILL.md と同一）
PALETTE = {
    "oatmeal": (242, 237, 228),
    "cream": (247, 243, 236),
    "pink": (245, 224, 224),
    "beige": (239, 230, 216),
    "gray": (230, 228, 225),
    "lavender": (233, 228, 239),
    "sage": (220, 228, 216),
    "bluegray": (224, 228, 232),
    "linegray": (138, 127, 112),
    "fillbeige": (183, 169, 154),
    "textbrown": (90, 80, 72),
    "accentred": (191, 107, 107),
}


# ---------- 背景マスク ----------
def _border_connected(cand, limit=5000):
    """縁に接する cand 領域（4近傍で反復膨張）"""
    m = np.zeros_like(cand)
    m[0, :] = cand[0, :]
    m[-1, :] = cand[-1, :]
    m[:, 0] = cand[:, 0]
    m[:, -1] = cand[:, -1]
    for _ in range(limit):
        g = m.copy()
        g[1:, :] |= m[:-1, :]
        g[:-1, :] |= m[1:, :]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        g &= cand
        if np.array_equal(g, m):
            break
        m = g
    return m


def _label(mask):
    """4近傍の連結成分ラベル（BFS）と面積・バウンディングボックス"""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    info = []
    for y in range(h):
        row = mask[y]
        for x in range(w):
            if row[x] and lab[y, x] == 0:
                idx = len(info) + 1
                stack = [(y, x)]
                lab[y, x] = idx
                area = 0
                x0 = x1 = x
                y0 = y1 = y
                while stack:
                    cy, cx = stack.pop()
                    area += 1
                    if cx < x0: x0 = cx
                    if cx > x1: x1 = cx
                    if cy < y0: y0 = cy
                    if cy > y1: y1 = cy
                    for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and lab[ny, nx] == 0:
                            lab[ny, nx] = idx
                            stack.append((ny, nx))
                info.append((idx, area, x0, y0, x1, y1))
    return lab, info


def _is_textish(color):
    """文字・金のアクセントか（= 消してはいけない前景）"""
    r, g, b = [float(v) for v in color]
    bright = 0.299 * r + 0.587 * g + 0.114 * b
    navy = b > r + 10 and bright < 140
    dark = bright < 130
    gold = (r - b) > 55 and r > 150
    return navy or dark or gold


def background_mask(rgb, tolerance=62, feather=1, tol_soft=90, grow=0, min_area=350):
    """差し替える背景の度合い(0..1)を返す。

    - 背景色に近いほど 1（=差し替え）
    - 写真コラージュ矩形と文字・アクセントは 0（=元画像を保持）
    - 文字の内側（A のカウンター等）の背景色は 1（=差し替え）
    """
    arr = rgb.astype(np.int16)
    border = np.concatenate([
        arr[:4, :, :].reshape(-1, 3),
        arr[-4:, :, :].reshape(-1, 3),
        arr[:, :4, :].reshape(-1, 3),
        arr[:, -4:, :].reshape(-1, 3),
    ])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=2))

    # 背景色への近さでソフトに 0..1
    alpha = np.clip((tol_soft - dist) / float(max(tol_soft - tolerance, 1)), 0.0, 1.0)
    alpha = alpha.astype(np.float32)

    # 前景（写真・文字）を検出してマスクを保護
    cand = dist < tolerance
    bgmask = _border_connected(cand)
    fg = ~bgmask
    lab, info = _label(fg)

    photo = (0, 0, rgb.shape[1] - 1, rgb.shape[0] - 1, 0)
    protect = np.zeros_like(fg)
    for idx, area, x0, y0, x1, y1 in info:
        if area > photo[4]:
            photo = (x0, y0, x1, y1, area)
        comp = lab == idx
        color = arr[comp].mean(axis=0)
        if area < 3000 and _is_textish(color):
            # 文字・金のアクセント（膨張させて輪郭の境界色も守る）
            grown = comp.copy()
            for _ in range(grow):
                g2 = grown.copy()
                g2[1:, :] |= grown[:-1, :]
                g2[:-1, :] |= grown[1:, :]
                g2[:, 1:] |= grown[:, :-1]
                g2[:, :-1] |= grown[:, 1:]
                grown = g2
            protect |= grown

    alpha[protect] = 0.0

    px0, py0, px1, py1 = photo[:4]
    if photo[4] > 0.02 * alpha.size:
        alpha[max(py0 - 1, 0):py1 + 2, max(px0 - 1, 0):px1 + 2] = 0.0

    a = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    if feather > 0:
        a = a.filter(ImageFilter.GaussianBlur(feather))
    return np.asarray(a, dtype=np.float32) / 255.0, tuple(int(v) for v in bg), photo[:4]


# ---------- 漆喰（プラスター）壁スタイル ----------
PLASTER_BASE = (215, 192, 160)      # 参考画像の壁の平均色
WALL_LIGHT = 1.0                    # 光ムラの強さ（CLI で変更）
WALL_TEXTURE = 1.0                  # 漆喰の質感の強さ（CLI で変更）


def _value_noise(h, w, cell_y, cell_x, rng):
    gh = max(int(round(h / float(cell_y))), 2)
    gw = max(int(round(w / float(cell_x))), 2)
    grid = rng.normal(0.0, 1.0, (gh, gw)).astype(np.float32)
    img = Image.fromarray(grid, "F").resize((w, h), Image.BICUBIC)
    arr = np.asarray(img, dtype=np.float32)
    std = arr.std()
    return arr / std if std > 1e-6 else arr


def plaster_background(size, seed=20251111, light=True):
    """漆喰壁のような、光ムラのある温かいベージュ背景"""
    w, h = size
    rng = np.random.default_rng(seed)

    field = (12.0 * _value_noise(h, w, h / 3.0, w / 3.0, rng)
             + 5.0 * _value_noise(h, w, h / 10.0, w / 10.0, rng)
             + 2.0 * _value_noise(h, w, h / 28.0, w / 28.0, rng))
    # 鏝（こて）跡のような横方向の流れ
    field += 1.6 * _value_noise(h, w, h / 45.0, w / 4.0, rng)

    # 漆喰の凹凸（高さ場の勾配で陰影をつける）
    height = 0.62 * _value_noise(h, w, 4.5, 4.5, rng) + 0.38 * _value_noise(h, w, 2.0, 2.0, rng)
    gy, gx = np.gradient(height)
    bump = (-gx * 0.8 - gy * 0.6)
    bump_std = bump.std()
    if bump_std > 1e-6:
        bump = bump / bump_std * 3.6

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xx / w, yy / h

    if light:
        # 明るい光だまり（左下寄り）＋右側を落とす
        bright = np.exp(-(((nx - 0.34) / 0.55) ** 2 + ((ny - 0.92) / 0.75) ** 2))
        dark = np.clip((nx - 0.45) / 0.55, 0.0, 1.0) ** 1.3
        shade = 28.0 * bright - 20.0 * dark + 5.0 * (1.0 - ny)
    else:
        shade = np.zeros((h, w), dtype=np.float32)

    vig = np.clip(np.sqrt(((nx - 0.5) * 1.7) ** 2 + ((ny - 0.5) * 1.3) ** 2) - 0.75, 0, 1)
    shade -= (vig ** 1.5) * 10.0

    lum = field * WALL_TEXTURE + shade * WALL_LIGHT + bump * WALL_TEXTURE
    base = np.array(PLASTER_BASE, dtype=np.float32)
    tint = np.array([1.0, 0.985, 0.95], dtype=np.float32)   # 明部をやや温かく
    rgb = base + lum[..., None] * tint
    rgb += rng.normal(0.0, 1.4, (h, w, 1))                  # 粒状感
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb, "RGB").convert("RGBA")


def add_shadow(img, rect, alpha=66):
    """写真コラージュの下に柔らかい影を落とす"""
    w, h = img.size
    x0, y0, x1, y1 = rect
    off = max(3, h // 60)
    blur = max(8, h // 22)
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.rectangle([x0, y0 + off, x1, y1 + off], fill=PALETTE["textbrown"] + (alpha,))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(img, sh)


def make_background(size, variant="a", seed=20251111, rect=None):
    if variant == "d":
        img = plaster_background(size, seed=seed)
        if rect is not None:
            img = add_shadow(img, rect, alpha=58)
        return img

    w, h = size
    rng = np.random.default_rng(seed)

    top = np.array(PALETTE["cream"], dtype=np.float32)
    bottom = np.array(PALETTE["beige"], dtype=np.float32)
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    bg = top * (1 - t) + bottom * t          # 縦グラデーション
    bg = np.repeat(bg, w, axis=1)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    if variant == "c":
        # リネン調の織りテクスチャ（ごく淡い）
        blot = rng.normal(0.0, 1.0, (max(h // 3, 2), max(w // 3, 2)))
        blot = np.asarray(Image.fromarray(blot.astype(np.float32), "F")
                          .resize((w, h), Image.BICUBIC), dtype=np.float32)
        weave = blot * 2.6
    else:
        weave = np.zeros((h, w), dtype=np.float32)

    # 対角の淡い光（上品な光沢）
    cx, cy = w * 0.72, h * 0.28
    r = np.sqrt(((xx - cx) / (w * 0.75)) ** 2 + ((yy - cy) / (h * 0.85)) ** 2)
    glow = np.clip(1.0 - r, 0.0, 1.0) ** 2
    bg += (glow[..., None] * 16.0)

    # 周辺をほんのり落とす（vignette）
    rx = (xx - w / 2) / (w / 2)
    ry = (yy - h / 2) / (h / 2)
    vig = np.clip(np.sqrt(rx ** 2 * 0.85 + ry ** 2) - 0.55, 0.0, 1.0)
    bg -= (vig[..., None] ** 1.4) * 13.0

    bg += weave[..., None]
    bg += rng.normal(0.0, 2.1, (h, w, 1))     # 紙の微細グレイン
    bg = np.clip(bg, 0, 255).astype(np.uint8)

    img = Image.fromarray(bg, "RGB").convert("RGBA")

    # 写真コラージュの柔らかいドロップシャドウ
    if rect is not None and variant in ("b", "c"):
        img = add_shadow(img, rect, alpha=66)

    if variant in ("b", "c"):
        # 内側の細いヘアライン（淡いゴールド）

        d = ImageDraw.Draw(img)
        inset = max(10, h // 30)
        d.rectangle([inset, inset, w - 1 - inset, h - 1 - inset],
                    outline=(190, 168, 128, 60), width=1)
    return img


# ---------- 合成 ----------
def compose(src_path, out_path, variant="a", tolerance=34, feather=2):
    src = Image.open(src_path).convert("RGB")
    rgb = np.asarray(src, dtype=np.uint8)
    alpha, bg_med, rect = background_mask(rgb, tolerance=tolerance, feather=feather)

    new_bg = make_background(src.size, variant=variant, rect=rect)
    fg = Image.fromarray(rgb, "RGB").convert("RGBA")

    a = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    out = Image.composite(new_bg, fg, a)      # a=255(背景) -> 新背景

    base, ext = os.path.splitext(out_path)
    final = out_path
    n = 1
    while os.path.exists(final):
        n += 1
        final = f"{base}_{n:02d}{ext}"
    out.convert("RGB").save(final, quality=95)
    covered = float(alpha.mean()) * 100
    return final, bg_med, covered, rect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", default="img/top")
    ap.add_argument("--variant", default="a,b,c",
                    help="a: グラデ+グレイン / b: +写真影+ヘアライン / c: リネン+写真影 / d: 漆喰壁")
    ap.add_argument("--tolerance", type=int, default=45)
    ap.add_argument("--suffix", default="bg")
    ap.add_argument("--wall-light", type=float, default=1.0, help="漆喰の光ムラ倍率")
    ap.add_argument("--wall-texture", type=float, default=1.0, help="漆喰の質感倍率")
    args = ap.parse_args()

    global WALL_LIGHT, WALL_TEXTURE
    WALL_LIGHT = args.wall_light
    WALL_TEXTURE = args.wall_texture
    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.input))[0]
    results = []
    for v in [x.strip() for x in args.variant.split(",") if x.strip()]:
        out = os.path.join(args.outdir, f"{stem}-{args.suffix}{v}.png")
        final, bg_med, covered, rect = compose(args.input, out, variant=v,
                                              tolerance=args.tolerance)
        results.append((final, bg_med, covered))
        print(f"[{v}] {final}  背景色={bg_med}  差し替え率={covered:.1f}%  写真矩形={rect}")

    log = "output/image_edit_log.csv"
    os.makedirs(os.path.dirname(log), exist_ok=True)
    new = not os.path.exists(log)
    with open(log, "a", encoding="utf-8") as fh:
        if new:
            fh.write("datetime,source,output,variant,note\n")
        for final, _bg, _c in results:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{args.input},{final},"
                     f"bg-replace,背景をくすみカラーグラデ+グレインに差し替え\n")
    print(f"log -> {log}")


if __name__ == "__main__":
    main()
