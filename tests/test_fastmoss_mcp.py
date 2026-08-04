import json
import os
import unittest
from unittest.mock import patch

import httpx

from product_research import Market
from product_research.fetcher_fastmoss_mcp import (
    FastMossMCPError,
    _is_placeholder_listing,
    fetch_fastmoss_mcp_products,
    item_to_product,
)


class FastMossMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_skill_first_and_nested_products_are_normalized(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/mcp")
            payload = json.loads(request.content)
            calls.append(payload)
            method = payload["method"]
            headers = {"content-type": "application/json", "mcp-session-id": "session-1"}
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}
            elif method == "tools/list":
                result = {"tools": [
                    {
                        "name": "skill",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    },
                    {
                        "name": "product_search",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "filter": {"type": "object"},
                                "orderby": {"type": "array"},
                                "page": {"type": "integer"},
                                "pagesize": {"type": "integer"},
                            },
                        },
                    },
                ]}
            elif payload["params"]["name"] == "skill":
                result = {"content": [{"type": "text", "text": "selection guidance"}]}
            else:
                category_path = payload["params"]["arguments"]["filter"]["category_path"]
                if category_path[-1] == 600621:
                    row = {
                        "distribution_summary": {"linked_creator_count": 12},
                        "product": {
                            "product_id": "home-1",
                            "title": "Storage organizer",
                            "floor_price": 350,
                            "currency_code": "THB",
                            "commission_rate_percent": 10,
                            "category": {
                                "l1": {"name": "Home Supplies"},
                                "l2": {"name": "Home Organizers"},
                                "l3": {"name": "Storage Boxes & Bins"},
                            },
                        },
                        "sales_summary": {
                            "last_7d_units_sold": 700,
                            "last_28d_units_sold": 1300,
                            "last_28d_gmv": 455000,
                            "total_units_sold": 2000,
                        },
                    }
                else:
                    row = {
                        "distribution_summary": {"linked_creator_count": 8},
                        "product": {
                            "product_id": "jewelry-1",
                            "title": "Minimal necklace",
                            "floor_price": 9.9,
                            "currency_code": "USD",
                            "category": {"l2": {"name": "Costume Jewelry"}},
                        },
                        "sales_summary": {
                            "last_7d_units_sold": 140,
                            "last_28d_units_sold": 370,
                            "total_units_sold": 700,
                        },
                    }
                result = {"content": [{"type": "text", "text": json.dumps({"list": [row]})}]}
            return httpx.Response(
                200,
                headers=headers,
                json={"jsonrpc": "2.0", "id": payload.get("id"), "result": result},
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="https://mcp.fastmoss.com/mcp", transport=transport
        ) as client:
            with patch.dict(os.environ, {"FASTMOSS_MCP_KEY": "fm_sk_test_only"}):
                products = await fetch_fastmoss_mcp_products(
                    ["th"],
                    {"results_per_category": 3, "retries": 1, "thb_to_usd": 0.028},
                    client=client,
                )

        self.assertEqual([call["method"] for call in calls[:3]], [
            "initialize", "tools/list", "tools/call"
        ])
        self.assertEqual(calls[2]["params"]["name"], "skill")
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].category_code, "home_daily")
        self.assertAlmostEqual(products[0].price, 9.8)
        self.assertAlmostEqual(products[0].revenue_estimate, 12740)
        self.assertEqual(products[0].creator_commission_rate, 0.10)
        self.assertEqual(products[0].seller_count, 12)
        self.assertEqual(products[1].category_code, "affordable_jewelry")
        self.assertTrue(all(product.market == Market.TH for product in products))

    async def test_server_error_does_not_expose_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="https://mcp.fastmoss.com/mcp", transport=transport
        ) as client:
            with patch.dict(os.environ, {"FASTMOSS_MCP_KEY": "fm_sk_private_value"}):
                with self.assertRaises(FastMossMCPError) as caught:
                    await fetch_fastmoss_mcp_products(
                        ["th"], {"retries": 1}, client=client
                    )
        self.assertNotIn("fm_sk_private_value", str(caught.exception))
        self.assertIn("HTTP 500", str(caught.exception))

    def test_unknown_currency_is_rejected(self):
        with self.assertRaises(FastMossMCPError):
            item_to_product(
                {"product_id": "p1", "title": "x", "price": 10, "currency": "EUR"},
                Market.TH,
                "home_daily",
                0.028,
            )

    def test_placeholder_and_promotion_rows_are_filtered(self):
        self.assertTrue(_is_placeholder_listing("Home Supplies กรุณาอย่าทำการสั่งซื้อ"))
        self.assertTrue(_is_placeholder_listing("GWP สินค้ากิจกรรมเท่านั้น"))
        self.assertTrue(_is_placeholder_listing("นี่คือของขวัญฟรีสำหรับคุณ"))
        self.assertFalse(_is_placeholder_listing("กล่องเก็บเสื้อผ้าขนาดใหญ่"))


if __name__ == "__main__":
    unittest.main()
