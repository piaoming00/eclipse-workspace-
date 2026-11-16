#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
販売価格（表示価格）計算スクリプト

  販売価格 = 最低価格 × (1 + 利益率) ÷ (1 - OFF率) ÷ (1 - 手数料率)

  条件: 最低価格 6,070円 / 40%OFF / 最低価格に対し15%利益

使い方:
  python3 script/calc-price-202511.py
  python3 script/calc-price-202511.py --min 6070 6980 --profit 0.15 --discount 0.40
  python3 script/calc-price-202511.py --min 6070 --fee 0.10 --round ceil --unit 10 --xlsx

出力: design/price/pricelist01.xlsx（Excel）
  ※ 派生列（必要実売価格〜実利益率）はセルに計算式を入れて出力し、
     先頭に「計算式」列（人が読める式）と丸め方法 / 丸め単位のパラメータセルを添える
"""

import argparse
import math
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# ---- 既定値 ----------------------------------------------------------------
DEFAULT_MIN_PRICES = [6070]
DEFAULT_PROFIT = 0.15     # 最低価格に対する利益率
DEFAULT_DISCOUNT = 0.40   # 販売価格に対するOFF率
DEFAULT_FEE = 0.0         # 楽天手数料など（実売に対する率）


def round_unit(value, unit, mode):
    """unit 単位で丸める。mode: ceil / floor / round"""
    if unit <= 0:
        return value
    v = value / unit
    if mode == "ceil":
        v = math.ceil(v - 1e-9)
    elif mode == "floor":
        v = math.floor(v + 1e-9)
    else:
        v = math.floor(v + 0.5 + 1e-9)
    return int(v * unit)


def calc(min_price, profit, discount, fee=0.0, unit=1, mode="ceil"):
    required_net = min_price * (1 + profit)          # 確保したい実売（税込）
    raw = required_net / (1 - discount)              # 手数料なしの表示価格
    if fee:
        raw = raw / (1 - fee)
    price = round_unit(raw, unit, mode)
    off_price = round_unit(price * (1 - discount), 1, "floor")  # 実際の販売価格（表示用）
    profit_amount = off_price - min_price
    return {
        "最低価格": min_price,
        "利益率(最低価格比)": profit,
        "OFF率": discount,
        "手数料率": fee,
        "必要実売価格": round(required_net, 2),
        "計算上の販売価格": round(raw, 2),
        "販売価格": price,
        "OFF額": price - off_price,
        "40%OFF後価格": off_price,
        "利益額": profit_amount,
        "実利益率": (profit_amount / min_price) if min_price else 0.0,
    }


def fmt_int(n):
    return "{:,}".format(n)


def print_table(rows):
    head = ["最低価格", "販売価格", "OFF額", "OFF後価格", "利益額", "実利益率"]
    print("")
    print("  ".join(h.rjust(10) for h in head))
    print("-" * 72)
    for r in rows:
        print("  ".join([
            fmt_int(r["最低価格"]).rjust(10),
            fmt_int(r["販売価格"]).rjust(10),
            fmt_int(r["OFF額"]).rjust(10),
            fmt_int(r["40%OFF後価格"]).rjust(10),
            fmt_int(r["利益額"]).rjust(10),
            ("%.2f%%" % (r["実利益率"] * 100)).rjust(10),
        ]))
    print("")


# 列ごとの表示形式（Excel のセル書式）
PERCENT_KEYS = ("利益率(最低価格比)", "OFF率", "手数料率", "実利益率")
DECIMAL_KEYS = ("必要実売価格", "計算上の販売価格")
INT_KEYS = ("最低価格", "販売価格", "OFF額", "40%OFF後価格", "利益額")

# 丸め方法 → Excel 関数
ROUND_FUNC = {"ceil": "ROUNDUP", "floor": "ROUNDDOWN", "round": "ROUND"}
MODE_LABEL = {"ceil": "切上げ", "floor": "切捨て", "round": "四捨五入"}

HEADERS = ["最低価格", "利益率(最低価格比)", "OFF率", "手数料率",
           "必要実売価格", "計算上の販売価格", "販売価格",
           "OFF額", "40%OFF後価格", "利益額", "実利益率", "計算式"]


def write_xlsx(rows, path, mode="ceil", unit=1):
    """計算結果を Excel（.xlsx）に出力する。

    派生列（必要実売価格〜実利益率）はセルに計算式を入れておくので、
    最低価格 / 利益率 / OFF率 / 手数料率 / 丸め単位を書き換えると自動で再計算される。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "価格表"

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="F2F2F2")
    param_fill = PatternFill("solid", fgColor="FBFBFB")

    # --- 計算式・パラメータ ---------------------------------------------
    ws["A1"] = "計算式: 販売価格 = 最低価格 × (1 + 利益率) ÷ (1 - OFF率) ÷ (1 - 手数料率)"
    ws["A1"].font = Font(size=10, bold=True, color="404040")

    ws["A2"], ws["B2"] = "丸め方法", MODE_LABEL[mode]
    ws["A3"], ws["B3"] = "丸め単位", unit
    for addr in ("A2", "A3"):
        ws[addr].font = Font(size=10, bold=True)
    for addr in ("B2", "B3"):
        ws[addr].fill = param_fill
        ws[addr].border = border
        ws[addr].font = Font(size=10)
    ws["B3"].number_format = "#,##0"

    dv = DataValidation(type="list", formula1='"切上げ,切捨て,四捨五入"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(ws["B2"])

    head_row = 5
    for c, h in enumerate(HEADERS, start=1):
        cell = ws.cell(row=head_row, column=c, value=h)
        cell.font = Font(bold=True, size=10)
        cell.fill = head_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # --- データ行（派生列は数式） --------------------------------------
    for i, r in enumerate(rows):
        r_i = head_row + 1 + i
        vals = {
            "最低価格": r["最低価格"],
            "利益率(最低価格比)": r["利益率(最低価格比)"],
            "OFF率": r["OFF率"],
            "手数料率": r["手数料率"],
            # 必要実売価格 = 最低価格 × (1 + 利益率)
            "必要実売価格": "=ROUND(A%d*(1+B%d),2)" % (r_i, r_i),
            # 計算上の販売価格 = 必要実売価格 ÷ (1 - OFF率) ÷ (1 - 手数料率)
            "計算上の販売価格": "=ROUND(E%d/(1-C%d)/(1-D%d),2)" % (r_i, r_i, r_i),
            # 販売価格 = 計算上の販売価格を丸め単位で丸める
            "販売価格": ("=IF($B$2=\"切捨て\",ROUNDDOWN(F%d/$B$3,0),"
                        "IF($B$2=\"四捨五入\",ROUND(F%d/$B$3,0),"
                        "ROUNDUP(F%d/$B$3,0)))*$B$3") % (r_i, r_i, r_i),
            # OFF額 = 販売価格 - OFF後価格
            "OFF額": "=G%d-I%d" % (r_i, r_i),
            # OFF後価格 = 販売価格 × (1 - OFF率)（1円未満切捨て）
            "40%OFF後価格": "=ROUNDDOWN(G%d*(1-C%d),0)" % (r_i, r_i),
            # 利益額 = OFF後価格 - 最低価格
            "利益額": "=I%d-A%d" % (r_i, r_i),
            # 実利益率 = 利益額 ÷ 最低価格
            "実利益率": "=IF(A%d=0,0,J%d/A%d)" % (r_i, r_i, r_i),
        }
        vals["計算式"] = (
            "%s × (1+%.0f%%) ÷ (1-%.0f%%) ÷ (1-%.0f%%) = %s → %s(%s円単位) = %s"
            % (fmt_int(r["最低価格"]), r["利益率(最低価格比)"] * 100,
               r["OFF率"] * 100, r["手数料率"] * 100,
               "{:,.2f}".format(r["計算上の販売価格"]),
               MODE_LABEL[mode], fmt_int(unit), fmt_int(r["販売価格"]))
        )

        for c, k in enumerate(HEADERS, start=1):
            cell = ws.cell(row=r_i, column=c, value=vals[k])
            cell.border = border
            cell.font = Font(size=10)
            if k in PERCENT_KEYS:
                cell.number_format = "0.00%"
            elif k in DECIMAL_KEYS:
                cell.number_format = "#,##0.00"
            elif k in INT_KEYS:
                cell.number_format = "#,##0"

    # --- 列幅 ----------------------------------------------------------
    widths = [12, 15, 9, 10, 14, 16, 12, 10, 13, 10, 11, 62]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[head_row].height = 30

    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)
    if rows:
        ws.auto_filter.ref = "A%d:%s%d" % (
            head_row, get_column_letter(len(HEADERS)), head_row + len(rows))

    wb.save(path)
    print("wrote %s (%d rows)" % (path, len(rows)))
    if rows:
        print("  ※ 派生列は数式です（最低価格 / 利益率 / OFF率 / 手数料率 / B2丸め方法 / B3丸め単位を"
              "書き換えると再計算されます）")


def main():
    p = argparse.ArgumentParser(description="販売価格（40%OFF + 利益率）計算")
    p.add_argument("--min", dest="mins", type=int, nargs="+",
                   default=DEFAULT_MIN_PRICES, help="最低価格（複数可）")
    p.add_argument("--profit", type=float, default=DEFAULT_PROFIT,
                   help="利益率（最低価格比, 例 0.15）")
    p.add_argument("--discount", type=float, default=DEFAULT_DISCOUNT,
                   help="OFF率（例 0.40）")
    p.add_argument("--fee", type=float, default=DEFAULT_FEE,
                   help="手数料率（実売比, 例 0.10）")
    p.add_argument("--round", dest="mode", choices=["ceil", "floor", "round"],
                   default="ceil", help="丸め方法（既定: ceil=切上げ）")
    p.add_argument("--unit", type=int, default=1,
                   help="丸め単位（例 10, 100）")
    p.add_argument("--xlsx", action="store_true", help="Excel を design/price/ に出力")
    p.add_argument("--xlsx-name", default="pricelist01.xlsx", help="Excel ファイル名")
    args = p.parse_args()

    rows = [
        calc(m, args.profit, args.discount, args.fee, args.unit, args.mode)
        for m in args.mins
    ]

    print_table(rows)
    for r in rows:
        print("  %s → 40%%OFF後 %s（利益 %s / %.2f%%）  ※計算値 %.2f" % (
            fmt_int(r["販売価格"]), fmt_int(r["40%OFF後価格"]),
            fmt_int(r["利益額"]), r["実利益率"] * 100, r["計算上の販売価格"]))
    print("")

    if args.xlsx:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        write_xlsx(rows, os.path.join(base, "design", "price", args.xlsx_name),
                   mode=args.mode, unit=args.unit)


if __name__ == "__main__":
    main()
