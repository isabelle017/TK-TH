import tempfile
import unittest
from pathlib import Path

from product_research import Market, ProductInsight, TrendScore
from product_research.selection_engine import SelectionStage, decide_selection_stage
from product_research.selection_report import write_selection_report


def make_product(**overrides):
    values = {
        "product_id": "p1",
        "title": "Demo-friendly household product",
        "price": 20,
        "sales_volume": 1000,
        "sales_growth_7d": 30,
        "seller_count": 10,
        "source": "manual_csv",
        "market": Market.TH,
    }
    values.update(overrides)
    return ProductInsight(**values)


def make_score(**overrides):
    values = {
        "product_id": "p1",
        "market": Market.TH,
        "score": 80,
        "estimated_contribution_margin": 0.20,
        "max_allowable_cpa": 5,
        "break_even_roas": 3.0,
    }
    values.update(overrides)
    return TrendScore(**values)


class SelectionEngineTests(unittest.TestCase):
    profiles = {
        "category_profiles": {
            "home_daily": {
                "disallowed_flags": ["electric", "liquid"],
                "required_for_sample": ["weight_kg", "quality_evidence"],
            },
            "affordable_jewelry": {
                "disallowed_flags": ["unknown_material"],
                "required_for_sample": ["material_spec", "quality_evidence"],
            },
        }
    }

    def test_missing_supplier_data_stops_at_validation(self):
        decision = decide_selection_stage(make_product(), make_score(), {})
        self.assertEqual(decision.stage, SelectionStage.SUPPLIER_VALIDATION)

    def test_high_compliance_risk_is_rejected(self):
        decision = decide_selection_stage(
            make_product(compliance_risk="high"), make_score(), {}
        )
        self.assertEqual(decision.stage, SelectionStage.REJECT)

    def test_complete_candidate_can_enter_sample_test(self):
        product = make_product(
            unit_cost_usd=4,
            outbound_shipping_usd=1,
            packaging_usd=0.2,
            content_score=80,
            compliance_risk="low",
            supplier_moq=30,
            lead_time_days=10,
        )
        decision = decide_selection_stage(product, make_score(), {})
        self.assertEqual(decision.stage, SelectionStage.SAMPLE_TEST)

    def test_report_is_written(self):
        product = make_product()
        score = make_score()
        decision = decide_selection_stage(product, score, {})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.md"
            write_selection_report([(product, score, decision)], str(output))
            text = output.read_text(encoding="utf-8")
        self.assertIn("店铺注册前选品报告", text)
        self.assertIn("询价/合规验证", text)

    def test_electric_home_product_is_rejected(self):
        product = make_product(
            category_code="home_daily", product_flags=["electric"]
        )
        decision = decide_selection_stage(product, make_score(), self.profiles)
        self.assertEqual(decision.stage, SelectionStage.REJECT)

    def test_jewelry_without_material_evidence_stays_in_validation(self):
        product = make_product(
            category_code="affordable_jewelry",
            unit_cost_usd=2,
            outbound_shipping_usd=0.5,
            packaging_usd=0.2,
            content_score=80,
            compliance_risk="low",
            supplier_moq=20,
            lead_time_days=8,
        )
        decision = decide_selection_stage(product, make_score(), self.profiles)
        self.assertEqual(decision.stage, SelectionStage.SUPPLIER_VALIDATION)
        self.assertIn("材质", decision.reasons[0])


if __name__ == "__main__":
    unittest.main()
