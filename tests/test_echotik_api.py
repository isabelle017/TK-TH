import unittest

from product_research.fetcher_echotik_api import (
    EchoTikAPIError,
    _growth_percentage,
    _price_usd,
)


class EchoTikAPITests(unittest.TestCase):
    def test_thb_price_is_converted_only_when_currency_is_explicit(self):
        item = {
            "spu_avg_price": 700,
            "skus": '[{"real_price":{"currency":"THB"}}]',
        }
        self.assertAlmostEqual(_price_usd(item, 0.028), 19.6)

    def test_usd_price_is_not_converted(self):
        item = {
            "spu_avg_price": 20,
            "skus": '[{"real_price":{"currency":"USD"}}]',
        }
        self.assertEqual(_price_usd(item, 0.028), 20)

    def test_growth_compares_seven_days_with_prior_weekly_pace(self):
        item = {"total_sale_7d_cnt": 140, "total_sale_30d_cnt": 370}
        self.assertAlmostEqual(_growth_percentage(item), 100.0)

    def test_unknown_currency_fails_instead_of_corrupting_profit(self):
        item = {
            "spu_avg_price": 20,
            "skus": '[{"real_price":{"currency":"EUR"}}]',
        }
        with self.assertRaises(EchoTikAPIError):
            _price_usd(item, 0.028)


if __name__ == "__main__":
    unittest.main()
