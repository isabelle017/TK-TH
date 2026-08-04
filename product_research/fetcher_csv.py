"""Free, auditable import path for manually exported product research data."""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from product_research import Market, ProductInsight

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "product_id", "title", "market", "price_usd", "sales_volume",
    "sales_growth_7d_pct", "seller_count", "likes", "comments", "shares", "views",
}


def _optional_float(row: dict[str, str], name: str) -> float | None:
    value = (row.get(name) or "").strip()
    return float(value) if value else None


def _optional_int(row: dict[str, str], name: str) -> int | None:
    value = (row.get(name) or "").strip()
    return int(value) if value else None


def _optional_bool(row: dict[str, str], name: str) -> bool:
    return (row.get(name) or "").strip().lower() in {"1", "true", "yes", "y"}


def fetch_products_from_csv(path: str, markets: list[str]) -> list[ProductInsight]:
    """Load normalized data; malformed rows fail loudly instead of creating signals."""
    csv_path = Path(path)
    if not csv_path.exists():
        logger.info("手工数据文件不存在，跳过: %s", csv_path)
        return []

    results: list[ProductInsight] = []
    market_filter = {market.lower() for market in markets}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少必填列: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(reader, start=2):
            market_code = row["market"].strip().lower()
            if market_code not in market_filter:
                continue
            try:
                if not row["product_id"].strip() or not row["title"].strip():
                    raise ValueError("product_id 和 title 不能为空")
                market = Market(market_code)
                views = int(row["views"] or 0)
                likes = int(row["likes"] or 0)
                comments = int(row["comments"] or 0)
                shares = int(row["shares"] or 0)
                results.append(ProductInsight(
                    product_id=row["product_id"].strip(),
                    title=row["title"].strip(),
                    price=float(row["price_usd"]),
                    sales_volume=int(row["sales_volume"]),
                    sales_growth_7d=float(row["sales_growth_7d_pct"]),
                    seller_count=int(row["seller_count"]),
                    avg_price=float(row.get("avg_price_usd") or 0),
                    unit_cost_usd=_optional_float(row, "unit_cost_usd"),
                    outbound_shipping_usd=_optional_float(row, "outbound_shipping_usd"),
                    packaging_usd=_optional_float(row, "packaging_usd"),
                    creator_commission_rate=_optional_float(row, "creator_commission_rate"),
                    platform_fee_rate=_optional_float(row, "platform_fee_rate"),
                    expected_return_rate=_optional_float(row, "expected_return_rate"),
                    expected_cod_share=_optional_float(row, "expected_cod_share"),
                    expected_cod_rejection_rate=_optional_float(
                        row, "expected_cod_rejection_rate"
                    ),
                    content_score=_optional_float(row, "content_score"),
                    compliance_risk=(row.get("compliance_risk") or "unknown").strip().lower(),
                    supplier_moq=_optional_int(row, "supplier_moq"),
                    lead_time_days=_optional_int(row, "lead_time_days"),
                    source_url=(row.get("source_url") or "").strip() or None,
                    category_code=(row.get("category_code") or "").strip().lower(),
                    product_flags=[
                        flag.strip().lower()
                        for flag in (row.get("product_flags") or "").split(";")
                        if flag.strip()
                    ],
                    material_spec=(row.get("material_spec") or "").strip() or None,
                    quality_evidence=_optional_bool(row, "quality_evidence"),
                    weight_kg=_optional_float(row, "weight_kg"),
                    longest_side_cm=_optional_float(row, "longest_side_cm"),
                    likes=likes,
                    comments=comments,
                    shares=shares,
                    engagement_rate=(likes + comments + shares) / max(views, 1),
                    source="manual_csv",
                    market=market,
                    fetched_at=datetime.now(timezone.utc),
                ))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"CSV 第 {row_number} 行无效: {exc}") from exc

    return results
