"""FastMoss official MCP integration for store-independent product research."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from product_research import Market, ProductInsight
from product_research.fetcher_fastmoss_export import _category_code

logger = logging.getLogger(__name__)
BASE_URL = "https://mcp.fastmoss.com/mcp"
PROTOCOL_VERSION = "2025-03-26"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FastMossMCPError(RuntimeError):
    pass


def _number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def _first(item: dict, *names: str, default: Any = None) -> Any:
    for name in names:
        if item.get(name) not in (None, ""):
            return item[name]
    return default


def _json_from_response(response: httpx.Response) -> dict:
    content_type = response.headers.get("content-type", "").lower()
    if "text/event-stream" not in content_type:
        try:
            return response.json()
        except ValueError as exc:
            raise FastMossMCPError("FastMoss MCP 返回非 JSON") from exc
    for line in response.text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    raise FastMossMCPError("FastMoss MCP 事件流中没有 JSON 数据")


def _extract_rows(result: dict) -> list[dict]:
    structured = result.get("structuredContent") or result.get("structured_content")
    candidates: list[Any] = [structured] if structured is not None else []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        if isinstance(block.get("json"), (dict, list)):
            candidates.append(block["json"])
        text = block.get("text")
        if isinstance(text, str):
            try:
                candidates.append(json.loads(text))
            except json.JSONDecodeError:
                match = re.search(r"(?:\[|\{)[\s\S]*(?:\]|\})", text)
                if match:
                    try:
                        candidates.append(json.loads(match.group(0)))
                    except json.JSONDecodeError:
                        pass

    def find_rows(value: Any) -> list[dict]:
        if isinstance(value, list) and all(isinstance(row, dict) for row in value):
            return value
        if isinstance(value, dict):
            for key in ("list", "items", "products", "goods", "rows", "data", "result"):
                rows = find_rows(value.get(key))
                if rows:
                    return rows
        return []

    for candidate in candidates:
        rows = find_rows(candidate)
        if rows:
            return rows
    raise FastMossMCPError("FastMoss MCP 商品工具未返回可解析的结构化列表")


def _price_usd(item: dict, thb_to_usd: float) -> float:
    price = _number(_first(
        item, "floor_price", "real_price", "price", "sale_price", "avg_price", "product_price"
    ))
    currency = str(_first(item, "currency", "currency_code", default="USD")).upper()
    if currency == "USD":
        return price
    if currency == "THB":
        return price * thb_to_usd
    raise FastMossMCPError(f"FastMoss MCP 返回不支持的价格币种: {currency}")


def _growth_from_windows(day7: float, day28: float) -> float:
    previous_weekly = max(0.0, day28 - day7) / 21 * 7
    if previous_weekly <= 0:
        return 100.0 if day7 > 0 else 0.0
    return (day7 / previous_weekly - 1) * 100


def _product_flags(title: str) -> list[str]:
    lowered = title.lower()
    flags = []
    if any(term in lowered for term in ("natural jade", "natural gem", "หยกธรรมชาติ")):
        flags.append("natural_gem_claim")
    if re.search(r"\b(?:1[5-9][0-9]|[2-9][0-9]{2,})\s*(?:l|liters?)\b", lowered) or re.search(
        r"(?:1[5-9][0-9]|[2-9][0-9]{2,})\s*ลิตร", lowered
    ):
        flags.append("oversized")
    return flags


def _is_placeholder_listing(title: str) -> bool:
    lowered = title.lower()
    if lowered.count("บรรจุ") >= 3:
        return True
    return any(term in lowered for term in (
        "do not order",
        "please do not purchase",
        "after-sales card",
        "กรุณาอย่าทำการสั่งซื้อ",
        "สินค้ากิจกรรมเท่านั้น",
        "ของขวัญฟรีสำหรับคุณ",
        "ของแถมฟรี",
        "บรรจุถุงขนส่ง",
        "请勿下单",
        "不要下单",
        "活动专用",
        "赠品勿拍",
    ))


def item_to_product(
    item: dict,
    market: Market,
    category_hint: str,
    thb_to_usd: float,
) -> ProductInsight:
    product_data = item.get("product") if isinstance(item.get("product"), dict) else item
    sales = item.get("sales_summary") if isinstance(item.get("sales_summary"), dict) else item
    distribution = (
        item.get("distribution_summary")
        if isinstance(item.get("distribution_summary"), dict)
        else item
    )
    product_id = str(_first(
        product_data, "product_id", "goods_id", "id", "productId", default=""
    )).strip()
    title = str(_first(
        product_data, "title", "product_name", "goods_name", "name", default=""
    )).strip()
    price = _price_usd(product_data, thb_to_usd)
    if not product_id or not title or price <= 0:
        raise FastMossMCPError("FastMoss MCP 商品缺少 ID、标题或有效价格")
    category_data = product_data.get("category")
    if isinstance(category_data, dict):
        category = " / ".join(
            str(level.get("name", ""))
            for level in category_data.values()
            if isinstance(level, dict) and level.get("name")
        )
    else:
        category = str(_first(
            product_data, "category_name", "category", "category_path", "leaf_category", default=""
        ))
    category_code = _category_code(category, title) or category_hint
    day7_units = _number(_first(sales, "last_7d_units_sold", "day7_sold_count"))
    day28_units = _number(_first(sales, "last_28d_units_sold", "day28_sold_count"))
    explicit_growth = _first(
        sales, "sold_count_inc_rate", "sales_growth_7d", "growth_rate", "growth_7d"
    )
    growth = (
        _number(explicit_growth)
        if explicit_growth not in (None, "")
        else _growth_from_windows(day7_units, day28_units)
    )
    day28_gmv = _number(_first(sales, "last_28d_gmv", "day28_sale_amount"))
    currency = str(_first(product_data, "currency", "currency_code", default="USD")).upper()
    revenue_usd = day28_gmv * thb_to_usd if currency == "THB" else day28_gmv
    commission = _number(_first(product_data, "commission_rate_percent", "commission_rate"))
    return ProductInsight(
        product_id=product_id,
        title=title,
        price=price,
        sales_volume=int(_number(_first(
            sales, "total_units_sold", "total_sold_count", "sold_count", "sales", "sales_volume", "units_sold"
        ))),
        sales_growth_7d=growth,
        revenue_estimate=revenue_usd or None,
        seller_count=int(_number(_first(
            distribution, "linked_creator_count", "total_creator_count", "creator_count", "seller_count"
        ))),
        avg_price=price,
        creator_commission_rate=(commission / 100 if commission > 1 else commission),
        source="fastmoss_mcp",
        market=market,
        category_code=category_code,
        source_url=str(_first(
            product_data, "fastmoss_detail_url", "detail_url", "tiktok_product_url", "product_url", "url", default=""
        )).strip() or None,
        product_flags=_product_flags(title),
        fetched_at=datetime.now(timezone.utc),
    )


def _tool_arguments(tool: dict, query: dict, market: str, limit: int) -> dict:
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    if "filter" not in properties:
        raise FastMossMCPError("FastMoss MCP product_search 缺少 filter 参数")
    filters: dict[str, Any] = {"region": market.upper()}
    if query.get("category_path"):
        filters["category_path"] = query["category_path"]
    if query.get("min_price_local") is not None or query.get("max_price_local") is not None:
        filters["floor_price_range"] = {
            "min": query.get("min_price_local", 0),
            "max": query.get("max_price_local"),
        }
        if filters["floor_price_range"]["max"] is None:
            del filters["floor_price_range"]["max"]
    arguments: dict[str, Any] = {
        "filter": filters,
        "orderby": [{"field": "day7_units_sold", "order": "desc"}],
        "page": 1,
        "pagesize": limit,
    }
    if query.get("keywords"):
        arguments["keywords"] = query["keywords"]
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise FastMossMCPError(
            f"FastMoss MCP 工具 {tool.get('name')} 出现未识别的必填参数: {', '.join(missing)}"
        )
    return arguments


def _skill_arguments(tool: dict) -> dict:
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    for name in ("name", "skill", "skill_name", "id"):
        if name in properties:
            return {name: "fm-agent-skills"}
    if schema.get("required"):
        raise FastMossMCPError("FastMoss MCP 的 skill 工具参数格式无法识别")
    return {}


class _MCPClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        api_key: str,
        retries: int,
    ) -> None:
        self.client = client
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.retries = max(1, retries)
        self.session_id: str | None = None
        self.request_id = 0

    async def request(self, method: str, params: dict | None = None) -> dict:
        self.request_id += 1
        payload = {"jsonrpc": "2.0", "id": self.request_id, "method": method}
        if params is not None:
            payload["params"] = params
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        response: httpx.Response | None = None
        for attempt in range(self.retries):
            try:
                response = await self.client.post(self.endpoint, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                if attempt + 1 >= self.retries:
                    raise FastMossMCPError("FastMoss MCP 网络连接失败") from exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code not in RETRYABLE_STATUS or attempt + 1 >= self.retries:
                break
            await asyncio.sleep(0.5 * (attempt + 1))
        assert response is not None
        if response.status_code in (401, 403):
            raise FastMossMCPError("FastMoss MCP Key 无效、已过期或试用未激活")
        if response.status_code >= 400:
            raise FastMossMCPError(f"FastMoss MCP 服务不可用: HTTP {response.status_code}")
        self.session_id = response.headers.get("mcp-session-id", self.session_id)
        body = _json_from_response(response)
        if body.get("error"):
            error = body["error"]
            message = str(error.get("message", "unknown error")).replace(
                self.api_key, "[REDACTED]"
            )
            message = re.sub(r"fm_sk_[A-Za-z0-9_-]+", "[REDACTED]", message)
            raise FastMossMCPError(f"FastMoss MCP 调用失败: {message}")
        return body.get("result") or {}

    async def initialize(self) -> None:
        await self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "TK-TH-workflow", "version": "1.0.0"},
        })

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self.request("tools/call", {"name": name, "arguments": arguments})


async def fetch_fastmoss_mcp_products(
    markets: list[str],
    config: dict,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ProductInsight]:
    api_key = os.getenv("FASTMOSS_MCP_KEY", "").strip()
    if not api_key:
        raise FastMossMCPError("缺少 FASTMOSS_MCP_KEY")
    if any(market.lower() != "th" for market in markets):
        raise FastMossMCPError("当前 FastMoss MCP 选品配置只允许泰国市场")
    queries = config.get("queries") or [
        {
            "category_code": "home_daily",
            "category_path": [10, 851848, 600621],
            "min_price_local": 286,
            "max_price_local": 893,
        },
        {
            "category_code": "affordable_jewelry",
            "category_path": [8, 905608],
            "min_price_local": 215,
            "max_price_local": 714,
        },
    ]
    limit = min(20, max(1, int(config.get("results_per_category", 10))))
    thb_to_usd = float(config.get("thb_to_usd", 0.028))
    retries = min(5, max(1, int(config.get("retries", 3))))
    owns_client = client is None
    endpoint = str(config.get("base_url", BASE_URL)).rstrip("/")
    http_client = client or httpx.AsyncClient(timeout=30.0)
    transport = _MCPClient(http_client, endpoint, api_key, retries)
    try:
        await transport.initialize()
        tools_result = await transport.request("tools/list", {})
        tools = tools_result.get("tools") or []
        skill_tool = next((tool for tool in tools if tool.get("name") == "skill"), None)
        if skill_tool:
            await transport.call_tool("skill", _skill_arguments(skill_tool))
        search_tool = next((tool for tool in tools if tool.get("name") == "product_search"), None)
        if not search_tool:
            raise FastMossMCPError("FastMoss MCP 未提供 product_search 工具")

        products: list[ProductInsight] = []
        seen: set[str] = set()
        failed_queries = 0
        for query in queries:
            try:
                result = await transport.call_tool(
                    "product_search",
                    _tool_arguments(search_tool, query, markets[0], limit),
                )
                if result.get("isError"):
                    raise FastMossMCPError("FastMoss MCP 商品查询后端暂时不可用")
                rows = _extract_rows(result)
            except FastMossMCPError as exc:
                failed_queries += 1
                logger.warning("FastMoss MCP 跳过查询 %s: %s", query.get("category_code"), exc)
                continue
            for item in rows:
                try:
                    nested_product = item.get("product") if isinstance(item.get("product"), dict) else item
                    title = str(nested_product.get("title", ""))
                    if _is_placeholder_listing(title):
                        logger.warning("跳过 FastMoss MCP 占位/请勿下单商品")
                        continue
                    product = item_to_product(
                        item, Market.TH, str(query["category_code"]), thb_to_usd
                    )
                except FastMossMCPError as exc:
                    logger.warning("跳过 FastMoss MCP 无效商品: %s", exc)
                    continue
                if product.product_id not in seen:
                    products.append(product)
                    seen.add(product.product_id)
        if failed_queries == len(queries):
            raise FastMossMCPError("FastMoss MCP 所有商品查询均失败")
        logger.info("FastMoss MCP 获取到 %d 条泰国商品", len(products))
        return products
    finally:
        if owns_client:
            await http_client.aclose()
