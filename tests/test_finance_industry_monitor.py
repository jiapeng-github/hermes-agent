import unittest

from hermes_cli.finance_industry_monitor import (
    _parse_market_breadth,
    _parse_northbound,
    _rank_groups,
    _split_market_sample,
)


class FinanceIndustryMonitorTest(unittest.TestCase):
    def test_parse_market_breadth_combines_mx_tables(self):
        payload = {
            "data": [
                {
                    "columns": ["2026-07-10(日)", "全部A股"],
                    "items": [
                        ["上涨家数", "3772"],
                        ["下跌家数", "1678"],
                        ["平盘家数", "71"],
                        ["成交额(合计)", "3.411万亿"],
                    ],
                },
                {
                    "columns": ["全部A股", "2026-07-10"],
                    "items": [["涨停家数", "95"], ["跌停家数", "7"]],
                },
            ]
        }

        breadth, as_of, turnover = _parse_market_breadth(payload)

        self.assertEqual(as_of, "2026-07-10")
        self.assertEqual(turnover, 34110)
        self.assertEqual(
            breadth,
            {
                "as_of": "2026-07-10",
                "advancers": 3772,
                "decliners": 1678,
                "flat": 71,
                "limit_up": 95,
                "limit_down": 7,
                "total": 5521,
                "advance_ratio": 69.2,
                "sentiment_label": "普涨",
            },
        )

    def test_parse_northbound_prefers_full_deduplicated_history(self):
        columns = [
            "交易日期",
            "北向资金成交总额(百万)",
            "沪股通-成交总额(百万)",
            "深股通-成交总额(百万)",
        ]
        payload = {
            "data": [
                {
                    "columns": columns,
                    "items": [["2026-07-10", "449280.34", "197704.64", "251575.70"]],
                },
                {
                    "columns": columns,
                    "items": [
                        ["2026-07-10", "449280.34", "197704.64", "251575.70"],
                        ["2026-07-09", "400767.76", "182945.71", "217822.05"],
                    ],
                },
            ]
        }

        northbound, as_of = _parse_northbound(payload)

        self.assertEqual(as_of, "2026-07-10")
        self.assertIsNotNone(northbound)
        assert northbound is not None
        self.assertEqual(northbound["current"]["date"], "2026-07-10")
        self.assertEqual(northbound["current"]["total_yi"], 4492.8)
        self.assertEqual(
            [point["date"] for point in northbound["series"]],
            ["2026-07-09", "2026-07-10"],
        )

    def test_split_market_sample_ranks_union_rows_by_signal(self):
        rows = [
            {"name": "A", "change_percent_value": 3.0, "main_net_inflow_yi": -1.0},
            {"name": "B", "change_percent_value": -5.0, "main_net_inflow_yi": 4.0},
            {"name": "C", "change_percent_value": 8.0, "main_net_inflow_yi": 2.0},
        ]

        gainers, losers, inflows = _split_market_sample(rows)

        self.assertEqual([row["name"] for row in gainers], ["C", "A"])
        self.assertEqual([row["name"] for row in losers], ["B"])
        self.assertEqual([row["name"] for row in inflows], ["B", "C"])

    def test_pressure_rank_ignores_groups_without_outflow(self):
        groups = {
            "流出": {
                "name": "流出",
                "sample_count": 2,
                "turnover_yi": 20.0,
                "main_net_inflow_yi": -8.0,
                "change_sum": -4.0,
                "leaders": [],
            },
            "流入": {
                "name": "流入",
                "sample_count": 3,
                "turnover_yi": 30.0,
                "main_net_inflow_yi": 6.0,
                "change_sum": -2.0,
                "leaders": [],
            },
        }

        ranked = _rank_groups(groups, 5, "pressure")

        self.assertEqual([item["name"] for item in ranked], ["流出"])


if __name__ == "__main__":
    unittest.main()
