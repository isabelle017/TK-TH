"""Import FastMoss member exports without scraping the authenticated website."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from product_research import Market, ProductInsight

logger = logging.getLogger(__name__)

ALIASES = {
    "product_id": ["productid", "product_id", "商品id", "商品编号"],
    "title": ["productname", "product_name", "商品名称", "商品名", "标题"],
    "price": ["priceusd", "price", "spuavgprice", "商品价格", "价格", "sku均价"],
    "sales": ["totalsales", "sales", "totalsalecnt", "总销量", "累计销量", "销量"],
    "sales_7d": ["sales7d", "7daysales", "totalsale7dcnt", "近7天销量", "7日销量"],
    "sales_30d": ["sales30d", "30daysales", "totalsale30dcnt", "近30天销量", "30日销量"],
    "growth_7d": ["salesgrowth7d", "7daygrowth", "7日增长率", "近7天销量增长率"],
    "creator_count": ["creatorcount", "influencercount", "totaliflcnt", "带货达人数", "达人数"],
    "reviews": ["reviewcount", "reviews", "评论数", "评价数"],
    "views": ["views", "totalviewscnt", "播放量", "总播放量"],
    "category": ["category", "categoryname", "类目", "商品类目", "三级类目"],
    "source_url": ["producturl", "url", "商品链接", "商品地址"],
}


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value).strip().lower())


def _find_column(columns: list[str], field: str) -> str | None:
    normalized = {_normalize(column): column for column in columns}
    for alias in ALIASES[field]:
        if _normalize(alias) in normalized:
            return normalized[_normalize(alias)]
    return None


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return default


def _category_code(category: str, filename: str) -> str:
    value = f"{category} {filename}".lower()
    jewelry_words = ("jewelry", "jewellery", "necklace", "earring", "bracelet", "ring", "首饰", "饰品", "项链", "耳饰", "手链", "戒指")
    home_words = ("home", "household", "storage", "cleaning", "kitchen", "家居", "日用", "收纳", "清洁", "厨房")
    if any(word in value for word in jewelry_words):
        return "affordable_jewelry"
    if any(word in value for word in home_words):
        return "home_daily"
    return ""


def _growth(row: pd.Series, columns: dict[str, str | None]) -> float:
    if columns["growth_7d"]:
        return _number(row[columns["growth_7d"]])
    recent_7d = _number(row[columns["sales_7d"]]) if columns["sales_7d"] else 0
    recent_30d = _number(row[columns["sales_30d"]]) if columns["sales_30d"] else 0
    previous_weekly = max(0.0, recent_30d - recent_7d) / 23 * 7
    if previous_weekly <= 0:
        return 100.0 if recent_7d > 0 else 0.0
    return (recent_7d / previous_weekly - 1) * 100


def _read_frames(path: Path) -> list[pd.DataFrame]:
    if path.suffix.lower() == ".csv":
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return [pd.read_csv(path, encoding=encoding)]
            except UnicodeDecodeError:
                continue
        raise ValueError(f"无法识别 CSV 编码: {path.name}")
    return [frame for frame in pd.read_excel(path, sheet_name=None).values()]


def fetch_fastmoss_exports(config: dict, markets: list[str]) -> list[ProductInsight]:
    directory = Path(config.get("directory", str(Path.home() / "Downloads")))
    if not directory.exists():
        logger.info("FastMoss 导出目录不存在: %s", directory)
        return []
    currency = str(config.get("price_currency", "USD")).upper()
    if currency != "USD":
        raise ValueError("请先在 FastMoss 将导出币种设置为 USD；系统不会猜测汇率")
    keywords = [word.lower() for word in config.get("filename_keywords", ["fastmoss"])]
    files = sorted(
        (
            path for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".csv", ".xlsx"}
            and any(word in path.name.lower() for word in keywords)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        logger.info("下载目录中没有找到 FastMoss 导出文件: %s", directory)
        return []

    results: list[ProductInsight] = []
    market = Market(markets[0].lower())
    for path in files:
        for frame in _read_frames(path):
            frame.columns = [str(column).strip() for column in frame.columns]
            columns = {field: _find_column(list(frame.columns), field) for field in ALIASES}
            missing = [field for field in ("product_id", "title", "price", "sales") if not columns[field]]
            if missing:
                logger.warning("跳过 %s 的工作表，缺少字段: %s", path.name, ", ".join(missing))
                continue
            for _, row in frame.iterrows():
                product_id = str(row[columns["product_id"]]).strip()
                title = str(row[columns["title"]]).strip()
                price = _number(row[columns["price"]])
                if not product_id or product_id.lower() == "nan" or not title or price <= 0:
                    continue
                category = str(row[columns["category"]]) if columns["category"] else ""
                views = int(_number(row[columns["views"]])) if columns["views"] else 0
                reviews = int(_number(row[columns["reviews"]])) if columns["reviews"] else 0
                results.append(ProductInsight(
                    product_id=product_id,
                    title=title,
                    price=price,
                    sales_volume=int(_number(row[columns["sales"]])),
                    sales_growth_7d=_growth(row, columns),
                    seller_count=int(_number(row[columns["creator_count"]])) if columns["creator_count"] else 0,
                    comments=reviews,
                    engagement_rate=reviews / max(views, 1),
                    source="fastmoss_export",
                    market=market,
                    category_code=_category_code(category, path.name),
                    source_url=str(row[columns["source_url"]]).strip() if columns["source_url"] else None,
                    fetched_at=datetime.now(timezone.utc),
                ))
    logger.info("从 %d 个 FastMoss 导出文件读取 %d 条商品", len(files), len(results))
    return results
