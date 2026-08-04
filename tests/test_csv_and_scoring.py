import tempfile
import unittest
from pathlib import Path

from product_research.analyzer_trend import TrendAnalyzer
from product_research.fetcher_csv import fetch_products_from_csv
from product_research.unit_economics import UnitEconomicsAssumptions


HEADER = (
    "product_id,title,market,price_usd,sales_volume,sales_growth_7d_pct,"
    "seller_count,likes,comments,shares,views,avg_price_usd\n"
)


class CsvAndScoringTests(unittest.TestCase):
    def test_csv_import_and_profit_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "products.csv"
            path.write_text(
                HEADER + "p1,Test product,th,20,1000,35,10,1000,100,50,20000,22\n",
                encoding="utf-8",
            )
            products = fetch_products_from_csv(str(path), ["th"])

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].source, "manual_csv")
        analyzer = TrendAnalyzer(
            economics_by_market={"th": UnitEconomicsAssumptions(cogs_rate=0.20)}
        )
        score = analyzer.analyze(products[0])
        self.assertIsNotNone(score.estimated_contribution_margin)
        self.assertIsNotNone(score.break_even_roas)

    def test_missing_columns_fail_loudly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("product_id,title\np1,broken\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                fetch_products_from_csv(str(path), ["th"])


if __name__ == "__main__":
    unittest.main()
