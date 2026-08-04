import unittest

from product_research.unit_economics import (
    UnitEconomicsAssumptions,
    estimate_unit_economics,
)


class UnitEconomicsTests(unittest.TestCase):
    def test_high_returns_reduce_profit_and_allowable_cpa(self):
        baseline = estimate_unit_economics(20, UnitEconomicsAssumptions(return_rate=0.05))
        stressed = estimate_unit_economics(20, UnitEconomicsAssumptions(return_rate=0.30))

        self.assertGreater(baseline.contribution_profit, stressed.contribution_profit)
        self.assertGreater(baseline.max_allowable_cpa, stressed.max_allowable_cpa)

    def test_invalid_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            UnitEconomicsAssumptions(cogs_rate=1.1)

    def test_break_even_roas_matches_revenue_over_allowable_cpa(self):
        result = estimate_unit_economics(25, UnitEconomicsAssumptions())
        self.assertIsNotNone(result.break_even_roas)
        self.assertAlmostEqual(
            result.break_even_roas,
            result.realized_revenue / result.max_allowable_cpa,
            places=3,
        )


if __name__ == "__main__":
    unittest.main()
