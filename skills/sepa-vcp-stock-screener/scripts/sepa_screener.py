#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEPA + VCP A股量化筛选脚本
基于马克·米勒维尼《股票魔法师》SEPA策略

依赖：pip install akshare pandas numpy tqdm
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

try:
    import akshare as ak
except ImportError:
    print("请先安装 akshare: pip install akshare")
    sys.exit(1)

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# ─────────────────────────────────────────────
# 参数配置（可按需修改）
# ─────────────────────────────────────────────
CONFIG = {
    "revenue_growth_min": 0.25,      # 营收同比增长率门槛
    "profit_growth_yoy_min": 0.30,   # 净利润同比增长率门槛
    "roe_min": 15.0,                 # ROE 最低要求（%）
    "profit_cagr_3y_min": 0.20,      # 三年净利润复合增长率门槛
    "volume_ratio_min": 1.0,         # 近10日均量 / 120日均量 门槛
    "ma_short": 50,                  # 短均线
    "ma_long": 150,                  # 长均线
    "listing_years_min": 1,          # 上市满 N 年
    "recent_vol_days": 10,           # 近期成交量计算窗口
    "base_vol_days": 120,            # 基准成交量计算窗口
    "max_stocks": 50,                # 最多筛查股票数（调试用，None=全部）
}


def get_all_stocks():
    """获取A股全部股票列表，剔除ST和次新股"""
    print("📋 获取A股股票列表...")
    df = ak.stock_info_a_code_name()
    df.columns = ["code", "name"]

    # 剔除 ST / *ST
    st_mask = df["name"].str.contains("ST", na=False)
    df = df[~st_mask].copy()
    print(f"   剔除ST后剩余：{len(df)} 只")

    # 剔除次新股（上市不满1年）
    listing_date_list = []
    cutoff = datetime.today() - timedelta(days=365 * CONFIG["listing_years_min"])
    try:
        ipo_df = ak.stock_ipo_summary_sse()  # 上交所
    except Exception:
        ipo_df = pd.DataFrame()

    # 通过股票基本信息过滤上市日期
    valid_codes = []
    for _, row in df.iterrows():
        code = row["code"]
        try:
            info = ak.stock_individual_info_em(symbol=code)
            listing_str = info[info["item"] == "上市时间"]["value"].values
            if len(listing_str) > 0:
                ld = pd.to_datetime(str(listing_str[0]), errors="coerce")
                if pd.notna(ld) and ld <= cutoff:
                    valid_codes.append(code)
        except Exception:
            # 无法获取则保留（宁可多不可少）
            valid_codes.append(code)

    df = df[df["code"].isin(valid_codes)].copy()
    print(f"   剔除次新股后剩余：{len(df)} 只")
    return df


def get_daily_data(code, n_days=200):
    """获取日线行情数据"""
    try:
        end = datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=n_days * 2)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date=start, end_date=end, adjust="qfq")
        df = df[["日期", "收盘", "成交量"]].copy()
        df.columns = ["date", "close", "volume"]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").tail(n_days)
        return df
    except Exception:
        return None


def check_price_above_ma(df):
    """条件4：股价位于 MA50 和 MA150 之上"""
    if df is None or len(df) < CONFIG["ma_long"]:
        return False, {}
    ma50 = df["close"].rolling(CONFIG["ma_short"]).mean().iloc[-1]
    ma150 = df["close"].rolling(CONFIG["ma_long"]).mean().iloc[-1]
    price = df["close"].iloc[-1]
    passed = price > ma50 and price > ma150
    return passed, {"price": round(price, 2), "MA50": round(ma50, 2), "MA150": round(ma150, 2)}


def check_volume_ratio(df):
    """条件5：近10日均量 > 120日均量"""
    if df is None or len(df) < CONFIG["base_vol_days"]:
        return False, {}
    vol_recent = df["volume"].tail(CONFIG["recent_vol_days"]).mean()
    vol_base = df["volume"].tail(CONFIG["base_vol_days"]).mean()
    ratio = vol_recent / vol_base if vol_base > 0 else 0
    passed = ratio >= CONFIG["volume_ratio_min"]
    return passed, {"vol_ratio": round(ratio, 2)}


def get_financial_data(code):
    """获取财务数据（营收、净利润、ROE等）"""
    try:
        # 获取最近几季度财务数据
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        return df
    except Exception:
        return None


def check_revenue_growth(fin_df):
    """条件2：最近一季度营收同比增长 > 25%"""
    if fin_df is None:
        return False, {}
    try:
        cols = [c for c in fin_df.columns if "营业总收入" in c or "营业收入" in c]
        if not cols:
            return False, {}
        col = cols[0]
        vals = fin_df[col].dropna()
        if len(vals) < 5:
            return False, {}
        latest = float(str(vals.iloc[0]).replace(",", ""))
        yoy = float(str(vals.iloc[4]).replace(",", ""))
        if yoy == 0:
            return False, {}
        growth = (latest - yoy) / abs(yoy)
        passed = growth > CONFIG["revenue_growth_min"]
        return passed, {"rev_yoy_growth": f"{growth*100:.1f}%"}
    except Exception:
        return False, {}


def check_profit_growth(fin_df):
    """条件3：净利润同比 > 30% 且环比正增长"""
    if fin_df is None:
        return False, {}
    try:
        cols = [c for c in fin_df.columns if "净利润" in c and "归母" not in c]
        if not cols:
            cols = [c for c in fin_df.columns if "净利润" in c]
        if not cols:
            return False, {}
        col = cols[0]
        vals = fin_df[col].dropna()
        if len(vals) < 5:
            return False, {}
        q0 = float(str(vals.iloc[0]).replace(",", ""))  # 最新季
        q1 = float(str(vals.iloc[1]).replace(",", ""))  # 上季
        q4 = float(str(vals.iloc[4]).replace(",", ""))  # 去年同期

        yoy = (q0 - q4) / abs(q4) if q4 != 0 else 0
        qoq = (q0 - q1) / abs(q1) if q1 != 0 else 0

        passed = yoy > CONFIG["profit_growth_yoy_min"] and qoq > 0
        return passed, {
            "profit_yoy": f"{yoy*100:.1f}%",
            "profit_qoq": f"{qoq*100:.1f}%"
        }
    except Exception:
        return False, {}


def check_roe(code):
    """条件6：ROE > 15%"""
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code)
        roe_col = [c for c in df.columns if "净资产收益率" in c or "ROE" in c]
        if not roe_col:
            return False, {}
        roe = float(str(df[roe_col[0]].dropna().iloc[0]).replace("%", ""))
        passed = roe > CONFIG["roe_min"]
        return passed, {"roe": f"{roe:.1f}%"}
    except Exception:
        return False, {}


def check_profit_cagr_3y(fin_df):
    """条件7：三年净利润复合增长率 > 20%"""
    if fin_df is None:
        return False, {}
    try:
        cols = [c for c in fin_df.columns if "净利润" in c]
        if not cols:
            return False, {}
        col = cols[0]
        vals = fin_df[col].dropna()
        # 需要至少13期（3年=12个季度）
        if len(vals) < 13:
            return False, {}
        latest = float(str(vals.iloc[0]).replace(",", ""))
        three_years_ago = float(str(vals.iloc[12]).replace(",", ""))
        if three_years_ago <= 0 or latest <= 0:
            return False, {}
        cagr = (latest / three_years_ago) ** (1 / 3) - 1
        passed = cagr > CONFIG["profit_cagr_3y_min"]
        return passed, {"profit_cagr_3y": f"{cagr*100:.1f}%"}
    except Exception:
        return False, {}


def calc_vcp_score(df):
    """VCP 形态评分（0-4分）"""
    if df is None or len(df) < 20:
        return 0, {}
    score = 0
    details = {}

    # +1：近期最大日振幅 < 4%
    recent_5 = df.tail(5)
    # 需要高低价，akshare 日线数据包含
    if "high" in df.columns and "low" in df.columns:
        max_range = ((recent_5["high"] - recent_5["low"]) / recent_5["close"]).max()
        if max_range < 0.04:
            score += 1
            details["low_volatility"] = True
    else:
        # 用收盘价波动替代
        std_5 = recent_5["close"].std() / recent_5["close"].mean()
        if std_5 < 0.02:
            score += 1
            details["low_volatility"] = True

    # +1：最近5日成交量 < 20日均量（回调缩量）
    vol5 = df["volume"].tail(5).mean()
    vol20 = df["volume"].tail(20).mean()
    if vol5 < vol20:
        score += 1
        details["contraction_volume"] = True

    # +1：价格在 MA50 ±5% 以内
    ma50 = df["close"].rolling(50).mean().iloc[-1]
    price = df["close"].iloc[-1]
    if abs(price - ma50) / ma50 < 0.05:
        score += 1
        details["near_ma50"] = True

    # +1：未跌破 MA150
    ma150 = df["close"].rolling(150).mean().iloc[-1]
    if price > ma150:
        score += 1
        details["above_ma150"] = True

    return score, details


def screen_stock(code, name):
    """对单只股票执行全部7项筛选条件 + VCP评分"""
    result = {"code": code, "name": name, "passed": False}

    # 获取日线数据
    daily = get_daily_data(code, n_days=200)

    # 条件4：均线
    c4, d4 = check_price_above_ma(daily)
    if not c4:
        return result

    # 条件5：成交量
    c5, d5 = check_volume_ratio(daily)
    if not c5:
        return result

    # 获取财务数据
    fin = get_financial_data(code)

    # 条件2：营收增长
    c2, d2 = check_revenue_growth(fin)
    if not c2:
        return result

    # 条件3：净利润增长
    c3, d3 = check_profit_growth(fin)
    if not c3:
        return result

    # 条件6：ROE
    c6, d6 = check_roe(code)
    if not c6:
        return result

    # 条件7：三年复合增长
    c7, d7 = check_profit_cagr_3y(fin)
    if not c7:
        return result

    # VCP 评分
    vcp_score, vcp_detail = calc_vcp_score(daily)

    result.update({
        "passed": True,
        "vcp_score": vcp_score,
        **d4, **d5, **d2, **d3, **d6, **d7
    })
    return result


def main():
    print("=" * 60)
    print("  SEPA + VCP A股量化筛选器")
    print("  基于《股票魔法师》马克·米勒维尼策略")
    print("=" * 60)

    stocks = get_all_stocks()

    if CONFIG["max_stocks"]:
        stocks = stocks.head(CONFIG["max_stocks"])
        print(f"⚠️  调试模式：仅筛查前 {CONFIG['max_stocks']} 只")

    print(f"\n🔍 开始逐一筛选 {len(stocks)} 只股票...\n")

    results = []
    iterator = tqdm(stocks.iterrows(), total=len(stocks)) if HAS_TQDM else stocks.iterrows()

    for _, row in iterator:
        code, name = row["code"], row["name"]
        try:
            res = screen_stock(code, name)
            if res["passed"]:
                results.append(res)
        except Exception as e:
            pass  # 静默跳过异常

    if not results:
        print("\n❌ 未找到满足全部条件的股票，请适当放宽筛选阈值。")
        return

    df_result = pd.DataFrame(results)
    df_result = df_result.sort_values("vcp_score", ascending=False)

    print(f"\n✅ 共找到 {len(df_result)} 只满足 SEPA 全部条件的股票：\n")

    # 输出表格
    display_cols = ["code", "name", "vcp_score", "price", "MA50", "MA150",
                    "vol_ratio", "rev_yoy_growth", "profit_yoy", "profit_qoq",
                    "roe", "profit_cagr_3y"]
    display_cols = [c for c in display_cols if c in df_result.columns]
    print(df_result[display_cols].to_string(index=False))

    # 保存结果
    out_path = f"sepa_result_{datetime.today().strftime('%Y%m%d_%H%M')}.csv"
    df_result.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n💾 结果已保存至：{out_path}")

    # VCP 重点推荐
    top = df_result[df_result["vcp_score"] >= 3]
    if len(top) > 0:
        print(f"\n⭐ VCP形态较完整（评分≥3）的重点候选（共{len(top)}只）：")
        for _, r in top.iterrows():
            stars = "⭐" * r["vcp_score"]
            print(f"   {r['code']} {r['name']}  VCP得分: {stars}({r['vcp_score']})")


if __name__ == "__main__":
    main()
