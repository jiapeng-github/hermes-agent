#!/usr/bin/env python3
"""
季度复审脚本：财务硬核穿透分析 + 研报过热度排除

依赖：a-stock-data skill、neodata-financial-search skill
本脚本为辅助工具，提供财务指标计算和研报统计逻辑。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QuarterlyFinancials:
    """单季度财务数据"""
    quarter: str           # e.g., "2026Q1"
    revenue: float         # 营收（亿）
    revenue_yoy: float     # 营收同比增速 (%)
    gross_margin: float    # 毛利率 (%)
    core_gross_margin: float  # 扣非毛利率 (%)
    net_profit: float      # 归母净利润（亿）
    core_net_profit: float  # 扣非净利润（亿）
    capex: float           # 资本支出（亿）
    construction_in_progress: float  # 在建工程（亿）
    fixed_assets: float    # 固定资产（亿）


@dataclass
class QuarterlyReview:
    code: str
    name: str
    quarters: list[QuarterlyFinancials] = field(default_factory=list)

    @property
    def margin_trend(self) -> dict:
        """毛利率趋势分析"""
        if len(self.quarters) < 2:
            return {"trend": "insufficient_data", "expansion": False}

        margins = [q.gross_margin for q in self.quarters]
        # 检查是否连续扩张
        expanding_count = sum(
            1 for i in range(1, len(margins)) if margins[i] > margins[i-1]
        )
        total_jumps = len(margins) - 1

        # 至少 3/4 季度在扩张
        expansion = expanding_count >= 3 and total_jumps >= 3
        # 最近季度相对最早季度提升 >2%
        margin_increase = margins[-1] - margins[0] if margins else 0
        significant = margin_increase > 2

        # 验证扣非毛利率一致性（偏离 <5%）
        core_diffs = [
            abs(q.gross_margin - q.core_gross_margin) for q in self.quarters
            if q.core_gross_margin > 0
        ]
        clean = all(d < 5 for d in core_diffs) if core_diffs else True

        return {
            "trend": "expanding" if (expansion and significant and clean) else "flat_or_declining",
            "expansion": expansion,
            "significant": significant,
            "clean": clean,
            "margin_increase_pct": round(margin_increase, 2),
            "latest_margin": margins[-1] if margins else 0
        }

    @property
    def capex_signal(self) -> dict:
        """资本支出信号"""
        if len(self.quarters) < 2:
            return {"signal": False}

        latest = self.quarters[-1]
        prev_year_same_q = self.quarters[0]  # 简化：取最早季度

        capex_yoy = 0
        if prev_year_same_q.capex > 0:
            capex_yoy = (latest.capex - prev_year_same_q.capex) / prev_year_same_q.capex * 100

        # 在建工程连续增长
        cip_increasing = True
        for i in range(1, len(self.quarters)):
            if self.quarters[i].construction_in_progress <= self.quarters[i-1].construction_in_progress:
                cip_increasing = False
                break

        # 在建工程/固定资产 >15%
        cip_ratio = 0
        if latest.fixed_assets > 0:
            cip_ratio = latest.construction_in_progress / latest.fixed_assets * 100

        signal = (
            capex_yoy > 30 and
            cip_increasing and
            cip_ratio > 15
        )

        return {
            "signal": signal,
            "capex_yoy_pct": round(capex_yoy, 2),
            "cip_increasing": cip_increasing,
            "cip_ratio_pct": round(cip_ratio, 2),
            "latest_capex": latest.capex,
            "latest_cip": latest.construction_in_progress
        }

    @property
    def overall_score(self) -> dict:
        """综合评分"""
        margin = self.margin_trend
        capex = self.capex_signal

        passing = (
            margin["expansion"] and
            margin["significant"] and
            margin["clean"] and
            capex["signal"]
        )

        return {
            "pass": passing,
            "margin_trend": margin["trend"],
            "capex_signal": capex["signal"],
            "details": {
                "margin": margin,
                "capex": capex
            }
        }


def check_report_overheat(code: str, report_count: int) -> dict:
    """
    研报过热度检查
    
    Args:
        code: 股票代码
        report_count: 近 3 个月研报篇数
    
    Returns:
        {"overheated": bool, "reason": str}
    """
    if report_count > 15:
        return {
            "overheated": True,
            "reason": f"近3个月研报数 {report_count} 篇，超过阈值 15 篇，信息差已收窄"
        }
    return {"overheated": False, "reason": ""}


def format_quarterly_report(reviews: list[QuarterlyReview]) -> str:
    """格式化季度复审报告"""
    lines = ["# 季度复审报告（财务硬核穿透）", ""]

    for r in reviews:
        score = r.overall_score
        lines.append(f"## {r.name}（{r.code}）")
        lines.append(f"- 综合判断：{'✅ 通过' if score['pass'] else '❌ 未通过'}")
        lines.append(f"- 毛利率趋势：{score['details']['margin']['trend']}")
        lines.append(f"- 毛利率提升幅度：{score['details']['margin']['margin_increase_pct']}%")
        lines.append(f"- 最新毛利率：{score['details']['margin']['latest_margin']}%")
        lines.append(f"- CapEx 同比增速：{score['details']['capex']['capex_yoy_pct']}%")
        lines.append(f"- 在建工程/固定资产：{score['details']['capex']['cip_ratio_pct']}%")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 示例数据
    example = QuarterlyReview(
        code="603662", name="柯力传感",
        quarters=[
            QuarterlyFinancials("2025Q4", 3.5, 28, 42.5, 41.8, 0.65, 0.62, 0.45, 4.2, 22.0),
            QuarterlyFinancials("2026Q1", 3.8, 32, 43.8, 43.2, 0.72, 0.70, 0.52, 4.8, 22.5),
            QuarterlyFinancials("2026Q2", 4.2, 35, 45.2, 44.8, 0.85, 0.83, 0.58, 5.5, 23.0),
            QuarterlyFinancials("2026Q3", 4.6, 38, 46.5, 46.1, 0.95, 0.93, 0.68, 6.2, 23.5),
        ]
    )
    print(format_quarterly_report([example]))
    print(check_report_overheat("603662", 8))
