#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
image_edit.py — aki-select 用 画像編集ヘルパー

サブコマンド:
  remove-bg    背景削除（端から塗りつぶし判定した背景色を透明化）
  fetch        画像を取得（URLダウンロード / ローカル複製）
  combine      複数の画像を1つに合成（グリッド / 縦 / 横 / カットアウト貼付）
  background   背景画像を作成（単色 / グラデーション。くすみカラーパレット対応）

規約（/Users/mingpiao/EC_work/eclipse-workspace/aki-work/AGENTS.md）:
  - resources/ には書き込まない（読み取り専用）
  - 既存ファイルの上書き禁止（連番を進める）
  - 加工ログを output/image_edit_log.csv に追記
"""

import argparse
import csv
import os
import sys
import urllib.request
from datetime import datetime

import numpy as np
from PIL import Image, ImageFilter

# ---------- くすみカラーパレット（AGENTS.md §4.1） ----------
PALETTE = {
    "oatmeal":   "#F2EDE4",  # ベース（デフォルト）
    "cream":     "#F7F3EC",  # トップス
    "pink":      "#F5E0E0",  # ワンピース
    "beige":     "#EFE6D8",  # ボトムス
    "gray":      "#E6E4E1",  # アウター
    "lavender":  "#E9E4EF",  # インナー
    "sage":      "#DCE4D8",  # グッズ
    "bluegray":  "#E0E4E8",  # オフィスカジュアル
    "softred":   "#F5DEDE",  # SALE
    "softyellow": "#F6EFD9",  # 新作
    "linegray":  "#8A7F70",  # 線（メイン）
    "fillbeige": "#B7A99A",  # 塗り（メイン）
    "textbrown": "#5A5048",  # 文字
    "accentred": "#BF6B6B",  # アクセント
}


def resolve_color(value: str) -> tuple:
    """パレット名 / #RRGGBB / R,G,B を RGBタプルに変換する。"""
    v = value.strip()
    if v.lower() in PALETTE:
        v = PALETTE[v.lower()]
    if v.startswith("#"):
        v = v.lstrip("#")
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    parts = v.split(",")
    if len(parts) == 3:
        return tuple(int(p) for p in parts)
    raise SystemExit(f"ERROR: 色の指定が不正です: {value!r}（パレット名: {', '.join(PALETTE)}）")


def resolve_out(path: str) -> str:
    """出力パスを検証する。上書き禁止 / resources 禁止。"""
    path = os.path.abspath(path)
    norm = path.replace("\\", "/").lower()
    if "/resources/" in norm:
        raise SystemExit("ERROR: resources/ には書き込めません（読み取り専用）。output/ を指定してください。")
    if os.path.exists(path):
        raise SystemExit(f"ERROR: 出力先が既に存在します（上書き禁止）: {path}\n       連番を進めてください。")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return path


def log_action(command: str, inputs: list, out: str, params: str) -> None:
    """加工ログを output/image_edit_log.csv に追記する。"""
    log_path = os.path.join(os.path.dirname(os.path.abspath(out)), "image_edit_log.csv")
    exists = os.path.exists(log_path)
    try:
        with open(log_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(["timestamp", "command", "inputs", "output", "params"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), command,
                        " | ".join(inputs), os.path.basename(out), params])
    except OSError as e:
        print(f"WARN: ログ書き込みに失敗: {e}", file=sys.stderr)


def load_rgb(path: str) -> Image.Image:
    return Image.open(path).convert("RGB")


def parse_size(text: str) -> tuple:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise SystemExit(f"ERROR: サイズは WIDTHxHEIGHT 形式で指定: {text!r}")


# ======================================================================
# remove-bg（背景削除）
# ======================================================================
def cmd_remove_bg(args) -> None:
    img = Image.open(args.input).convert("RGBA")
    arr = np.asarray(img).astype(np.int16)
    h, w = arr.shape[:2]

    # 背景色: --color 未指定なら4隅の最頻値（の平均）
    if args.color:
        bg = np.array(resolve_color(args.color), dtype=np.float32)
    else:
        corners = np.concatenate([
            arr[:5, :5, :3].reshape(-1, 3), arr[:5, -5:, :3].reshape(-1, 3),
            arr[-5:, :5, :3].reshape(-1, 3), arr[-5:, -5:, :3].reshape(-1, 3),
        ]).astype(np.float32)
        bg = corners.mean(axis=0)

    tol = args.tolerance
    dist = np.sqrt(((arr[:, :, :3] - bg) ** 2).sum(axis=2))
    bg_like = dist <= tol  # 背景色に近いピクセル

    # 端から連結している領域のみ透明化（白い服など内部の類似色は残す）
    visited = np.zeros((h, w), dtype=bool)
    stack = []
    for x in range(w):
        for y in (0, h - 1):
            if bg_like[y, x] and not visited[y, x]:
                stack.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if bg_like[y, x] and not visited[y, x]:
                stack.append((y, x))
    while stack:
        y, x = stack.pop()
        if visited[y, x]:
            continue
        visited[y, x] = True
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and bg_like[ny, nx] and not visited[ny, nx]:
                stack.append((ny, nx))

    alpha = np.where(visited, 0, 255).astype(np.uint8)
    alpha_img = Image.fromarray(alpha, "L")
    if args.feather > 0:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(args.feather))
    img.putalpha(alpha_img)

    out = resolve_out(args.out)
    img.save(out, "PNG")
    removed = float(visited.mean()) * 100
    print(f"OK 背景削除: {args.input} -> {out}")
    print(f"   背景色RGB={tuple(int(v) for v in bg)} 許容差={tol} 透明化率={removed:.1f}%")
    log_action("remove-bg", [args.input], out, f"tol={tol},feather={args.feather},color={args.color or 'auto'}")


# ======================================================================
# fetch（画像を取得）
# ======================================================================
def cmd_fetch(args) -> None:
    out = resolve_out(args.out)
    src = args.source
    if src.lower().startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0 (image-edit skill)"})
        with urllib.request.urlopen(req, timeout=args.timeout) as r, open(out, "wb") as f:
            f.write(r.read())
        kind = "ダウンロード"
    else:
        src = os.path.abspath(src)
        if not os.path.exists(src):
            raise SystemExit(f"ERROR: 元画像が見つかりません: {src}")
        with open(src, "rb") as f:
            data = f.read()
        with open(out, "wb") as f:
            f.write(data)
        kind = "複製（原本は変更なし）"
    print(f"OK 画像取得({kind}): {src} -> {out}")
    log_action("fetch", [src], out, "url" if src.lower().startswith("http") else "copy")


# ======================================================================
# combine（複数の画像を1つに）
# ======================================================================
def load_list(paths: list) -> list:
    imgs = []
    for p in paths:
        imgs.append(Image.open(p).convert("RGBA"))
    return imgs


def cmd_combine(args) -> None:
    imgs = load_list(args.inputs)
    n = len(imgs)
    if n < 2:
        raise SystemExit("ERROR: 2枚以上の画像を指定してください。")

    out = resolve_out(args.out)
    mode = args.mode

    if mode in ("grid", "vertical", "horizontal"):
        gap = args.gap
        bg = resolve_color(args.background or "oatmeal")
        if mode == "vertical":
            cols, rows = 1, n
        elif mode == "horizontal":
            cols, rows = n, 1
        else:
            cols = min(args.cols or n, n)
            rows = (n + cols - 1) // cols

        cell_w = max(im.width for im in imgs)
        cell_h = max(im.height for im in imgs)
        if args.size:
            cell_w, cell_h = parse_size(args.size)
        W = cols * cell_w + (cols + 1) * gap
        H = rows * cell_h + (rows + 1) * gap
        canvas = Image.new("RGBA", (W, H), bg + (255,))

        for i, im in enumerate(imgs):
            r, c = divmod(i, cols)
            scale = min(cell_w / im.width, cell_h / im.height)
            im2 = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
            x = gap + c * (cell_w + gap) + (cell_w - im2.width) // 2
            y = gap + r * (cell_h + gap) + (cell_h - im2.height) // 2
            canvas.alpha_composite(im2, (x, y))

    elif mode == "paste":
        # カットアウト（透過PNG）を背景に並べる。全画像を同一高さに縮小。
        bg = resolve_color(args.background or "oatmeal")
        target_h = args.height
        if args.size:
            W, _ = parse_size(args.size)
        else:
            scaled = []
            for im in imgs:
                s = target_h / im.height
                scaled.append(im.resize((max(1, round(im.width * s)), target_h), Image.LANCZOS))
            W = sum(im.width for im in scaled) + args.gap * (len(scaled) + 1)
        H = target_h + args.gap * 2
        canvas = Image.new("RGBA", (W, H), bg + (255,))
        x = args.gap
        for im in imgs:
            s = target_h / im.height
            im2 = im.resize((max(1, round(im.width * s)), target_h), Image.LANCZOS)
            canvas.alpha_composite(im2, (x, args.gap))
            x += im2.width + args.gap
    else:
        raise SystemExit(f"ERROR: 不明なモード: {mode}")

    canvas = canvas.convert("RGB") if args.background or mode == "paste" else canvas
    canvas.save(out, "PNG" if out.lower().endswith(".png") else "JPEG", quality=95)
    print(f"OK 合成: {n}枚 ({mode}) -> {out}  サイズ={canvas.width}x{canvas.height}")
    log_action("combine", args.inputs, out, f"mode={mode},gap={args.gap},bg={args.background}")


# ======================================================================
# background（背景を作成）
# ======================================================================
def cmd_background(args) -> None:
    W, H = parse_size(args.size)
    out = resolve_out(args.out)
    c1 = resolve_color(args.color)
    if args.color2:
        c2 = resolve_color(args.color2)
        top = np.array(c1, dtype=np.float32)
        bot = np.array(c2, dtype=np.float32)
        rows = np.linspace(0, 1, H)[:, None, None]
        arr = (top[None, None, :] * (1 - rows) + bot[None, None, :] * rows)
        arr = np.repeat(arr, W, axis=1).astype(np.uint8)
        img = Image.fromarray(arr, "RGB")
        grad = "yes"
    else:
        img = Image.new("RGB", (W, H), c1)
        grad = "no"
    img.save(out, "PNG" if out.lower().endswith(".png") else "JPEG", quality=95)
    print(f"OK 背景作成: {out}  サイズ={W}x{H}  グラデーション={grad}")
    log_action("background", [], out, f"size={W}x{H},color={args.color},color2={args.color2}")


# ======================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="aki-select 画像編集ヘルパー")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("remove-bg", help="背景削除（透過PNG化）")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True, help="出力PNGパス")
    p.add_argument("--tolerance", type=int, default=30, help="背景色の許容差（既定30）")
    p.add_argument("--color", help="背景色（パレット名/#RRGGBB/R,G/B。未指定は4隅から自動判定）")
    p.add_argument("--feather", type=int, default=1, help="エッジのぼかしpx（既定1、0で無効）")
    p.set_defaults(func=cmd_remove_bg)

    p = sub.add_parser("fetch", help="画像を取得（URLまたはローカルから複製）")
    p.add_argument("--source", required=True, help="URL または ローカルパス")
    p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=int, default=30)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("combine", help="複数の画像を1つに合成")
    p.add_argument("inputs", nargs="+", help="入力画像（2枚以上）")
    p.add_argument("--out", required=True)
    p.add_argument("--mode", choices=["grid", "vertical", "horizontal", "paste"], default="grid")
    p.add_argument("--cols", type=int, help="grid モードの列数")
    p.add_argument("--gap", type=int, default=20, help="余白px（既定20）")
    p.add_argument("--background", help="背景色（パレット名/#RRGGBB。既定 oatmeal）")
    p.add_argument("--size", help="grid: セルサイズ WxH / paste: 横幅 WxH の W を使用")
    p.add_argument("--height", type=int, default=800, help="paste モードの高さ（既定800）")
    p.set_defaults(func=cmd_combine)

    p = sub.add_parser("background", help="背景画像を作成")
    p.add_argument("--size", required=True, help="WIDTHxHEIGHT")
    p.add_argument("--color", required=True, help="パレット名/#RRGGBB/R,G,B")
    p.add_argument("--color2", help="指定すると縦グラデーション（color -> color2）")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_background)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
