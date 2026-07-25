"""
EchoTik 数据抓取

EchoTik 目前没有公开的 REST API，有两种获取方式：
1. Playwright 无头浏览器 + Cookie（推荐，更稳定）
2. 直接 HTTP 请求模拟（需要 Cookie）

使用本模块前：
1. 在浏览器中登录 EchoTik (https://www.echotik.com)
2. 从开发者工具 → Application → Cookies 中复制完整 Cookie
3. 设置环境变量 ECHO_TIK_COOKIE

本模块默认关闭（config.yaml -> sources.echotik.enabled: false）
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

from product_research import Market, ProductInsight

logger = logging.getLogger(__name__)

BASE_URL = "https://www.echotik.com"

# EchoTik 国家映射
_MARKET_MAP: dict[str, Market] = {
    "US": Market.US, "UK": Market.UK, "JP": Market.JP,
    "ID": Market.ID, "TH": Market.TH, "VN": Market.VN,
    "PH": Market.PH, "SG": Market.SG, "MY": Market.MY, "SA": Market.SA,
    "BR": Market.BR, "MX": Market.MX,
}

# HTTP 请求头（模拟移动端浏览器）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}


class EchoTikClient:
    """
    EchoTik 数据客户端 (HTTP 模式)

    注意：EchoTik 可能会频繁更新其 API 端点，如遇问题
    请检查 EchoTik 网站的网络请求，更新 _API_ENDPOINTS。
    """

    def __init__(self, cookie: Optional[str] = None):
        self.cookie = cookie or os.getenv("ECHO_TIK_COOKIE", "")
        if not self.cookie or self.cookie == "${ECHO_TIK_COOKIE}":
            raise ValueError(
                "缺少 EchoTik Cookie。"
                "请从浏览器登录后复制 Cookie 并设置 ECHO_TIK_COOKIE 环境变量。"
            )

        self._session: Optional[Any] = None  # httpx.AsyncClient
        self._use_playwright = False

    async def _ensure_session(self):
        """惰性初始化 HTTP 会话"""
        if self._session is not None:
            return
        import httpx
        self._session = httpx.AsyncClient(
            headers={**_HEADERS, "Cookie": self.cookie},
            timeout=30.0,
            follow_redirects=True,
        )

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None

    async def get_trending_products(
        self,
        market: str = "us",
        page: int = 1,
        days: int = 7,
    ) -> list[ProductInsight]:
        """
        获取 EchoTik 趋势商品

        EchoTik 前端可能使用 GraphQL 或 REST，以下尝试几个已知端点。
        """
        await self._ensure_session()

        # 尝试策略 1: REST 接口
        products = await self._try_rest_api(market, page, days)
        if products:
            return products

        # 尝试策略 2: 从 HTML 页面中提取
        products = await self._try_html_scrape(market)
        if products:
            return products

        logger.warning("EchoTik 所有抓取策略均失败，返回空列表")
        return []

    async def _try_rest_api(
        self, market: str, page: int, days: int
    ) -> Optional[list[ProductInsight]]:
        """尝试 EchoTik REST API"""
        candidates = [
            f"{BASE_URL}/api/product/trending",
            f"{BASE_URL}/api/v1/products",
            f"{BASE_URL}/api/top/products",
        ]

        params = {
            "market": market.upper(),
            "page": page,
            "pageSize": 20,
            "days": days,
        }

        for url in candidates:
            try:
                resp = await self._session.get(url, params=params)  # type: ignore
                if resp.status_code != 200:
                    continue

                data = resp.json()
                items = self._extract_items_from_echotik(data)
                if items:
                    logger.info("EchoTik REST API 成功: %s", url)
                    return items
            except Exception as exc:
                logger.debug("EchoTik REST 端点 %s 失败: %s", url, exc)

        return None

    async def _try_html_scrape(self, market: str) -> Optional[list[ProductInsight]]:
        """从 EchoTik HTML 页面提取数据（后备方案）"""
        url = f"{BASE_URL}/top-products?market={market.upper()}"
        try:
            resp = await self._session.get(url)  # type: ignore
            if resp.status_code != 200:
                return None

            text = resp.text

            # 尝试从 <script> 标签中提取 JSON 数据
            # EchoTik 可能使用 Next.js，数据在 __NEXT_DATA__ 或 __INITIAL_STATE__ 中
            patterns = [
                r'__NEXT_DATA__\s*=\s*({.*?});',
                r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                r'__INITIAL_STATE__\s*=\s*({.*?});',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    items = self._extract_items_from_echotik(data)
                    if items:
                        logger.info("EchoTik HTML 提取成功")
                        return items

        except Exception as exc:
            logger.debug("EchoTik HTML 抓取失败: %s", exc)

        return None

    @staticmethod
    def _extract_items_from_echotik(data: dict) -> list[ProductInsight]:
        """
        从 EchoTik 的 JSON 中递归查找商品列表
        EchoTik 的数据结构可能不同，所以做了递归搜索。
        """
        results: list[ProductInsight] = []

        def _find_products(obj: Any):
            if isinstance(obj, dict):
                # 检查是否是商品条目
                if obj.get("id") and obj.get("title"):
                    try:
                        price = float(obj.get("price", 0) or 0)
                        sales = int(obj.get("sales", 0) or 0)
                        likes = int(obj.get("likes", 0) or 0)
                        comments = int(obj.get("comments", 0) or 0)
                        shares = int(obj.get("shares", 0) or 0)
                        views = int(obj.get("views", 1) or 1)
                        engagement = (likes + comments + shares) / max(views, 1)

                        results.append(ProductInsight(
                            product_id=str(obj["id"]),
                            title=str(obj["title"]),
                            price=price,
                            sales_volume=sales,
                            likes=likes,
                            comments=comments,
                            shares=shares,
                            engagement_rate=engagement,
                            source="echotik",
                            market=Market.US,  # 调用方修正
                            fetched_at=datetime.utcnow(),
                        ))
                    except (ValueError, TypeError):
                        pass
                else:
                    for v in obj.values():
                        _find_products(v)
            elif isinstance(obj, list):
                for item in obj:
                    _find_products(item)

        _find_products(data)
        return results


# ──────────────────────────────────────────────
# Playwright 模式（更稳定，但需要安装 playwright）
# ──────────────────────────────────────────────

class EchoTikPlaywrightClient:
    """
    Playwright 无头浏览器抓取（推荐模式）

    安装:
        pip install playwright
        playwright install chromium
    """

    def __init__(self, cookie: Optional[str] = None):
        self.cookie = cookie or os.getenv("ECHO_TIK_COOKIE", "")

    async def get_trending_products(
        self, market: str = "us"
    ) -> list[ProductInsight]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("请安装 playwright: pip install playwright && playwright install chromium")
            return []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=_HEADERS["User-Agent"]
            )

            # 注入 Cookie
            if self.cookie:
                await context.add_cookies([
                    {"name": k, "value": v, "domain": ".echotik.com", "path": "/"}
                    for cookie_part in self.cookie.split("; ")
                    for k, v in [cookie_part.split("=", 1)]
                ])

            page = await context.new_page()
            url = f"{BASE_URL}/top-products?market={market.upper()}"
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(3000)  # 等 JS 渲染

            # 提取页面数据
            content = await page.content()
            await browser.close()

            # 解析
            import re, json
            match = re.search(r'__NEXT_DATA__\s*=\s*({.*?});', content, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                return EchoTikClient._extract_items_from_echotik(data)

            return []
