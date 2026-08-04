import tempfile
import unittest
from pathlib import Path

import pandas as pd

from product_research.fetcher_fastmoss_export import fetch_fastmoss_exports


class FastMossExportTests(unittest.TestCase):
    def test_chinese_excel_export_is_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "FastMoss_平价首饰.xlsx"
            pd.DataFrame([{
                "商品ID": "j1",
                "商品名称": "Minimal necklace",
                "价格": 9.9,
                "总销量": 1000,
                "7日销量": 140,
                "30日销量": 370,
                "带货达人数": 25,
                "评论数": 80,
                "播放量": 10000,
                "商品链接": "https://example.com/j1",
            }]).to_excel(path, index=False)
            products = fetch_fastmoss_exports({
                "directory": directory,
                "filename_keywords": ["fastmoss"],
                "price_currency": "USD",
            }, ["th"])

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].source, "fastmoss_export")
        self.assertEqual(products[0].category_code, "affordable_jewelry")
        self.assertAlmostEqual(products[0].sales_growth_7d, 100.0)

    def test_non_usd_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                fetch_fastmoss_exports({
                    "directory": directory,
                    "price_currency": "THB",
                }, ["th"])


if __name__ == "__main__":
    unittest.main()
