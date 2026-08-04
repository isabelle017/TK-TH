"""Official EchoTik offline product-list API integration."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from product_research import Market, ProductInsight

logger = logging.getLogger(__name__)
BASE_URL = "https://open.echotik.live"
PRODUCT_LIST_PATH = "/api/v3/echotik/product/list"


class EchoTikAPIError(RuntimeError):
    pass


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


def _price_usd(item: dict, thb_to_usd: float) -> float:
    average = _number(item.get("spu_avg_price"))
    try:
        skus = json.loads(item.get("skus") or "[]")
        currency = skus[0]["real_price"]["currency"].upper() if skus else ""
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        currency = ""
    if currency == "THB":
        return average * thb_to_usd
    if currency in {"USD", ""}:
        return average
    raise EchoTikAPIError(f"暂不支持 EchoTik 价格币种: {currency}")


def _growth_percentage(item: dict) -> float:
    recent_7d = _number(item.get("total_sale_7d_cnt"))
    recent_30d = _number(item.get("total_sale_30d_cnt"))
    previous_23d = max(0.0, recent_30d - recent_7d)
    previous_weekly_pace = previous_23d / 23 * 7
    if previous_weekly_pace <= 0:
        return 100.0 if recent_7d > 0 else 0.0
    return (recent_7d / previous_weekly_pace - 1) * 100


async def fetch_echotik_products(
    markets: list[str],
    config: dict,
) -> list[ProductInsight]:
    username = os.getenv("ECHOTIK_USERNAME", "")
    password = os.getenv("ECHOTIK_PASSWORD", "")
    if not username or not password:
        raise EchoTikAPIError("缺少 ECHOTIK_USERNAME / ECHOTIK_PASSWORD")

    page_size = min(10, int(config.get("page_size", 10)))
    pages = max(1, int(config.get("pages", 1)))
    thb_to_usd = float(config.get("thb_to_usd", 0.028))
    results: list[ProductInsight] = []

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        auth=httpx.BasicAuth(username, password),
        timeout=30.0,
    ) as client:
        for market_code in markets:
            market = Market(market_code.lower())
            for page_num in range(1, pages + 1):
                params = {
                    "region": market_code.upper(),
                    "page_num": page_num,
                    "page_size": page_size,
                    "sales_trend_flag": int(config.get("sales_trend_flag", 1)),
                    "min_total_sale_cnt": int(config.get("min_total_sale_cnt", 100)),
                    "product_sort_field": int(config.get("product_sort_field", 4)),
                    "sort_type": int(config.get("sort_type", 1)),
                    "off_mark": int(config.get("off_mark", 0)),
                }
                response = await client.get(PRODUCT_LIST_PATH, params=params)
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise EchoTikAPIError(f"EchoTik 返回非 JSON: HTTP {response.status_code}") from exc
                if response.status_code != 200 or payload.get("code") != 0:
                    raise EchoTikAPIError(
                        f"EchoTik API 失败: {payload.get('message', response.status_code)}"
                    )
                rows = payload.get("data") or []
                if not rows:
                    break
                for item in rows:
                    price = _price_usd(item, thb_to_usd)
                    if price <= 0:
                        continue
                    results.append(ProductInsight(
                        product_id=str(item.get("product_id", "")),
                        title=str(item.get("product_name", "")).strip(),
                        price=price,
                        sales_volume=int(_number(item.get("total_sale_cnt"))),
                        sales_growth_7d=_growth_percentage(item),
                        sales_growth_30d=0.0,
                        revenue_estimate=_number(item.get("total_sale_gmv_30d_amt")),
                        # EchoTik has creator saturation, not multi-seller count; use it as the
                        # closest conservative competition proxy for this product.
                        seller_count=int(_number(item.get("total_ifl_cnt"))),
                        avg_price=price,
                        comments=int(_number(item.get("review_count"))),
                        engagement_rate=0.0,
                        source="echotik_api",
                        market=market,
                        fetched_at=datetime.now(timezone.utc),
                    ))
    logger.info("EchoTik 官方 API 获取到 %d 条真实商品", len(results))
    return results
