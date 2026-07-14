#!/usr/bin/env python3
"""
贝叶斯动态熔断脚本：里程碑跟踪 + 逻辑可信度更新

本脚本提供：
1. 里程碑状态跟踪模板
2. 贝叶斯可信度更新计算
3. 熔断信号生成
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class MilestoneStatus(Enum):
    PENDING = "待确认"
    CONFIRMED = "已确认"
    OVERDUE = "已逾期"
    BREACHED = "已熔断"


@dataclass
class Milestone:
    """硬核里程碑"""
    event: str                    # 事件描述
    deadline: str                 # 最晚时限（"YYYY-MM" 或 "2026-Q2"）
    threshold: str                # 熔断阈值描述
    status: MilestoneStatus
    verification_channel: str     # 验证渠道（"互动易"/"公告"/"新闻"）
    confirmed_date: Optional[str] = None
    notes: str = ""


@dataclass
class PositionMonitor:
    code: str
    name: str
    initial_confidence: float     # 初始逻辑可信度 (0-100)
    milestones: list[Milestone] = field(default_factory=list)

    def update_confidence(self, new_info_bias: float) -> float:
        """
        贝叶斯更新：根据新信息调整可信度
        
        Args:
            new_info_bias: 新信息偏向
                > 1.0: 利好（提升可信度）
                = 1.0: 中性
                < 1.0: 利空（降低可信度）
        
        Returns:
            更新后的可信度
        """
        # 简化贝叶斯更新
        updated = self.initial_confidence * new_info_bias
        self.initial_confidence = min(max(updated, 0), 100)
        return self.initial_confidence

    def check_circuit_breaker(self) -> dict:
        """
        检查熔断条件
        
        Returns:
            {"triggered": bool, "reason": str, "action": str}
        """
        # 条件1：逻辑可信度 < 30%
        if self.initial_confidence < 30:
            return {
                "triggered": True,
                "reason": f"逻辑可信度降至 {self.initial_confidence:.1f}%，低于 30% 熔断阈值",
                "action": "无条件卖出"
            }

        # 条件2：逻辑可信度 < 50%
        if self.initial_confidence < 50:
            return {
                "triggered": True,
                "reason": f"逻辑可信度降至 {self.initial_confidence:.1f}%，低于 50% 减仓阈值",
                "action": "减仓至一半"
            }

        # 条件3：任一里程碑逾期未确认
        for m in self.milestones:
            if m.status == MilestoneStatus.OVERDUE:
                return {
                    "triggered": True,
                    "reason": f"里程碑「{m.event}」逾期未确认，逻辑失效",
                    "action": "卖出"
                }

        return {"triggered": False, "reason": "", "action": "持有"}

    def format_monitor_table(self) -> str:
        """输出贝叶斯动态熔断监控表"""
        lines = []
        lines.append(f"## 标的：{self.name}（{self.code}）")
        lines.append("")
        lines.append("| 序号 | 事件（里程碑） | 最晚时限 | 熔断阈值 | 当前状态 | 验证渠道 |")
        lines.append("|------|---------------|----------|----------|----------|----------|")

        for i, m in enumerate(self.milestones, 1):
            status_icon = {
                MilestoneStatus.PENDING: "⏳",
                MilestoneStatus.CONFIRMED: "✅",
                MilestoneStatus.OVERDUE: "🔴",
                MilestoneStatus.BREACHED: "💀"
            }.get(m.status, "❓")
            lines.append(
                f"| {i} | {m.event} | {m.deadline} | "
                f"{m.threshold} | {status_icon} {m.status.value} | "
                f"{m.verification_channel} |"
            )

        lines.append("")
        breaker = self.check_circuit_breaker()
        lines.append(f"**当前逻辑可信度**：{self.initial_confidence:.0f}%")
        lines.append(f"**熔断状态**：{'🔴 已触发' if breaker['triggered'] else '🟢 正常'}")

        if breaker["triggered"]:
            lines.append(f"**触发原因**：{breaker['reason']}")
            lines.append(f"**操作建议**：**{breaker['action']}**")

        lines.append("")
        lines.append("---")
        return "\n".join(lines)


def example_usage():
    """示例：柯力传感贝叶斯动态熔断"""
    monitor = PositionMonitor(
        code="603662",
        name="柯力传感",
        initial_confidence=75.0,
        milestones=[
            Milestone(
                event="六维力传感器通过特斯拉 Optimus 供应链认证",
                deadline="2026-Q3",
                threshold="未在时限内确认 → 逻辑失效，卖出",
                status=MilestoneStatus.PENDING,
                verification_channel="互动易/公告"
            ),
            Milestone(
                event="六维力传感器产线投产，月产能达 5000 只",
                deadline="2026-Q4",
                threshold="未在时限内确认 → 逻辑失效，卖出",
                status=MilestoneStatus.PENDING,
                verification_channel="公告/新闻"
            ),
            Milestone(
                event="获得人形机器人头部客户批量订单（≥2000万）",
                deadline="2027-Q1",
                threshold="未在时限内确认 → 逻辑失效，卖出",
                status=MilestoneStatus.PENDING,
                verification_channel="公告/互动易"
            )
        ]
    )

    # 模拟一则利好消息更新
    monitor.update_confidence(1.15)  # 利好，提升 15%
    print(monitor.format_monitor_table())

    # 模拟一则利空消息更新
    monitor.update_confidence(0.70)  # 利空，降低 30%
    print(monitor.format_monitor_table())


if __name__ == "__main__":
    example_usage()
