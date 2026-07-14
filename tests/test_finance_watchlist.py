import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hermes_cli.finance_watchlist import (
    _read_entries,
    add_watchlist_stock,
    _build_sector_performance,
    _build_technicals,
    _parse_indices,
    _parse_kline,
    _parse_watchlist_quotes,
    remove_watchlist_stock,
)


class FinanceWatchlistTest(unittest.TestCase):
    def test_add_and_remove_stock_persist_in_profile_directory(self):
        resolved = {
            "code": "601318",
            "name": "中国平安",
            "exchange": "SH",
            "industry": "非银金融",
            "added_at": "2026-07-10T00:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as home:
            with (
                patch("hermes_cli.finance_watchlist._home_key", return_value=home),
                patch("hermes_cli.finance_watchlist.resolve_watchlist_stock", return_value=resolved),
                patch(
                    "hermes_cli.finance_watchlist.start_watchlist_refresh",
                    return_value={"status": "running"},
                ),
            ):
                added = add_watchlist_stock("中国平安")
                persisted_after_add = _read_entries(home)
                removed = remove_watchlist_stock("601318")
                persisted_after_remove = _read_entries(home)

        self.assertTrue(added["added"])
        self.assertIn("601318", [entry["code"] for entry in persisted_after_add])
        self.assertTrue(removed["removed"])
        self.assertNotIn("601318", [entry["code"] for entry in persisted_after_remove])

    def test_legacy_watchlist_is_migrated_once_and_retained_as_fallback(self):
        legacy_payload = {
            "version": 1,
            "items": [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "exchange": "SH",
                    "industry": "食品饮料",
                    "added_at": "2026-07-10T00:00:00+00:00",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / "finance" / "watchlist.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps(legacy_payload), encoding="utf-8")

            entries = _read_entries(home)
            migrated = (
                Path(home)
                / "app-data"
                / "ai.hermes.watchlist"
                / "storage"
                / "watchlist.json"
            )

            self.assertEqual([entry["code"] for entry in entries], ["600519"])
            self.assertTrue(migrated.is_file())
            self.assertEqual(json.loads(legacy.read_text(encoding="utf-8")), legacy_payload)

    def test_parse_watchlist_quotes_merges_snapshot_and_history_tables(self):
        entries = [
            {
                "code": "300750",
                "name": "宁德时代",
                "exchange": "SZ",
                "industry": "电力设备",
            },
            {
                "code": "002594",
                "name": "比亚迪",
                "exchange": "SZ",
                "industry": "汽车",
            },
        ]
        payload = {
            "data": [
                {
                    "columns": [
                        "指标(2026-07-10)",
                        "宁德时代(300750.SZ)",
                        "比亚迪(002594.SZ)",
                    ],
                    "items": [
                        ["最新价", "348.76", "90.00"],
                        ["涨跌幅", "-7.12%", "+3.60%"],
                        ["主力净流入", "-22.85亿元", "+10.40亿元"],
                        ["申万行业", "电力设备-电池", "汽车-乘用车"],
                        ["成交额", "221.2亿元", "100亿元"],
                    ],
                },
                {
                    "columns": [
                        "宁德时代(300750.SZ)",
                        "2026-07-10",
                        "2026-07-09",
                        "2026-07-08",
                    ],
                    "items": [
                        ["收盘价", "348.76", "375.49", "381.20"],
                        ["主力净流入", "-22.85亿元", "1.20亿元", "0.80亿元"],
                        ["涨跌幅", "-7.12%", "+0.32%", "+1.10%"],
                    ],
                },
            ]
        }

        quotes, as_of = _parse_watchlist_quotes(payload, entries)

        self.assertEqual(as_of, "2026-07-10")
        self.assertEqual([quote["code"] for quote in quotes], ["300750", "002594"])
        self.assertEqual(quotes[0]["price"], 348.76)
        self.assertEqual(quotes[0]["change_percent"], -7.12)
        self.assertEqual(quotes[0]["main_net_flow_yi"], -22.85)
        self.assertEqual(quotes[0]["turnover_yi"], 221.2)
        self.assertEqual(quotes[0]["sector"], "电力设备")
        self.assertEqual(quotes[0]["sparkline"], [381.2, 375.49, 348.76])
        self.assertEqual(quotes[0]["quote_status"], "ok")

    def test_parse_kline_sorts_points_and_normalizes_units(self):
        payload = {
            "data": [
                {
                    "columns": [
                        "宁德时代(300750.SZ)",
                        "2026-07-10",
                        "2026-07-09",
                        "2026-07-08",
                    ],
                    "items": [
                        ["前复权开盘价", "362.00", "373.00", "380.00"],
                        ["最高价", "366.00", "380.00", "386.00"],
                        ["最低价", "346.16", "370.00", "378.00"],
                        ["收盘价", "348.76", "375.49", "381.20"],
                        ["成交量", "24.5万", "20万", "18万"],
                        ["成交额", "85.4亿元", "75亿元", "69亿元"],
                        ["涨跌幅", "-7.12%", "-1.50%", "+0.80%"],
                    ],
                }
            ]
        }

        points = _parse_kline(payload, "300750")

        self.assertEqual(
            [point["date"] for point in points],
            ["2026-07-08", "2026-07-09", "2026-07-10"],
        )
        self.assertEqual(points[-1]["close"], 348.76)
        self.assertEqual(points[-1]["volume"], 245000)
        self.assertEqual(points[-1]["turnover_yi"], 85.4)
        self.assertEqual(points[-1]["change_percent"], -7.12)

    def test_parse_indices_accepts_plain_names_and_point_value_label(self):
        payload = {
            "data": [
                {
                    "columns": [
                        "指标(2026-07-10)",
                        "上证指数",
                        "深证成份指数",
                        "创业板指(399006)",
                    ],
                    "items": [
                        ["最新点位", "4036.59", "12682.15", "2847.96"],
                        ["涨跌幅", "+1.65%", "+2.10%", "+4.49%"],
                        ["成交额", "1.36万亿", "1.58万亿", "7266亿元"],
                    ],
                }
            ]
        }

        indices, as_of = _parse_indices(payload)

        self.assertEqual(as_of, "2026-07-10")
        self.assertEqual([item["name"] for item in indices], ["上证指数", "深证成指", "创业板指"])
        self.assertEqual(indices[0]["value"], 4036.59)
        self.assertEqual(indices[1]["code"], "399001")
        self.assertEqual(indices[2]["change_percent"], 4.49)

    def test_parse_indices_reads_latest_date_from_horizontal_history(self):
        payload = {
            "data": [
                {
                    "columns": [
                        "上证指数(000001.SH)",
                        "2026-07-09(日)",
                        "2026-07-10(日)",
                        "2026-07-08(日)",
                    ],
                    "items": [
                        ["成交额", "1.364万亿", "1.563万亿", "1.192万亿"],
                        ["收盘价", "4036.5879点", "3996.1616点", "3970.8797点"],
                        ["涨跌幅", "1.655%", "-1.001%", "-0.4851%"],
                    ],
                }
            ]
        }

        indices, as_of = _parse_indices(payload)

        self.assertEqual(as_of, "2026-07-10")
        self.assertEqual(len(indices), 1)
        self.assertEqual(indices[0]["name"], "上证指数")
        self.assertEqual(indices[0]["value"], 3996.1616)
        self.assertEqual(indices[0]["change_percent"], -1.001)
        self.assertEqual(indices[0]["turnover"], "1.563万亿")

    def test_sector_performance_is_equal_weighted_with_flow_sum(self):
        items = [
            {
                "industry": "电子-半导体",
                "change_percent": 4.0,
                "main_net_flow_yi": 3.2,
            },
            {
                "industry": "电子-消费电子",
                "change_percent": -2.0,
                "main_net_flow_yi": -0.7,
            },
            {
                "industry": "银行",
                "change_percent": -1.5,
                "main_net_flow_yi": 0.4,
            },
        ]

        sectors = _build_sector_performance(items)

        self.assertEqual([sector["name"] for sector in sectors], ["电子", "银行"])
        self.assertEqual(sectors[0]["stock_count"], 2)
        self.assertEqual(sectors[0]["avg_change_percent"], 1.0)
        self.assertEqual(sectors[0]["main_net_flow_yi"], 2.5)

    def test_technicals_identify_bullish_alignment(self):
        points = [
            {
                "date": f"2026-07-{day:02d}",
                "open": float(day),
                "high": float(day + 1),
                "low": float(day - 1),
                "close": float(day),
            }
            for day in range(1, 21)
        ]

        technicals = _build_technicals(points)

        self.assertEqual(technicals["trend_label"], "多头排列")
        self.assertEqual(technicals["ma5"], 18.0)
        self.assertEqual(technicals["ma20"], 10.5)
        self.assertEqual(technicals["support"], 0.0)
        self.assertEqual(technicals["resistance"], 21.0)


if __name__ == "__main__":
    unittest.main()
