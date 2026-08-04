import tempfile
import unittest
from pathlib import Path

from product_research import Market, ProductInsight
from storage import ProductRecord, Storage


class StorageTests(unittest.TestCase):
    def test_repeated_product_updates_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "products.db"
            storage = Storage(f"sqlite:///{database.as_posix()}")
            first = ProductInsight(
                product_id="p1",
                title="First title",
                price=9.0,
                sales_volume=100,
                source="fastmoss_mcp",
                market=Market.TH,
            )
            updated = first.model_copy(update={
                "title": "Updated title",
                "price": 10.0,
                "sales_volume": 150,
            })
            storage.save_products([first])
            storage.save_products([updated])

            with storage.Session() as session:
                rows = session.query(ProductRecord).all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].title, "Updated title")
                self.assertEqual(rows[0].sales_volume, 150)
            storage.engine.dispose()


if __name__ == "__main__":
    unittest.main()
