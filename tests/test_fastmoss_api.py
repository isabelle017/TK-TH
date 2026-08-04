import unittest

from product_research import Market
from product_research.fetcher_fastmoss_api import FastMossAPIError, item_to_product


class FastMossAPITests(unittest.TestCase):
    def test_sales_rank_item_is_mapped(self):
        product = item_to_product({
            "product_id": "p1",
            "title": "Storage organizer",
            "currency": "THB",
            "real_price": "350",
            "sold_count": 100,
            "total_sold_count": 2000,
            "sold_count_inc_rate": "25%",
            "creator_count": 20,
            "total_creator_count": 40,
            "commission_rate": "15%",
            "category_name": ["Home", "Storage"],
            "detail_url": "https://example.com/p1",
        }, Market.TH, 0.028)
        self.assertAlmostEqual(product.price, 9.8)
        self.assertEqual(product.sales_volume, 2000)
        self.assertEqual(product.sales_growth_7d, 25)
        self.assertEqual(product.creator_commission_rate, 0.15)
        self.assertEqual(product.category_code, "home_daily")

    def test_unknown_currency_is_rejected(self):
        with self.assertRaises(FastMossAPIError):
            item_to_product({
                "product_id": "p1", "title": "x", "currency": "EUR", "real_price": 10,
            }, Market.TH, 0.028)


if __name__ == "__main__":
    unittest.main()
