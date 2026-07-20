"""
存储层 - SQLite / PostgreSQL 数据持久化

使用 SQLAlchemy ORM，支持 SQLite 和 PostgreSQL 切换。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from product_research import ProductInsight, TrendScore

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# ORM 模型
# ──────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class ProductRecord(Base):
    """商品记录表"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String(128), nullable=False, index=True)
    title = Column(Text, nullable=False)
    price = Column(Float, default=0.0)
    sales_volume = Column(Integer, default=0)
    sales_growth_7d = Column(Float, default=0.0)
    seller_count = Column(Integer, default=0)
    engagement_rate = Column(Float, default=0.0)
    source = Column(String(32), nullable=False)
    market = Column(String(8), nullable=False, index=True)
    trend_score = Column(Float, default=0.0)
    trend_direction = Column(String(16), default="stable")
    fetched_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class CODRecord(Base):
    """COD (货到付款) 记录表 - SEA 市场专属"""
    __tablename__ = "cod_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(128), nullable=False, index=True)
    product_id = Column(String(128), nullable=False)
    market = Column(String(8), nullable=False, index=True)
    amount = Column(Float, default=0.0)
    status = Column(String(16), default="pending")
    customer_phone = Column(String(32), nullable=True)
    confirmation_sent = Column(Integer, default=0)
    last_confirmation_at = Column(DateTime, nullable=True)
    rejection_reason = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime, nullable=True)


class AnalysisLog(Base):
    """分析日志表 - 记录每次抓取分析的结果概要"""
    __tablename__ = "analysis_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(32), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    market = Column(String(8), nullable=False)
    product_count = Column(Integer, default=0)
    top_score = Column(Float, default=0.0)
    hot_count = Column(Integer, default=0)
    trending_count = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    ran_at = Column(DateTime, default=datetime.utcnow)


# ──────────────────────────────────────────────
# 存储管理器
# ──────────────────────────────────────────────

class Storage:
    """
    数据持久化管理器

    使用示例:
        storage = Storage("sqlite:///data/tk_products.db")
        storage.save_products(products)
        storage.save_scores(scores)
        top = storage.get_top_products(market="us", limit=10)
    """

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        logger.info("数据库初始化完成: %s", db_url)

    def save_products(
        self,
        products: list[ProductInsight],
        scores: Optional[list[TrendScore]] = None,
    ) -> int:
        """
        批量保存商品数据

        Args:
            products: 商品列表
            scores: 对应的评分列表 (长度应与 products 一致)

        Returns:
            写入条数
        """
        score_map = {}
        if scores:
            score_map = {s.product_id: s for s in scores}

        saved = 0
        with self.Session() as session:
            for product in products:
                score = score_map.get(product.product_id)
                record = ProductRecord(
                    product_id=product.product_id,
                    title=product.title,
                    price=product.price,
                    sales_volume=product.sales_volume,
                    sales_growth_7d=product.sales_growth_7d,
                    seller_count=product.seller_count,
                    engagement_rate=product.engagement_rate,
                    source=product.source,
                    market=product.market.value,
                    trend_score=score.score if score else 0.0,
                    trend_direction=score.direction.value if score else "stable",
                    fetched_at=product.fetched_at,
                )
                session.add(record)
                saved += 1

            session.commit()

        logger.info("已保存 %d 条商品记录", saved)
        return saved

    def log_analysis(
        self,
        run_id: str,
        source: str,
        market: str,
        product_count: int,
        top_score: float,
        hot_count: int,
        trending_count: int,
        errors: int = 0,
    ):
        """记录分析日志"""
        with self.Session() as session:
            log = AnalysisLog(
                run_id=run_id,
                source=source,
                market=market,
                product_count=product_count,
                top_score=top_score,
                hot_count=hot_count,
                trending_count=trending_count,
                errors=errors,
            )
            session.add(log)
            session.commit()

    def save_cod_record(self, cod: "CODRecord") -> int:
        """保存 COD 记录 (SEA)"""
        with self.Session() as session:
            session.add(cod)
            session.commit()
            return cod.id

    def update_cod_status(
        self,
        order_id: str,
        status: str,
        rejection_reason: Optional[str] = None,
    ) -> bool:
        """更新 COD 状态"""
        with self.Session() as session:
            record = session.query(CODRecord).filter(
                CODRecord.order_id == order_id
            ).first()
            if not record:
                return False
            record.status = status
            if rejection_reason:
                record.rejection_reason = rejection_reason
            session.commit()
            return True

    def get_top_products(
        self,
        market: Optional[str] = None,
        min_score: float = 70.0,
        limit: int = 20,
    ) -> list[ProductRecord]:
        """
        获取最高评分的商品

        Args:
            market: 市场过滤 (None = 全部)
            min_score: 最低评分
            limit: 返回数量

        Returns:
            ProductRecord 列表
        """
        with self.Session() as session:
            query = session.query(ProductRecord).filter(
                ProductRecord.trend_score >= min_score
            )
            if market:
                query = query.filter(ProductRecord.market == market)

            results = (
                query
                .order_by(ProductRecord.trend_score.desc())
                .limit(limit)
                .all()
            )
            return results

    def close(self):
        self.engine.dispose()


# ──────────────────────────────────────────────
# 工厂函数
# ──────────────────────────────────────────────

def create_storage(config: dict) -> Storage:
    """
    根据配置创建 Storage 实例

    Args:
        config: 从 config.yaml 读取的 storage 配置

    Returns:
        Storage 实例
    """
    storage_type = config.get("type", "sqlite")

    if storage_type == "postgresql":
        db_url = config.get("postgres_url", "")
        if not db_url:
            raise ValueError("PostgreSQL 模式需要提供 postgres_url")
    else:
        sqlite_path = config.get("sqlite_path", "data/tk_products.db")
        # 确保目录存在
        db_dir = os.path.dirname(sqlite_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        db_url = f"sqlite:///{os.path.abspath(sqlite_path)}"

    return Storage(db_url)
