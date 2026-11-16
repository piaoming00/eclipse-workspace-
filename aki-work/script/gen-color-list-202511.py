#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日本語カラー名 + 中国語名 + 色見本(HEX) の一覧を生成する一時スクリプト。
出力:
  design/color/colorchart01.html  … 色見本つき一覧（単体で開けるインライン CSS）
  design/color/colorchart01.xlsx  … 一覧データ（Excel）
"""

import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# (グループ名, [(日本語名, 中国語名, HEX)])
GROUPS = [
    ("ホワイト・アイボリー", [
        ("ホワイト", "白色", "#FFFFFF"),
        ("オフホワイト", "米白色", "#F7F4EF"),
        ("アイボリー", "象牙白", "#F5EFDC"),
        ("ナチュラル", "自然色", "#E8DCC8"),
        ("バニラ", "香草色", "#F3E5AB"),
    ]),
    ("ブラック・グレー", [
        ("ブラック", "黑色", "#000000"),
        ("チャコールブラック", "炭黑色", "#2B2B2B"),
        ("グレー", "灰色", "#808080"),
        ("ライトグレー", "浅灰色", "#C8C8C8"),
        ("ダークグレー", "深灰色", "#4D4D4D"),
        ("チャコールグレー", "炭灰色", "#3C3C3C"),
        ("ガンメタ", "炮铜色（枪灰色）", "#4A4E52"),
        ("グレージュ", "灰褐色（灰米色）", "#B8ADA6"),
    ]),
    ("ブラウン", [
        ("ブラウン", "棕色", "#6B4C3A"),
        ("ライトブラウン", "浅棕色", "#A87C5F"),
        ("ダークブラウン", "深棕色", "#3E2A20"),
        ("ショコラブラウン", "巧克力棕", "#4A2C1D"),
        ("キャメル", "驼色", "#C19A6B"),
        ("キャラメル", "焦糖色", "#C68A4F"),
        ("モカ", "摩卡色", "#7B5B47"),
        ("モカブラウン", "摩卡棕", "#6F4E37"),
        ("ブロンズ", "青铜色", "#A97142"),
        ("ダークブロンズ", "深青铜色", "#6E4B2A"),
        ("ダークオークル", "深赭色", "#9C6B3A"),
        ("コーヒー", "咖啡色", "#4B3621"),
        ("マルーン", "栗色（暗红褐）", "#800000"),
    ]),
    ("ベージュ", [
        ("ベージュ", "米色", "#E3D5C0"),
        ("ライトベージュ", "浅米色", "#F0E6D8"),
        ("モカベージュ", "摩卡米色", "#C8B29A"),
        ("クリーム", "奶油色", "#FFFDD0"),
        ("オートミール", "燕麦色", "#D9CFBB"),
        ("エクリュ", "胚布色", "#F0EAD6"),
    ]),
    ("イエロー", [
        ("イエロー", "黄色", "#FFD700"),
        ("ライトイエロー", "浅黄色", "#FFF3A0"),
        ("マスタード", "芥末黄", "#E1AD01"),
        ("レモンイエロー", "柠檬黄", "#FFF44F"),
        ("ネオンイエロー", "荧光黄", "#E8FF00"),
        ("ダークイエロー", "深黄色（土黄）", "#B8860B"),
    ]),
    ("ブルー", [
        ("ブルー", "蓝色", "#0066CC"),
        ("ライトブルー", "浅蓝色", "#7EC8E3"),
        ("ダークブルー", "深蓝色", "#003366"),
        ("スカイブルー", "天蓝色", "#87CEEB"),
        ("ロイヤルブルー", "宝蓝色", "#4169E1"),
        ("ネイビー", "藏青色", "#000080"),
        ("ネイビーブルー", "藏青蓝", "#1B2A4A"),
        ("サックスブルー", "灰蓝色（萨克森蓝）", "#7FA6C9"),
        ("ターコイズ", "绿松石色", "#40E0D0"),
        ("コバルトブルー", "钴蓝色", "#0047AB"),
        ("トリコロール", "三色蓝", "#2B4C9B"),
        ("インディゴブルー", "靛蓝色", "#2A4B8D"),
        ("ダークインディゴブルー", "深靛蓝", "#1A2E5A"),
        ("ユーズド", "做旧蓝（水洗蓝）", "#6E7CA0"),
        ("ブリーチ", "漂白蓝", "#C9D3DE"),
        ("ライトブリーチ", "浅漂白蓝", "#DDE5ED"),
        ("スーパーブリーチ", "超漂白蓝", "#EFF3F7"),
        ("ダークネイビー", "深藏青", "#101B33"),
    ]),
    ("グリーン", [
        ("グリーン", "绿色", "#008000"),
        ("ライトグリーン", "浅绿色", "#90EE90"),
        ("ダークグリーン", "深绿色", "#013220"),
        ("ミント", "薄荷绿", "#98FF98"),
        ("エメラルドグリーン", "翡翠绿", "#50C878"),
        ("オリーブ", "橄榄绿", "#808000"),
        ("カーキ", "卡其色", "#C3B091"),
        ("ダークカーキ", "深卡其", "#6B6B4A"),
        ("グリーンブルー", "蓝绿色", "#2E8B8B"),
        ("ライムグリーン", "青柠绿", "#32CD32"),
        ("ブルーグリーン", "青绿色", "#00A9A5"),
        ("モスグリーン", "苔藓绿", "#8A9A5B"),
    ]),
    ("パープル", [
        ("パープル", "紫色", "#800080"),
        ("ライトパープル", "浅紫色", "#C39BD3"),
        ("ダークパープル", "深紫色", "#301934"),
        ("ラベンダー", "薰衣草紫", "#B57EDC"),
        ("バイオレット", "紫罗兰", "#7F00FF"),
        ("ディープパープル", "暗紫色", "#36013F"),
        ("パープルピンク", "紫粉色", "#D4739E"),
        ("アメジスト", "紫水晶色", "#9966CC"),
        ("プラム", "李子色", "#8E4585"),
    ]),
    ("ピンク", [
        ("ピンク", "粉色", "#FFC0CB"),
        ("ライトピンク", "浅粉色", "#FFD1DC"),
        ("ベビーピンク", "婴儿粉", "#F4C2C2"),
        ("ピンクベージュ", "粉米色", "#E8C4B8"),
        ("サーモンピンク", "鲑鱼粉", "#FA8072"),
        ("ショッキングピンク", "亮粉色（荧光粉）", "#FC0FC0"),
        ("サンゴ", "珊瑚色", "#FF7F50"),
        ("ダークピンク", "深粉色", "#C1547A"),
        ("サクラ", "樱花粉", "#F7CAC9"),
        ("ピーチ", "蜜桃色", "#FFDAB9"),
        ("ホットピンク", "玫红色", "#FF69B4"),
        ("チェリーピンク", "樱桃粉", "#DE3163"),
        ("くすみピンク", "灰粉色", "#D8A7A7"),
    ]),
    ("レッド", [
        ("レッド", "红色", "#FF0000"),
        ("ダークレッド", "深红色", "#8B0000"),
        ("ワインレッド", "酒红色", "#722F37"),
        ("ボルドー", "波尔多红", "#6D071A"),
        ("バーガンディー", "勃艮第红", "#800020"),
        ("エンジ", "胭脂红", "#8C2B2B"),
        ("ローズ", "玫瑰红", "#E75480"),
        ("朱色", "朱红色", "#E34234"),
        ("紅色", "绯红色", "#C22047"),
    ]),
    ("オレンジ", [
        ("オレンジ", "橙色", "#FFA500"),
        ("ライトオレンジ", "浅橙色", "#FFD8A8"),
        ("アプリコット", "杏色", "#FBCEB1"),
        ("マンゴー", "芒果色", "#FFC324"),
        ("カボチャ", "南瓜色", "#E2711D"),
        ("テラコッタ", "陶土色", "#E2725B"),
        ("ネオンオレンジ", "荧光橙", "#FF5F1F"),
        ("ダークオレンジ", "深橙色", "#D2691E"),
    ]),
    ("メタリック", [
        ("シルバー", "银色", "#C0C0C0"),
        ("ゴールド", "金色", "#D4AF37"),
        ("ピンクゴールド", "玫瑰金", "#B76E79"),
        ("シャンペーンゴールド", "香槟金", "#E6D2B5"),
    ]),
]


def luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_color(hex_color):
    # 背景が明るければ黒文字、暗ければ白文字
    return "#333333" if luminance(hex_color) > 0.6 else "#FFFFFF"


def build_html():
    out = []
    total = sum(len(items) for _, items in GROUPS)
    out.append("""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>カラー一覧 | aki-select</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; padding: 0 0 60px; background: #f2f2f2; color: #333;
  font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
  line-height: 1.4; }
a { color: #333; }
#wrap { max-width: 1100px; margin: 0 auto; padding: 0 16px; }
h1 { font-size: 26px; font-weight: 500; letter-spacing: .12em; text-align: center;
  padding: 36px 0 6px; margin: 0; }
.lead { text-align: center; font-size: 12px; color: #888; margin: 0 0 30px; }
section { background: #fff; padding: 18px 16px 8px; margin: 0 0 18px; }
section > h2 { font-size: 14px; font-weight: 600; letter-spacing: .14em; color: #555;
  margin: 0 0 12px; padding: 0 0 8px; border-bottom: 1px solid #e6e6e6; }
.grid { display: flex; flex-wrap: wrap; }
.chip { width: 12.5%; padding: 3px; }
.chip > div { border: 1px solid #e6e6e6; }
.sw { height: 62px; position: relative; }
.sw span { position: absolute; left: 4px; bottom: 3px; font-size: 9px;
  font-family: "din-2014", Arial, sans-serif; letter-spacing: .04em; }
.name { font-size: 11px; padding: 5px 5px 0; min-height: 32px; }
.cn { font-size: 10px; color: #888; padding: 0 5px 6px; }
@media (max-width: 860px) { .chip { width: 25%; } }
@media (max-width: 520px) { .chip { width: 33.333%; } h1 { font-size: 20px; } }
</style>
</head>
<body>
<div id="wrap">
<h1>カラー一覧</h1>
<p class="lead">日本語カラー名 / 中国語名 / 色見本（全 __TOTAL__ 色）</p>
""" .replace("__TOTAL__", str(total)))

    for gname, items in GROUPS:
        out.append('<section>\n<h2>%s</h2>\n<div class="grid">' % gname)
        for jp, cn, hx in items:
            out.append(
                '<div class="chip"><div>'
                '<div class="sw" style="background:%s"><span style="color:%s">%s</span></div>'
                '<div class="name">%s</div><div class="cn">%s</div>'
                '</div></div>' % (hx, text_color(hx), hx, jp, cn)
            )
        out.append("</div>\n</section>")

    out.append("</div>\n</body>\n</html>\n")
    return "\n".join(out)


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(base, "design", "color")
    os.makedirs(outdir, exist_ok=True)

    html_path = os.path.join(outdir, "colorchart01.html")
    with open(html_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_html())

    xlsx_path = os.path.join(outdir, "colorchart01.xlsx")
    build_xlsx(xlsx_path)

    total = sum(len(i) for _, i in GROUPS)
    print("wrote %s (%d colors)" % (html_path, total))
    print("wrote %s (%d colors)" % (xlsx_path, total))


def build_xlsx(path):
    """一覧データを Excel（.xlsx）に出力する。色見本のセルは実際の色で塗る。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "カラー一覧"

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="F2F2F2")
    heads = ["No", "カテゴリ", "日本語名", "中国語名", "HEX", "色見本"]

    for c, h in enumerate(heads, start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True, size=10)
        cell.fill = head_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    r_i = 1
    no = 0
    for gname, items in GROUPS:
        for jp, cn, hx in items:
            no += 1
            r_i += 1
            values = [no, gname, jp, cn, hx, ""]
            for c, v in enumerate(values, start=1):
                cell = ws.cell(row=r_i, column=c, value=v)
                cell.border = border
                cell.font = Font(size=10)
                cell.alignment = Alignment(vertical="center")
            sw = ws.cell(row=r_i, column=6)
            sw.fill = PatternFill("solid", fgColor=hx.replace("#", "").upper())
            ws.cell(row=r_i, column=5).alignment = Alignment(horizontal="left")

    for c, width in enumerate([6, 22, 22, 24, 12, 12], start=1):
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:F%d" % r_i

    wb.save(path)


if __name__ == "__main__":
    main()
