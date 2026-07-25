# -*- coding: utf-8 -*-
"""查看数据库中的商品数据"""
import yaml
from storage import create_storage

with open("config.sea.yaml") as f:
    config = yaml.safe_load(f)

storage = create_storage(config["storage"])
products = storage.get_top_products(min_score=0, limit=15)

print("=== Database Products ===")
for p in products:
    hot = "HOT" if p.trend_score >= 82 else "UP" if p.trend_score >= 72 else "  "
    print(
        f"  [{hot}] [{p.market.upper()}] {p.title[:42]:42s}"
        f"  ${p.price:>5.2f}  sales:{p.sales_volume:>6,}  score:{p.trend_score:>5.1f}"
    )
