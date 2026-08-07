import unittest
from types import SimpleNamespace

from product_research import Market, ProductInsight, TrendScore
from product_research.selection_engine import SelectionStage, decide_selection_stage
from scheduler import ProductPipeline


class SchedulerNotificationTests(unittest.TestCase):
    def test_supplier_validation_products_are_detailed_notifications(self):
        product = ProductInsight(
            product_id="th-jewelry-1",
            title="Six-point star necklace",
            price=8.5,
            sales_volume=1200,
            sales_growth_7d=35,
            seller_count=12,
            source="manual_csv",
            market=Market.TH,
            source_url="https://example.test/products/th-jewelry-1",
        )
        score = TrendScore(
            product_id=product.product_id,
            market=Market.TH,
            score=82,
            estimated_contribution_margin=0.18,
            break_even_roas=2.8,
            reasoning="增长和需求信号较强",
        )
        decision = decide_selection_stage(product, score, {})
        self.assertEqual(decision.stage, SelectionStage.SUPPLIER_VALIDATION)

        pipeline = object.__new__(ProductPipeline)
        pipeline.region = "sea"
        pipeline.selection_decisions = {product.product_id: decision}
        pipeline.analyzer = SimpleNamespace(
            thresholds=SimpleNamespace(
                notify_min_score=70,
                hot_score=85,
                trending_score=75,
            )
        )

        messages = pipeline._build_push_messages([(product, score)], {})
        self.assertEqual(len(messages), 1)
        self.assertIn("商品ID: th-jewelry-1", messages[0].body)
        self.assertIn("Six-point star necklace", messages[0].body)
        self.assertIn("询价/合规验证", messages[0].body)
        self.assertIn("https://example.test/products/th-jewelry-1", messages[0].body)


if __name__ == "__main__":
    unittest.main()
