#!/usr/bin/env python3
"""背景を「キザキザした石壁」風のおしゃれなテクスチャに差し替える。

元画像（Aki. ロゴ入り）から:
  1) 写真コラージュの矩形を検出
  2) 角張った石積み壁のテクスチャを生成（くすみカラーのベージュ系）
  3) 写真を元の位置に戻し、ロゴを AKI楽天市場店 として描き直す
  4) 1206px 幅などにリサイズして保存（既存ファイルは上書きしない）

使い方:
  python3 script/wall-jagged-aki.py --input img/top/IMG_1674-4k.jpg \
      --out img/top/IMG_1674-4k-shop-wall.jpg --width 1206
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))

NAVY = (16, 35, 65)
GOLD = (176, 141, 85)
BASE = np.array([211, 188, 154], dtype=np.float32)     # 既存背景の色味に合わせる


def _load_logo_mod():
    """ロゴ差し替えスクリプトの関数を再利用する。"""
    path = os.path.join(HERE, "replace-logo-aki-rakuten.py")
    spec = importlib.util.spec_from_file_location("logo_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ noise
def value_noise(h: int, w: int, cell_y: float, cell_x: float, rng) -> np.ndarray:
    gh = max(int(round(h / float(cell_y))), 2)
    gw = max(int(round(w / float(cell_x))), 2)
    grid = rng.random((gh, gw), dtype=np.float32)
    img = Image.fromarray(grid, "F").resize((w, h), Image.BICUBIC)
    arr = np.asarray(img, dtype=np.float32)
    std = float(arr.std())
    return (arr - arr.mean()) / std if std > 1e-6 else arr - arr.mean()


def fbm(h: int, w: int, cell: float, octaves: int, rng) -> np.ndarray:
    out = np.zeros((h, w), dtype=np.float32)
    amp = 1.0
    c = cell
    for _ in range(octaves):
        out += amp * value_noise(h, w, c, c, rng)
        amp *= 0.5
        c *= 0.5
    return out


# ------------------------------------------------------------- photo rect
def detect_photo_rect(im: Image.Image) -> tuple[int, int, int, int]:
    """背景と異なる領域（写真コラージュ）の矩形を検出する。"""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    h, w, _ = a.shape
    bg = np.median(np.concatenate([
        a[:40, :40].reshape(-1, 3), a[:40, -40:].reshape(-1, 3),
        a[-40:, :40].reshape(-1, 3), a[-40:, -40:].reshape(-1, 3)]), axis=0)
    diff = np.abs(a - bg).max(axis=2)
    mask = diff > 14
    mask[:, int(w * 0.5):] = False          # 左半分（写真側）だけ見る
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise SystemExit("写真領域を検出できませんでした")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


# ------------------------------------------------------------- wall tex
def jagged_wall(size: tuple[int, int], seed: int = 20261116,
                block_h: float = 118.0, block_w: float = 250.0,
                warp: float = 8.0, joint: float = 17.0) -> Image.Image:
    """角張った石積み壁テクスチャ。戻り値は RGB。"""
    w, h = size
    rng = np.random.default_rng(seed)

    # ドメインワープ（境界をギザギザに歪ませる）
    wy = fbm(h, w, 60.0, 3, rng)
    wx = fbm(h, w, 60.0, 3, rng)
    # ノイズを量子化して「カクカク」した稜線にする
    q = 3.0
    wy = np.round(wy * q) / q
    wx = np.round(wx * q) / q

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    Y = yy + wy * warp
    X = xx + wx * warp

    # 段（コース）ごとに高さを少し変える
    n_rows = int(np.ceil(h / block_h)) + 2
    row_h = block_h * rng.uniform(0.82, 1.22, n_rows).astype(np.float32)
    row_top = np.concatenate([[0.0], np.cumsum(row_h)])
    row_idx = np.clip(np.searchsorted(row_top, Y, side="right") - 1, 0, n_rows - 1)

    # 各段のブロック幅（段ごとにずらす）
    col_w = block_w * rng.uniform(0.62, 1.55, (n_rows, 40)).astype(np.float32)
    col_idx = np.zeros((h, w), dtype=np.int32)
    for r in range(n_rows):
        sel = row_idx == r
        if not sel.any():
            continue
        cum = np.concatenate([[0.0], np.cumsum(col_w[r])])
        col_idx[sel] = np.clip(np.searchsorted(cum, X[sel], side="right") - 1, 0, 39)

    # ブロックごとの色ムラ
    stone = rng.normal(0.0, 4.2, (n_rows, 40)).astype(np.float32)
    tone = stone[row_idx, col_idx]

    # 目地（ブロック境界）からの距離 → 面取り（ベベル）と目地の陰
    cum = np.concatenate([np.zeros((n_rows, 1), np.float32), np.cumsum(col_w, axis=1)], axis=1)
    x_start = cum[row_idx, col_idx]
    x_end = cum[row_idx, col_idx + 1]
    bw = np.maximum(x_end - x_start, 1.0)
    y_in = (Y - row_top[row_idx]) / np.maximum(row_h[row_idx], 1.0)
    x_in = (X - x_start) / bw

    # 境界までの距離（px 目安）
    dy = np.minimum(y_in, 1.0 - y_in) * np.maximum(row_h[row_idx], 1.0)
    dx = np.minimum(x_in, 1.0 - x_in) * bw
    dist = np.minimum(dy, dx)

    bevel = np.clip(dist / 6.0, 0.0, 1.0) ** 0.65
    # 上辺・左辺を明るく、下辺・右辺を暗く（斜め上からの光）
    lit = (np.where(y_in < 0.5, 1.0, -1.0) * 0.58 + np.where(x_in < 0.5, 1.0, -1.0) * 0.42)
    relief = (bevel - 1.0) * 7.0 + lit * (1.0 - bevel) * 13.0
    groove = -(1.0 - bevel) ** 2 * joint
    rim = np.exp(-((dist - 1.6) / 2.4) ** 2) * np.clip(lit, 0.0, 1.0) * 5.0   # 角のハイライト

    # 石の表面の細かな凹凸
    rough = fbm(h, w, 7.0, 3, rng) * 3.2
    pores = value_noise(h, w, 2.2, 2.2, rng) * 1.2

    # 全体の光ムラ（左上から光、右下を落とす）
    nx, ny = xx / w, yy / h
    glow = 10.0 * np.exp(-(((nx - 0.45) / 0.7) ** 2 + ((ny - 0.25) / 0.6) ** 2))
    shade = glow - 9.0 * np.clip((nx - 0.35) / 0.65, 0, 1) ** 1.2 - 5.0 * np.clip(ny - 0.55, 0, 1)
    vig = np.clip(np.sqrt(((nx - 0.5) * 1.6) ** 2 + ((ny - 0.5) * 1.2) ** 2) - 0.8, 0, 1)
    shade -= (vig ** 1.4) * 9.0

    lum = tone + relief + groove + rim + rough + pores + shade
    tint = np.array([1.0, 0.985, 0.955], dtype=np.float32)
    rgb = BASE[None, None, :] + lum[..., None] * tint[None, None, :]
    rgb += rng.normal(0.0, 1.3, (h, w, 1))
    # 彩度を少し落として「くすみ」に寄せる
    gray = rgb.mean(axis=2, keepdims=True)
    rgb = gray + (rgb - gray) * 0.92
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")



def voronoi_wall(size: tuple[int, int], seed: int = 20261116,
                 cell_x: float = 330.0, cell_y: float = 190.0,
                 jitter: float = 0.42, warp: float = 26.0,
                 edge_w: float = 7.0, mortar: float = 26.0,
                 warmth: float = 1.0, base: np.ndarray | None = None) -> Image.Image:
    """多角形の石積み壁（ジッター格子ボロノイ）。角張った継ぎ目＝キザキザ感。"""
    w, h = size
    rng = np.random.default_rng(seed)

    # 座標をノイズで歪ませ、境界をギザギザにする
    wx = fbm(h, w, 150.0, 3, rng)
    wy = fbm(h, w, 150.0, 3, rng)
    X = np.arange(w, dtype=np.float32)[None, :] + (np.round(wx * 2) / 2) * warp
    Y = np.arange(h, dtype=np.float32)[:, None] + (np.round(wy * 2) / 2) * warp
    X, Y = np.broadcast_arrays(X, Y)
    X = np.ascontiguousarray(X, dtype=np.float32)
    Y = np.ascontiguousarray(Y, dtype=np.float32)

    # ジッター格子のサイト
    gx = int(np.ceil(w / cell_x)) + 3
    gy = int(np.ceil(h / cell_y)) + 3
    jx = rng.uniform(-jitter, jitter, (gy, gx)).astype(np.float32) * cell_x
    jy = rng.uniform(-jitter, jitter, (gy, gx)).astype(np.float32) * cell_y
    sx_pos = np.arange(gx, dtype=np.float32)[None, :] * cell_x + jx
    sy_pos = np.arange(gy, dtype=np.float32)[:, None] * cell_y + jy

    cx = np.clip(np.floor(X / cell_x).astype(np.int32), 1, gx - 2)
    cy = np.clip(np.floor(Y / cell_y).astype(np.int32), 1, gy - 2)

    d1 = np.full((h, w), 1e9, np.float32)
    d2 = np.full((h, w), 1e9, np.float32)
    idx = np.zeros((h, w), np.int32)

    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            ry = cy + di
            rx = cx + dj
            dx = X - sx_pos[ry, rx]
            dy = Y - sy_pos[ry, rx]
            d = np.sqrt(dx * dx + dy * dy).astype(np.float32)
            closer = d < d1
            d2 = np.where(closer, d1, np.minimum(d2, d))
            idx = np.where(closer, ry * gx + rx, idx)
            d1 = np.where(closer, d, d1)

    edge = (d2 - d1) * 0.5                       # 継ぎ目までの距離
    # 継ぎ目に細かいノイズを足して「欠けた・キザキザ」した縁にする
    edge = edge + fbm(h, w, 22.0, 3, rng) * 2.2 + value_noise(h, w, 5.0, 5.0, rng) * 0.9
    t = np.clip(edge / edge_w, 0.0, 1.0)

    stone = rng.normal(0.0, 4.2, (gy * gx,)).astype(np.float32)
    stone2 = rng.normal(0.0, 2.0, (gy * gx,)).astype(np.float32)
    tone = stone[np.clip(idx, 0, gy * gx - 1)]

    ey, ex = np.gradient(edge.astype(np.float32))
    nrm = np.sqrt(ex ** 2 + ey ** 2) + 1e-3
    light = (-ex / nrm) * 0.42 + (-ey / nrm) * 0.58
    shade = np.clip(light, -1, 1) * (1.0 - t) ** 1.6 * 15.0

    bevel = (t ** 0.55 - 1.0) * 7.0
    groove = -(1.0 - t) ** 2 * mortar
    rim = np.exp(-((edge - 2.5) / 3.2) ** 2) * np.clip(-ey / nrm, 0, 1) * 7.5

    rough = fbm(h, w, 9.0, 3, rng) * 2.4 + stone2[np.clip(idx, 0, gy * gx - 1)]
    pores = value_noise(h, w, 2.4, 2.4, rng) * 1.1

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xx / w, yy / h
    glow = 8.0 * np.exp(-(((nx - 0.4) / 0.8) ** 2 + ((ny - 0.3) / 0.7) ** 2))
    vig = np.clip(np.sqrt(((nx - 0.5) * 1.5) ** 2 + ((ny - 0.5) * 1.2) ** 2) - 0.85, 0, 1)
    lum = tone + bevel + groove + rim + shade + rough + pores + glow - (vig ** 1.4) * 8.0

    # 暖色グレーディング（warmth: 0=寒色寄り / 1=標準 / 2=かなり暖かい）
    base_col = BASE if base is None else np.asarray(base, dtype=np.float32)
    wm = float(np.clip(warmth, 0.0, 4.0))
    rgb = base_col[None, None, :] + lum[..., None]
    rgb += rng.normal(0.0, 1.2, (h, w, 1))
    grade = np.array([1.0 + 0.028 * (wm - 1.0),
                      1.0 + 0.006 * (wm - 1.0),
                      1.0 - 0.060 * (wm - 1.0)], dtype=np.float32)
    rgb = rgb * grade[None, None, :]
    gray = rgb.mean(axis=2, keepdims=True)
    sat = float(np.clip(0.93 + 0.045 * (wm - 1.0), 0.85, 1.12))
    rgb = gray + (rgb - gray) * sat
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", action="append", required=True)
    ap.add_argument("--suffix", default="-shop-wall")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--width", type=int, default=1206)
    ap.add_argument("--layout", choices=["inline", "stacked"], default="inline")
    ap.add_argument("--no-dot", action="store_true")
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--block-h", type=float, default=96.0)
    ap.add_argument("--block-w", type=float, default=196.0)
    ap.add_argument("--warp", type=float, default=8.0)
    ap.add_argument("--joint", type=float, default=17.0)
    ap.add_argument("--style", choices=["voronoi", "courses"], default="voronoi")
    ap.add_argument("--cell-x", type=float, default=240.0)
    ap.add_argument("--cell-y", type=float, default=140.0)
    ap.add_argument("--edge-w", type=float, default=5.0)
    ap.add_argument("--mortar", type=float, default=32.0)
    ap.add_argument("--warmth", type=float, default=1.8,
                    help="暖色の強さ（0=寒色寄り / 1=標準 / 2=かなり暖かい）")
    ap.add_argument("--quality", type=int, default=92)
    args = ap.parse_args()

    lm = _load_logo_mod()
    for src in args.input:
        base, ext = os.path.splitext(os.path.basename(src))
        outdir = args.outdir or os.path.dirname(src) or "."
        dst = os.path.join(outdir, f"{base}{args.suffix}{ext}")
        if os.path.exists(dst):
            raise SystemExit(f"出力先が既に存在します（上書き禁止）: {dst}")

        im = Image.open(src).convert("RGB")
        rect = detect_photo_rect(im)

        if args.style == "voronoi":
            wall = voronoi_wall(im.size, seed=args.seed, cell_x=args.cell_x,
                                cell_y=args.cell_y, warp=args.warp,
                                edge_w=args.edge_w, mortar=args.mortar,
                                warmth=args.warmth).convert("RGBA")
        else:
            wall = jagged_wall(im.size, seed=args.seed, block_h=args.block_h,
                               block_w=args.block_w, warp=args.warp,
                               joint=args.joint).convert("RGBA")

        # 写真の下に柔らかい影
        shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sx0, sy0, sx1, sy1 = rect
        off = max(4, im.size[1] // 55)
        ImageDraw.Draw(shadow).rectangle([sx0 - 2, sy0 + off, sx1 + 2, sy1 + off],
                                         fill=(90, 78, 66, 70))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(10, im.size[1] // 40)))
        canvas = Image.alpha_composite(wall, shadow)

        # 写真を元の位置へ戻す
        canvas.paste(im.crop((sx0, sy0, sx1 + 1, sy1 + 1)), (sx0, sy0))

        # ロゴを描き直す
        text_box, dot_box = lm.detect_logo(im)
        union = (min(text_box[0], dot_box[0]), min(text_box[1], dot_box[1]),
                 max(text_box[2], dot_box[2]), max(text_box[3], dot_box[3]))
        orig_h = union[3] - union[1] + 1
        max_w = min(int(im.width * 0.46), union[2] - int(im.width * 0.475))
        size_latin = orig_h * 0.80
        size_cjk = size_latin * 0.72
        if args.layout == "stacked":
            lockup = lm.layout_stacked("AKI", "楽天市場店", size_latin, size_cjk,
                                       size_cjk * 0.10, not args.no_dot, "bold")
            if lockup.width > max_w:
                f = max_w / lockup.width
                lockup = lockup.resize((max(1, int(lockup.width * f)),
                                        max(1, int(lockup.height * f))), Image.LANCZOS)
        else:
            lockup, _, _ = lm.layout_text("AKI", "楽天市場店", size_latin, size_cjk,
                                          size_cjk * 0.04, not args.no_dot, "bold")
            lockup = lm.trim(lockup)
            if lockup.width > max_w:
                f = max_w / lockup.width
                lockup = lockup.resize((max(1, int(lockup.width * f)),
                                        max(1, int(lockup.height * f))), Image.LANCZOS)

        px = int(union[2] - lockup.width + 1)
        py = int((union[1] + union[3]) / 2 - lockup.height / 2)

        # 壁の上でも読めるよう、淡い光だまり＋ごく薄い影を後ろに敷く
        halo = Image.new("RGBA", im.size, (0, 0, 0, 0))
        mask = lockup.split()[3].point(lambda v: int(v * 0.55))
        halo.paste(Image.new("RGBA", lockup.size, (246, 240, 228, 255)), (px, py), mask)
        halo = halo.filter(ImageFilter.GaussianBlur(max(6, int(lockup.height * 0.14))))
        canvas = Image.alpha_composite(canvas, halo)

        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        m2 = lockup.split()[3].point(lambda v: int(v * 0.30))
        sh.paste(Image.new("RGBA", lockup.size, (60, 52, 44, 255)),
                 (px + max(2, lockup.height // 26), py + max(3, lockup.height // 20)), m2)
        sh = sh.filter(ImageFilter.GaussianBlur(max(3, lockup.height // 30)))
        canvas = Image.alpha_composite(canvas, sh)

        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        layer.paste(lockup, (px, py), lockup)
        canvas = Image.alpha_composite(canvas, layer)

        out = canvas.convert("RGB")
        if args.width:
            f = args.width / out.width
            out = out.resize((args.width, int(round(out.height * f))), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        out.save(dst, quality=args.quality, subsampling=0, optimize=True)
        print(f"[ok] {src} -> {dst}  size={out.size}  photo_rect={rect}")


if __name__ == "__main__":
    sys.exit(main())
