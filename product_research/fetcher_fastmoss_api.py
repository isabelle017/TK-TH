"""FastMoss official OpenAPI product sales-rank integration."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from product_research import Market, ProductInsight
from product_research.fetcher_fastmoss_export import _category_code

logger = logging.getLogger(__name__)
BASE_URL = "https://openapi.fastmoss.com"
TOKEN_PATH = "/v1/token"
SALES_RANK_PATH = "/api/goods/saleRank"


class FastMossAPIError(RuntimeError):
    pass


def _number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def _rate(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = _number(value)
    return parsed / 100 if parsed > 1 else parsed


def _price_usd(item: dict, thb_to_usd: float) -> float:
    price = _number(item.get("real_price"))
    currency = str(item.get("currency", "USD")).upper()
    if currency == "USD":
        return price
    if currency == "THB":
        return price * thb_to_usd
    raise FastMossAPIError(f"暂不支持 FastMoss 价格币种: {currency}")


def item_to_product(item: dict, market: Market, thb_to_usd: float) -> ProductInsight:
    category = " / ".join(str(value) for value in (item.get("category_name") or []))
    price = _price_usd(item, thb_to_usd)
    return ProductInsight(
        product_id=str(item.get("product_id", "")),
        title=str(item.get("title", "")).strip(),
        price=price,
        sales_volume=int(_number(item.get("total_sold_count"), item.get("sold_count", 0))),
        sales_growth_7d=_number(item.get("sold_count_inc_rate")),
        revenue_estimate=_number(item.get("total_sale_amount")),
        seller_count=int(_number(item.get("total_creator_count"), item.get("creator_count", 0))),
        avg_price=price,
        creator_commission_rate=_rate(item.get("commission_rate")),
        source="fastmoss_api",
        market=market,
        category_code=_category_code(category, ""),
        source_url=str(item.get("detail_url", "")).strip() or None,
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch_fastmoss_api_products(
    markets: list[str],
    config: dict,
) -> list[ProductInsight]:
    client_id = os.getenv("FASTMOSS_CLIENT_ID", "")
    client_secret = os.getenv("FASTMOSS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise FastMossAPIError("缺少 FASTMOSS_CLIENT_ID / FASTMOSS_CLIENT_SECRET")
    pages = max(1, int(config.get("pages", 1)))
    page_size = min(50, max(1, int(config.get("page_size", 20))))
    thb_to_usd = float(config.get("thb_to_usd", 0.028))
    results: list[ProductInsight] = []

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        token_response = await client.post(
            TOKEN_PATH,
            json={"client_id": client_id, "client_secret": client_secret},
            headers={"Content-Type": "application/json"},
        )
        try:
            token_body = token_response.json()
        except ValueError as exc:
            raise FastMossAPIError("FastMoss Token 接口返回非 JSON") from exc
        access_token = (token_body.get("data") or {}).get("access_token")
        if token_response.status_code != 200 or token_body.get("code") != 0 or not access_token:
            raise FastMossAPIError(
                f"FastMoss Token 失败: {token_body.get('msg') or token_body.get('message') or token_response.status_code}"
            )
        client.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })
        for market_code in markets:
            market = Market(market_code.lower())
            for page in range(1, pages + 1):
                payload = {
                    "page": page,
                    "pagesize": page_size,
                    "filter": {"region": market_code.upper()},
                    "orderby": {"field": "sold_count", "type": "desc"},
                }
                response = await client.post(SALES_RANK_PATH, json=payload)
                try:
                    body = response.json()
                except ValueError as exc:
                    raise FastMossAPIError(
                        f"FastMoss 返回非 JSON: HTTP {response.status_code}"
                    ) from exc
                if response.status_code != 200 or body.get("code") != 0:
                    raise FastMossAPIError(
                        f"FastMoss API 失败: {body.get('msg', response.status_code)}"
                    )
                rows = (body.get("data") or {}).get("list") or []
                if not rows:
                    break
                results.extend(item_to_product(item, market, thb_to_usd) for item in rows)
    logger.info("FastMoss 官方 API 获取到 %d 条商品", len(results))
    return results
