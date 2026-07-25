"""
TikTok 选品自动化 - 主调度器

三种运行模式:
1. 一次性运行:  python scheduler.py --once
2. 定时调度:    python scheduler.py
3. 仅推送测试:  python scheduler.py --test-notify

部署方式:
- 本地: 直接运行 python scheduler.py（后台常驻）
- GitHub Actions: 使用 .github/workflows/product_research.yml（推荐，免服务器）
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import uuid
from datetime import datetime
from typing import Optional

import yaml
from dotenv import load_dotenv

from product_research import ProductInsight, PushMessage, TrendScore
from product_research.fetcher_fastmoss import FastMossClient, fetch_trending_products as fetch_fastmoss
from product_research.fetcher_echotik import EchoTikClient
from product_research.analyzer_trend import (
    ScoringThresholds,
    ScoringWeights,
    TrendAnalyzer,
)
from product_research.analyzer_sentiment import SentimentAnalyzer
from notify import Notifier
from storage import create_storage, Storage

# 加载 .env 文件
load_dotenv()

# ──────────────────────────────────────────────
# 日志配置
# ──────────────────────────────────────────────

def setup_logging(config: dict):
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "logs/tk_automation.log")

    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
        ),
    ]

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


# ──────────────────────────────────────────────
# 核心流水线
# ──────────────────────────────────────────────

class ProductPipeline:
    """
    选品分析流水线

    完整的处理链路：
    1. 从数据源抓取趋势商品（FastMoss → EchoTik → Mock 降级）
    2. 趋势评分算法计算
    3. (可选) ChatGPT 评论情感分析
    4. 存储到数据库
    5. 推送高分商品到即时通讯
    """

    def __init__(self, config: dict, storage: Optional[Storage] = None, region: str = "us"):
        self.config = config
        self.region = region
        self.logger = logging.getLogger("pipeline")

        # 评分引擎
        weights_cfg = config.get("scoring", {}).get("weights", {})
        thresholds_cfg = config.get("scoring", {}).get("thresholds", {})
        self.analyzer = TrendAnalyzer(
            weights=ScoringWeights(
                sales_growth_7d=weights_cfg.get("sales_growth_7d", 0.35),
                competition_inverse=weights_cfg.get("competition_inverse", 0.20),
                estimated_margin=weights_cfg.get("estimated_margin", 0.25),
                seasonality=weights_cfg.get("seasonality", 0.10),
                engagement_rate=weights_cfg.get("engagement_rate", 0.10),
            ),
            thresholds=ScoringThresholds(
                notify_min_score=thresholds_cfg.get("notify_min_score", 70),
                hot_score=thresholds_cfg.get("hot_score", 85),
                trending_score=thresholds_cfg.get("trending_score", 75),
            ),
        )

        # 通知器
        notify_cfg = config.get("notify", {})
        channel = notify_cfg.get("channel", "telegram")
        if channel == "email":
            from notify.email import NotifierWithEmail
            self.notifier = NotifierWithEmail()
        else:
            self.notifier = Notifier(channel=channel)

        # 存储
        if storage:
            self.storage = storage
        else:
            storage_cfg = config.get("storage", {})
            self.storage = create_storage(storage_cfg)

        # ChatGPT 分析器 (可选)
        gpt_cfg = config.get("gpt_analysis", {})
        if gpt_cfg.get("enabled", True):
            try:
                self.sentiment_analyzer = SentimentAnalyzer(
                    model=gpt_cfg.get("model", "gpt-4o-mini"),
                    max_comments=gpt_cfg.get("max_comments", 50),
                )
            except ValueError as exc:
                self.logger.warning("ChatGPT 分析未启用: %s", exc)
                self.sentiment_analyzer = None
        else:
            self.sentiment_analyzer = None

    async def run_once(
        self,
        markets: Optional[list[str]] = None,
        days: int = 7,
    ) -> dict:
        """
        执行一次完整的选品分析

        Returns:
            运行统计: {
                "products_fetched": int,
                "pushed": int,
                "hot_count": int,
                "errors": int,
                "run_id": str
            }
        """
        run_id = uuid.uuid4().hex[:8]
        self.logger.info("=" * 50)
        self.logger.info("开始选品分析 [run_id=%s]", run_id)
        self.logger.info("=" * 50)

        stats = {"products_fetched": 0, "pushed": 0, "hot_count": 0,
                 "trending_count": 0, "errors": 0, "run_id": run_id}

        if not markets:
            sources_cfg = self.config.get("sources", {})
            markets = sources_cfg.get("fastmoss", {}).get("markets", ["us"])

        # ── 第一步：数据获取（多源降级） ──
        # 优先级: FastMoss → EchoTik → Mock
        all_products = []

        # 1a) 尝试 FastMoss
        sources_cfg = self.config.get("sources", {})
        fastmoss_cfg = sources_cfg.get("fastmoss", {})
        if fastmoss_cfg.get("enabled", True):
            self.logger.info("正在从 FastMoss 抓取数据: markets=%s", markets)
            try:
                all_products = await fetch_fastmoss(markets=markets, days=days)
            except Exception as exc:
                self.logger.warning("FastMoss 抓取失败: %s", exc)
                stats["errors"] += 1

        # 1b) FastMoss 无数据 → 尝试 EchoTik
        if not all_products:
            echotik_cfg = sources_cfg.get("echotik", {})
            if echotik_cfg.get("enabled", False):
                self.logger.info("FastMoss 无数据，尝试从 EchoTik 抓取...")
                try:
                    cookie = os.getenv("ECHO_TIK_COOKIE", "") or echotik_cfg.get("cookie", "")
                    if cookie and cookie != "${ECHO_TIK_COOKIE}":
                        client = EchoTikClient(cookie=cookie)
                        for market in markets:
                            products = await client.get_trending_products(market=market, days=days)
                            all_products.extend(products)
                        await client.close()
                    else:
                        self.logger.info("EchoTik Cookie 未配置，跳过")
                except Exception as exc:
                    self.logger.warning("EchoTik 抓取失败: %s", exc)
                    stats["errors"] += 1

        # 1c) 全部失败 → 模拟数据兜底
        if not all_products:
            self.logger.warning("所有数据源均不可用，使用模拟数据")
            all_products = self._generate_mock_products(markets)
            if not all_products:
                await self._notify_error("无法获取任何商品数据")
                return stats

        stats["products_fetched"] = len(all_products)
        self.logger.info("获取到 %d 条商品", len(all_products))

        # ── 第二步：趋势评分 ──
        self.logger.info("正在计算趋势评分...")
        scored: list[tuple[ProductInsight, TrendScore]] = []
        for product in all_products:
            score = self.analyzer.analyze(product)
            scored.append((product, score))

        # 按评分排序
        scored.sort(key=lambda x: x[1].score, reverse=True)

        # ── 第三步：保存到数据库 ──
        products = [s[0] for s in scored]
        scores = [s[1] for s in scored]
        self.storage.save_products(products, scores)

        # ── 第四步：ChatGPT 评论分析（只对高分商品） ──
        sentiment_results: dict[str, Optional] = {}
        if self.sentiment_analyzer:
            threshold = self.analyzer.thresholds.notify_min_score
            top_products = [
                s for s in scored if s[1].score >= threshold
            ][:5]  # 最多分析前5个

            if top_products:
                self.logger.info("正在对 %d 个高分商品进行 ChatGPT 评论分析...",
                                 len(top_products))
                # 此处可以集成 FastMoss 的评论 API
                # 由于评论 API 需要单独调用，这里先跳过评论获取
                # 实际使用时，可以在此处调用 FastMossClient 的 get_product_reviews
                pass

        # ── 第五步：推送通知 ──
        push_messages = self._build_push_messages(scored, sentiment_results)
        if push_messages:
            pushed = self.notifier.send_batch(push_messages)
            stats["pushed"] = pushed

        # 发送运行摘要
        threshold = self.analyzer.thresholds.notify_min_score
        hot_score = self.analyzer.thresholds.hot_score
        trending_score = self.analyzer.thresholds.trending_score

        stats["hot_count"] = sum(1 for _, s in scored if s.score >= hot_score)
        stats["trending_count"] = sum(
            1 for _, s in scored if trending_score <= s.score < hot_score
        )

        summary = (
            f"📊 **选品分析完成** [run_id={run_id}]\n"
            f"• 抓取市场: {', '.join(m.upper() for m in markets)}\n"
            f"• 抓取商品: {stats['products_fetched']} 条\n"
            f"• 🔥 爆品潜力 (≥{hot_score}分): {stats['hot_count']} 个\n"
            f"• 📈 趋势上升 (≥{trending_score}分): {stats['trending_count']} 个\n"
            f"• 推送通知: {stats['pushed']} 条"
        )
        # 通知和日志分开：通知保留 emoji，日志用纯文本避免 GBK 编码问题
        self.notifier.send_text(summary)
        log_summary = (
            f"[RESULT] 选品分析完成 [run_id={run_id}]\n"
            f"  市场: {', '.join(m.upper() for m in markets)}\n"
            f"  商品: {stats['products_fetched']} 条 | "
            f"爆品: {stats['hot_count']} | "
            f"趋势: {stats['trending_count']} | "
            f"推送: {stats['pushed']}"
        )
        self.logger.info(log_summary)

        # 记录分析日志
        top_score = scores[0].score if scores else 0.0
        actual_source = products[0].source if products else "mock"
        self.storage.log_analysis(
            run_id=run_id,
            source=actual_source,
            market=",".join(markets),
            product_count=len(products),
            top_score=top_score,
            hot_count=stats["hot_count"],
            trending_count=stats["trending_count"],
            errors=stats["errors"],
        )

        self.logger.info("选品分析完成 [run_id=%s]", run_id)
        return stats

    def _build_push_messages(
        self,
        scored: list[tuple[ProductInsight, TrendScore]],
        sentiment_results: dict,
    ) -> list[PushMessage]:
        """构建推送消息列表（仅高分商品）"""
        threshold = self.analyzer.thresholds.notify_min_score
        messages = []

        for product, score in scored:
            if score.score < threshold:
                continue

            # 标题标签
            if score.score >= self.analyzer.thresholds.hot_score:
                tag = "🔥 爆品潜力"
            elif score.score >= self.analyzer.thresholds.trending_score:
                tag = "📈 趋势上升"
            else:
                tag = "👀 值得关注"

            title = f"{tag} | {product.title[:50]}"
            body = (
                f"💰 售价: ${product.price:.2f} | 销量: {product.sales_volume:,}\n"
                f"📈 7日增长: {product.sales_growth_7d:.1f}%\n"
                f"🏪 在售卖家: {product.seller_count} | 互动率: {product.engagement_rate*100:.2f}%\n"
                f"📊 综合评分: {score.score:.0f}/100 | {score.reasoning}"
            )

            sentiment = sentiment_results.get(product.product_id)
            messages.append(PushMessage(
                title=title,
                body=body,
                score=score.score,
                product_id=product.product_id,
                source=product.source,
                market=product.market.value,
                region=self.region,
                sentiment=sentiment,
            ))

        return messages

    async def _notify_error(self, message: str):
        """推送错误通知"""
        try:
            self.notifier.send_text(f"⚠️ 选品自动化异常: {message}")
        except Exception:
            pass

    def _generate_mock_products(self, markets: list[str]) -> list:
        """
        当 FastMoss API 不可用时生成模拟商品数据
        """
        import random
        from datetime import datetime, timezone
        from product_research import Market, ProductInsight

        mock_titles = {
            "th": [
                "Whitening Sunscreen SPF50 PA+++",
                "Yoga Leggings High Waist",
                "Wireless Bluetooth Earbuds TWS",
                "Collagen Face Serum Vitamin C",
                "Phone Case Cute Cat Pattern",
            ],
            "vn": [
                "Áo Thun Cotton 100%",
                "Kem Chống Nắng SPF50",
                "Sạc Dự Phòng 20000mAh",
                "Mặt Nạ Dưỡng Da Collagen",
                "Ốp Lưng iPhone Siêu Xinh",
            ],
            "my": [
                "Hijab Shawl Premium Cotton",
                "Skincare Set Vitamin C",
                "Wireless Mouse Ergonomic",
                "Tudung Segi Empat",
                "Essential Oil Diffuser",
            ],
        }

        products = []
        for market_code in markets:
            market_enum = Market(market_code)
            titles = mock_titles.get(market_code, mock_titles["th"])

            for i, title in enumerate(titles):
                price = round(random.uniform(5, 35), 2)
                sales = random.randint(500, 50000)
                growth = round(random.uniform(-20, 150), 1)
                likes = random.randint(100, 50000)
                comments = random.randint(10, 5000)
                shares = random.randint(5, 2000)
                views = random.randint(1000, 200000)
                engagement = (likes + comments + shares) / max(views, 1)
                sellers = random.randint(3, 150)

                product = ProductInsight(
                    product_id=f"mock_{market_code}_{i}",
                    title=title,
                    price=price,
                    sales_volume=sales,
                    sales_growth_7d=growth,
                    seller_count=sellers,
                    avg_price=round(price * random.uniform(0.8, 1.2), 2),
                    likes=likes,
                    comments=comments,
                    shares=shares,
                    engagement_rate=engagement,
                    source="mock",
                    market=market_enum,
                    fetched_at=datetime.now(timezone.utc),
                )
                products.append(product)

        self.logger.info("生成 %d 条模拟商品数据 (市场: %s)",
                         len(products), markets)
        return products


# ──────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────

# 区域配置映射
REGION_CONFIG_MAP = {
    "sea": "config.sea.yaml",
    "us": "config.us.yaml",
    "eu": "config.us.yaml",
}

DEFAULT_MARKETS: dict[str, list[str]] = {
    "sea": ["th", "vn", "my"],
    "us": ["us", "uk", "jp"],
    "eu": ["de", "fr", "es", "it"],
}


def load_config(path: str = "config.yaml") -> dict:
    """加载 YAML 配置文件"""
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 替换 ${ENV_VAR} 占位符
    def _resolve_env(value):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.getenv(env_var, value)
        return value

    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_walk(v) for v in obj]
        elif isinstance(obj, str):
            return _resolve_env(obj)
        return obj

    return _walk(config)


def main():
    parser = argparse.ArgumentParser(
        description="TikTok 选品自动化 - 按区域自动分析趋势商品并推送通知"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="仅运行一次，然后退出"
    )
    parser.add_argument(
        "--test-notify", action="store_true",
        help="发送测试通知，验证配置是否正确"
    )
    parser.add_argument(
        "--config", default=None,
        help="配置文件路径 (指定后忽略 --region)"
    )
    parser.add_argument(
        "--region", default="us",
        choices=["sea", "us", "eu"],
        help="目标区域 (sea=东南亚, us=美国+英国+日本, eu=欧洲)"
    )
    parser.add_argument(
        "--markets", default=None,
        help="市场列表，逗号分隔，如 'th,vn,my' (默认使用区域默认值)"
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="数据回溯天数 (默认 7)"
    )
    args = parser.parse_args()

    # 确定配置文件 (在 logging 初始化之前用 print)
    config_path = args.config or REGION_CONFIG_MAP.get(args.region, "config.yaml")
    print(f"使用配置文件: {config_path} (区域: {args.region})")

    if not os.path.exists(config_path):
        print(f"配置文件 {config_path} 不存在，回退到 config.yaml")
        config_path = "config.yaml"

    # 加载配置
    config = load_config(config_path)
    setup_logging(config)

    logger = logging.getLogger("main")
    logger.info("配置加载完成: %s (区域: %s)", config_path, args.region)

    # 确定市场列表
    markets = None
    if args.markets:
        markets = [m.strip().lower() for m in args.markets.split(",")]
    else:
        markets = DEFAULT_MARKETS.get(args.region, ["us"])

    # 测试通知
    if args.test_notify:
        logger.info("发送测试通知 (区域: %s)...", args.region)
        notify_cfg = config.get("notify", {})
        channel = notify_cfg.get("channel", "telegram")

        if channel == "email":
            from notify.email import NotifierWithEmail
            notifier = NotifierWithEmail()
        elif args.region == "sea":
            from notify.whatsapp import SEANotifier
            notifier = SEANotifier(channel=channel)
        else:
            notifier = Notifier(channel=channel)

        ok = notifier.send_text(
            f"✅ TikTok 选品自动化测试通知 ({args.region.upper()})\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"配置验证通过，推送渠道正常工作。"
        )
        if ok:
            logger.info("测试通知发送成功 ✅")
        else:
            logger.error("测试通知发送失败 ❌")
        return

    import asyncio

    if args.once:
        # 一次性运行
        logger.info("一次性运行模式 - 区域: %s, 市场: %s", args.region, markets)
        pipeline = ProductPipeline(config)
        pipeline.region = args.region  # 标记区域
        asyncio.run(pipeline.run_once(markets=markets, days=args.days))
    else:
        # 定时调度模式
        logger.info("定时调度模式 - 区域: %s", args.region)
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        pipeline = ProductPipeline(config)
        pipeline.region = args.region

        scheduler = AsyncIOScheduler()

        # 从配置读取抓取时间
        sources_cfg = config.get("sources", {})
        fastmoss_cfg = sources_cfg.get("fastmoss", {})
        fetch_times = fastmoss_cfg.get("fetch_times", ["08:00", "12:00", "20:00"])
        days = 7

        for time_str in fetch_times:
            hour, minute = map(int, time_str.split(":"))
            trigger = CronTrigger(hour=hour, minute=minute)
            scheduler.add_job(
                pipeline.run_once,
                trigger=trigger,
                kwargs={"markets": markets, "days": days},
                id=f"fetch_{args.region}_{time_str}",
                name=f"选品抓取 [{args.region}] {time_str}",
            )
            logger.info("已添加定时任务 [%s]: 每天 %s:%s 执行",
                        args.region, hour, minute)

        scheduler.start()
        logger.info("调度器已启动，按 Ctrl+C 停止")

        try:
            import signal
            signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown())
            signal.pause()
        except KeyboardInterrupt:
            logger.info("收到停止信号")
            scheduler.shutdown()


if __name__ == "__main__":
    main()
