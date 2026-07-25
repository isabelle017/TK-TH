"""
FastMoss API 客户端

FastMoss 是目前 TikTok 电商数据量最大的平台（5亿+商品）。
接口文档: https://open.fastmoss.com/

注意：FastMoss 没有公开的 REST API。如果需要对接官方接口，
请联系 FastMoss 商务团队（sales@fastmoss.com）获取专有对接方案。

本客户端当前仅作为占位符，返回空列表以便 pipeline 降级到其他数据源。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from product_research import Market, ProductInsight

# ---- 常量 ----
BASE_URL = "https://open.fastmoss.com"
API_VERSION = "v1"
TIMEOUT = 30.0  # 秒

# FastMoss 国家代码 → 我们的 Market 枚举
_MARKET_MAP: dict[str, Market] = {
    "US": Market.US, "UK": Market.UK, "JP": Market.JP,
    "DE": Market.DE, "FR": Market.FR, "ES": Market.ES,
    "IT": Market.IT, "ID": Market.ID, "TH": Market.TH,
    "VN": Market.VN, "PH": Market.PH, "SG": Market.SG, "MY": Market.MY,
    "SA": Market.SA, "MX": Market.MX, "BR": Market.BR,
    "KR": Market.KR, "NL": Market.NL, "CA": Market.CA,
    "AU": Market.AU,
}


class FastMossClient:
    """
    FastMoss API 客户端

    使用示例:
        client = FastMossClient(api_key="your_key")
        products = await client.get_trending_products(market="us")
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("FAST_MOSS_API_KEY", "")
        self._available = bool(self.api_key) and self.api_key != "${FAST_MOSS_API_KEY}"

        if not self._available:
            logger = logging.getLogger(__name__)
            logger.warning(
                "FastMoss 没有公开的 REST API，已降级跳过。"
                "如需对接请联系 FastMoss 商务团队。"
            )

        self._client = httpx.AsyncClient(
            base_url=f"{BASE_URL}/{API_VERSION}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            timeout=TIMEOUT,
        )

    async def close(self):
        await self._client.aclose()

    # ──────────────────────────────────────────────
    # 公开接口
    # ──────────────────────────────────────────────

    async def get_trending_products(
        self,
        market: str = "us",
        page: int = 1,
        page_size: int = 50,
        days: int = 7,
    ) -> list[ProductInsight]:
        """
        获取 FastMoss 趋势商品列表

        Args:
            market: 国家代码 (us/uk/jp/...)
            page: 页码 (从1开始)
            page_size: 每页数量 (最大 50)
            days: 数据回溯天数 (7/14/30)
        """
        if not self._available:
            return []
        params = {
            "market": market.upper(),
            "page": page,
            "pageSize": page_size,
            "days": days,
        }
        data = await self._get("/product/list", params=params)
        return self._parse_products(data, source="fastmoss", market_str=market)

    async def get_product_detail(self, product_id: str) -> Optional[ProductInsight]:
        """获取单个商品详情"""
        if not self._available:
            return None
        data = await self._get(f"/product/{product_id}")
        if not data:
            return None
        return self._parse_single_product(data)

    async def search_products(
        self,
        keyword: str,
        market: str = "us",
        page: int = 1,
        page_size: int = 20,
    ) -> list[ProductInsight]:
        """按关键词搜索商品"""
        if not self._available:
            return []
        params = {
            "keyword": keyword,
            "market": market.upper(),
            "page": page,
            "pageSize": page_size,
        }
        data = await self._get("/product/search", params=params)
        return self._parse_products(data, source="fastmoss", market_str=market)

    async def get_product_reviews(
        self,
        product_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        """获取商品评论"""
        if not self._available:
            return []
        params = {"productId": product_id, "page": page, "pageSize": page_size}
        data = await self._get("/product/review", params=params)
        return data.get("data", {}).get("items", [])

    # ──────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _get(self, path: str, params: Optional[dict] = None) -> dict[str, Any]:
        """带重试的 GET 请求"""
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        body = resp.json()

        if not body.get("success", True):
            raise RuntimeError(
                f"FastMoss API 返回错误: {body.get('msg', 'unknown')}"
            )
        return body

    def _parse_products(
        self,
        raw: dict,
        source: str,
        market_str: str,
    ) -> list[ProductInsight]:
        """解析商品列表"""
        market = _MARKET_MAP.get(market_str.upper(), Market.US)
        items = raw.get("data", {}).get("items", [])
        results = []

        for item in items:
            try:
                results.append(self._item_to_insight(item, source, market))
            except Exception as exc:
                # 单条解析失败不影响其他
                import logging
                logging.getLogger(__name__).warning(
                    "跳过解析失败的商品 %s: %s", item.get("id"), exc
                )

        return results

    def _parse_single_product(self, raw: dict) -> Optional[ProductInsight]:
        """解析单个商品详情"""
        item = raw.get("data", {})
        if not item:
            return None
        market_str = item.get("market", "us")
        market = _MARKET_MAP.get(market_str.upper(), Market.US)
        return self._item_to_insight(item, "fastmoss", market)

    @staticmethod
    def _item_to_insight(
        item: dict,
        source: str,
        market: Market,
    ) -> ProductInsight:
        """FastMoss API JSON → ProductInsight"""
        # FastMoss 返回字段映射
        price = float(item.get("price", 0) or 0)
        sales = int(item.get("sales", 0) or 0)
        sales_7d = int(item.get("sales7d", 0) or 0)
        sales_30d = int(item.get("sales30d", 0) or 0)
        growth_7d = (sales_7d / max(sales - sales_7d, 1)) * 100 if sales > 0 else 0.0

        likes = int(item.get("likes", 0) or 0)
        comments = int(item.get("comments", 0) or 0)
        shares = int(item.get("shares", 0) or 0)
        total_engagement = likes + comments + shares
        views = int(item.get("views", 1) or 1)
        engagement_rate = total_engagement / max(views, 1)

        return ProductInsight(
            product_id=str(item.get("id", "")),
            title=str(item.get("title", "")),
            price=price,
            sales_volume=sales,
            sales_growth_7d=growth_7d,
            sales_growth_30d=(
                (sales_30d - sales) / max(sales, 1) * 100 if sales_30d > 0 else 0.0
            ),
            revenue_estimate=price * sales,
            seller_count=int(item.get("sellerCount", 0) or 0),
            avg_price=float(item.get("avgPrice", 0) or 0),
            likes=likes,
            comments=comments,
            shares=shares,
            engagement_rate=engagement_rate,
            source=source,
            market=market,
            fetched_at=datetime.now(timezone.utc),
        )


# ──────────────────────────────────────────────
# 便捷同步入口（用于 GitHub Actions）
# ──────────────────────────────────────────────

async def fetch_trending_products(
    markets: list[str],
    api_key: Optional[str] = None,
    days: int = 7,
) -> list[ProductInsight]:
    """
    快捷函数：获取多个市场的趋势商品

    Args:
        markets: 市场代码列表, 如 ["th", "vn", "my"]
        api_key: FastMoss API Key (默认从环境变量读取)
        days: 数据回溯天数

    Returns:
        合并的商品列表（若 API 不可用返回空列表）
    """
    client = FastMossClient(api_key=api_key)
    all_products: list[ProductInsight] = []

    try:
        if not client._available:
            logger = logging.getLogger(__name__)
            logger.info("FastMoss 不可用，跳过（返回空列表供 pipeline 降级）")
            return []

        for market in markets:
            products = await client.get_trending_products(
                market=market, days=days
            )
            all_products.extend(products)
            import asyncio
            await asyncio.sleep(0.5)  # 避免请求过快
    finally:
        await client.close()

    return all_products
