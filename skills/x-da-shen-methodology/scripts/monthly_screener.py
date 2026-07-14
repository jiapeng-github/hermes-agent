#!/usr/bin/env python3
"""
月度初筛脚本：BOM 逆向拆解 + 卡脖子环节筛选 + 专精特新冠军匹配

依赖：a-stock-data skill、neodata-financial-search skill
本脚本为辅助工具，实际执行时由 LLM 调用上述 skill 获取实时数据，
脚本提供打分模型、排序逻辑和输出格式化。
"""

import json
from typing import NamedTuple


class BottleneckLink(NamedTuple):
    """卡脖子环节"""
    sector: str            # 赛道名称
    link_name: str         # 环节名称
    localization_rate: float  # 国产化率 (0-100)
    cost_ratio: float      # 成本占比 (0-100)
    expansion_cycle: int   # 扩产周期（月）
    score: float           # 垄断得分
    companies: list        # 匹配的公司列表


def score_monopoly(localization_rate: float, cost_ratio: float, expansion_cycle: int) -> float:
    """
    三维垄断打分
    
    Args:
        localization_rate: 国产化率 (0-100, 越低越垄断)
        cost_ratio: 成本占比 (0-100, 越低越好, 意味着涨价空间大)
        expansion_cycle: 扩产周期（月，越长越难进入）
    
    Returns:
        垄断得分 (0-5, 越高越垄断)
    """
    # 维度1：国产化率打分
    if localization_rate < 10:
        l_score = 5
    elif localization_rate < 20:
        l_score = 4
    elif localization_rate < 50:
        l_score = 2
    else:
        l_score = 0

    # 维度2：成本占比打分（越低越好--小成本高壁垒）
    if cost_ratio < 3:
        c_score = 5
    elif cost_ratio < 5:
        c_score = 4
    elif cost_ratio < 10:
        c_score = 2
    else:
        c_score = 0

    # 维度3：扩产周期打分
    if expansion_cycle > 24:
        e_score = 5
    elif expansion_cycle >= 18:
        e_score = 4
    elif expansion_cycle >= 12:
        e_score = 2
    else:
        e_score = 0

    # 加权综合（国产化率 40%，成本占比 30%，扩产周期 30%）
    weighted = l_score * 0.4 + c_score * 0.3 + e_score * 0.3
    return round(weighted, 1)


def filter_bottleneck_link(sector: str, link: dict) -> BottleneckLink | None:
    """
    筛选符合条件的卡脖子环节
    
    条件：
    - 国产化率 < 20%
    - 成本占比 < 5%
    - 扩产周期 > 18 个月
    """
    loc_rate = link.get("localization_rate", 100)
    cost_pct = link.get("cost_ratio", 100)
    exp_cycle = link.get("expansion_cycle", 0)

    if loc_rate >= 20:
        return None
    if cost_pct >= 5:
        return None
    if exp_cycle <= 18:
        return None

    score = score_monopoly(loc_rate, cost_pct, exp_cycle)
    return BottleneckLink(
        sector=sector,
        link_name=link["name"],
        localization_rate=loc_rate,
        cost_ratio=cost_pct,
        expansion_cycle=exp_cycle,
        score=score,
        companies=link.get("companies", [])
    )


def filter_companies(companies: list) -> list:
    """筛选符合市值和资质的公司"""
    results = []
    for c in companies:
        mc = c.get("market_cap", 0)  # 亿
        is_st = c.get("is_st", False)
        is_ipo_less_2yr = c.get("is_ipo_less_2yr", False)
        is_specialized = c.get("is_specialized_new", False)  # 专精特新
        is_champion = c.get("is_single_champion", False)     # 单项冠军

        # 排除 ST 和次新股
        if is_st or is_ipo_less_2yr:
            continue

        # 市值约束：30亿-150亿
        if mc < 30 or mc > 150:
            continue

        # 必须是专精特新或单项冠军
        if not (is_specialized or is_champion):
            continue

        results.append(c)
    return results


def generate_monthly_report(sector_name: str, links: list, output_path: str = None) -> str:
    """生成月度初筛报告"""
    lines = []
    lines.append(f"# {sector_name} 卡脖子环节月度初筛报告")
    lines.append(f"")
    lines.append("## 筛选条件")
    lines.append("- 国产化率 < 20%")
    lines.append("- 成本占比 < 5%")
    lines.append("- 扩产周期 > 18 个月")
    lines.append("- 市值 30亿-150亿")
    lines.append("- 专精特新 / 单项冠军")
    lines.append("")

    all_companies = []
    for link_data in links:
        result = filter_bottleneck_link(sector_name, link_data)
        if result:
            lines.append(f"### {result.link_name}")
            lines.append(f"- 国产化率: {result.localization_rate}%")
            lines.append(f"- 成本占比: {result.cost_ratio}%")
            lines.append(f"- 扩产周期: {result.expansion_cycle}个月")
            lines.append(f"- 垄断得分: {result.score}/5")
            lines.append("")

            qualified = filter_companies(result.companies)
            all_companies.extend(qualified)

    # 输出汇总表
    if all_companies:
        lines.append("## 候选标的")
        lines.append("| 排名 | 代码 | 名称 | 环节 | 得分 | 市值(亿) | 专精特新 | 单项冠军 |")
        lines.append("|------|------|------|------|------|----------|----------|----------|")
        all_companies.sort(key=lambda x: x.get("monopoly_score", 0), reverse=True)
        for i, c in enumerate(all_companies[:20], 1):
            lines.append(
                f"| {i} | {c.get('code','')} | {c.get('name','')} | "
                f"{c.get('link','')} | {c.get('monopoly_score','')} | "
                f"{c.get('market_cap','')} | "
                f"{'✓' if c.get('is_specialized_new') else '✗'} | "
                f"{'✓' if c.get('is_single_champion') else '✗'} |"
            )

    report = "\n".join(lines)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
    return report


# 示例：人形机器人赛道 BOM 数据模板
EXAMPLE_BOM_DATA = [
    {
        "name": "六维力传感器",
        "localization_rate": 5,
        "cost_ratio": 3,
        "expansion_cycle": 22,
        "companies": [
            {
                "code": "603662", "name": "柯力传感",
                "market_cap": 65, "is_st": False, "is_ipo_less_2yr": False,
                "is_specialized_new": True, "is_single_champion": True,
                "monopoly_score": 4.6, "link": "六维力传感器"
            },
            {
                "code": "688100", "name": "威胜信息",
                "market_cap": 80, "is_st": False, "is_ipo_less_2yr": False,
                "is_specialized_new": True, "is_single_champion": False,
                "monopoly_score": 4.2, "link": "六维力传感器"
            }
        ]
    },
    {
        "name": "谐波减速器",
        "localization_rate": 15,
        "cost_ratio": 8,
        "expansion_cycle": 20,
        "companies": [
            {
                "code": "688017", "name": "绿的谐波",
                "market_cap": 120, "is_st": False, "is_ipo_less_2yr": False,
                "is_specialized_new": True, "is_single_champion": True,
                "monopoly_score": 4.3, "link": "谐波减速器"
            }
        ]
    }
]

if __name__ == "__main__":
    report = generate_monthly_report("人形机器人", EXAMPLE_BOM_DATA)
    print(report)
