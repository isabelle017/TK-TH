"""
泰国市场深度优化模块

覆盖三大核心策略:
1. 达人分销策略 (Influencer/KOL Strategy)
2. 直播电商策略 (Live Commerce Strategy)
3. 热门品类库 (Category Insights)

数据源: FastMoss 达人 API + ChatGPT 话术生成 + 本地品类知识库

使用方法:
    optimizer = ThailandMarketOptimizer()
    
    # 达人推荐
    creators = await optimizer.recommend_creators(category="beauty", budget=500)
    
    # 直播话术
    script = optimizer.generate_live_script(product_name="防晒霜", price=299)
    
    # 品类分析
    insights = optimizer.get_category_insights("beauty")
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────

@dataclass
class CreatorInfo:
    """达人信息"""
    creator_id: str
    nickname: str
    followers: int
    following: int
    likes: int
    avg_views: int
    engagement_rate: float           # 互动率 (%)
    categories: list[str]            # 擅长品类
    price_per_video: float           # 单条视频报价 (USD)
    price_per_live: float            # 单场直播报价 (USD)
    commission_rate: float           # 佣金比例 (0-1)
    tier: str = "koc"                # head / mid / koc
    score: float = 0.0               # 综合评分

    @property
    def follower_label(self) -> str:
        if self.followers >= 1_000_000:
            return "头部达人"
        elif self.followers >= 100_000:
            return "腰部达人"
        elif self.followers >= 10_000:
            return "KOC"
        return "素人"


@dataclass
class ProductTier:
    """选品分层"""
    name: str                        # 引流款 / 利润款 / 形象款
    price_range: tuple[float, float] # 价格区间 (THB)
    margin_target: float             # 目标利润率
    purpose: str                     # 策略目的
    examples: list[str]              # 示例品类


@dataclass
class CategoryInsight:
    """品类洞察"""
    category_id: str
    name_th: str                     # 泰语名称
    name_en: str                     # 英文名称
    tier: str                        # S/A/B/C
    avg_price: float                 # 客单价 (USD)
    avg_margin: float                # 平均利润率
    competition: str                 # low/mid/high
    growth_trend: str                # up/stable/down
    recommended_creator_tier: str    # 推荐达人层级
    top_keywords: list[str]          # 热搜关键词
    tips: str                        # 运营建议


# ──────────────────────────────────────────────
# 品类知识库 (内置)
# ──────────────────────────────────────────────

_CATEGORY_DB: list[CategoryInsight] = [
    # S级 - 美妆个护
    CategoryInsight(
        category_id="beauty_skincare", name_th="สกินแคร์", name_en="Skincare",
        tier="S", avg_price=18.0, avg_margin=0.65, competition="high",
        growth_trend="up", recommended_creator_tier="all",
        top_keywords=["กันแดด", "ไวท์เทนนิ่ง", "เซรั่ม", "มอยส์เจอร์ไรเซอร์"],
        tips="防晒是全年刚需。泰国用户极度重视美白提亮。建议用 KOC 大量铺量评测，头部达人做品牌背书。",
    ),
    CategoryInsight(
        category_id="beauty_makeup", name_th="เครื่องสำอาง", name_en="Makeup",
        tier="S", avg_price=15.0, avg_margin=0.70, competition="high",
        growth_trend="up", recommended_creator_tier="mid_koc",
        top_keywords=["รองพื้น", "ลิปสติก", "คอนซีลเลอร์", "อายแชโดว์"],
        tips="泰国全年炎热，防水防汗是核心卖点。唇釉/气垫/定妆喷雾是 TikTok 爆品三大件。",
    ),
    CategoryInsight(
        category_id="beauty_sunscreen", name_th="ครีมกันแดด", name_en="Sunscreen",
        tier="S", avg_price=12.0, avg_margin=0.60, competition="mid",
        growth_trend="up", recommended_creator_tier="all",
        top_keywords=["กันแดด", "SPF50", "PA+++", "ไม่มีแอลกอฮอล์"],
        tips="泰国年均气温28°C，防晒一年四季都是刚需。SPF50+PA+++是标配，无酒精配方是差异化卖点。",
    ),
    # A级 - 时尚服饰
    CategoryInsight(
        category_id="fashion_women", name_th="แฟชั่นผู้หญิง", name_en="Women's Fashion",
        tier="A", avg_price=12.0, avg_margin=0.55, competition="high",
        growth_trend="up", recommended_creator_tier="mid_koc",
        top_keywords=["เดรส", "กระโปรง", "เสื้อกล้าม", "กางเกงยีนส์"],
        tips="泰国女性偏爱亮色系+贴身版型。连衣裙和背心全年热卖。直播试穿展示转化率最好。",
    ),
    CategoryInsight(
        category_id="fashion_muslim", name_th="แฟชั่นมุสลิม", name_en="Muslim Fashion",
        tier="A", avg_price=15.0, avg_margin=0.60, competition="mid",
        growth_trend="up", recommended_creator_tier="koc",
        top_keywords=["ฮิญาบ", "ชุดมุสลิม", "ผ้าคลุมผม", "เดรสยาว"],
        tips="泰国南部穆斯林人口集中。hijab 和 modest fashion 是高速增长赛道，竞争尚未饱和。",
    ),
    CategoryInsight(
        category_id="fashion_accessories", name_th="เครื่องประดับ", name_en="Accessories",
        tier="A", avg_price=8.0, avg_margin=0.70, competition="mid",
        growth_trend="stable", recommended_creator_tier="koc",
        top_keywords=["สร้อยคอ", "ต่างหู", "กำไล", "แหวน"],
        tips="配饰是 TikTok 上冲动消费最强的品类。客单价低、退货率低、利润高。适合视频种草。",
    ),
    # B级 - 3C配件
    CategoryInsight(
        category_id="phone_case", name_th="เคสโทรศัพท์", name_en="Phone Cases",
        tier="B", avg_price=6.0, avg_margin=0.65, competition="high",
        growth_trend="stable", recommended_creator_tier="koc",
        top_keywords=["เคสไอโฟน", "เคสกันตก", "เคสน่ารัก", "สายคล้องมือถือ"],
        tips="泰国手机壳市场极大但竞争也大。差异化方向：IP联名/个性化定制/功能性(支架+卡槽)。",
    ),
    CategoryInsight(
        category_id="earphone", name_th="หูฟัง", name_en="Wireless Earbuds",
        tier="B", avg_price=10.0, avg_margin=0.45, competition="mid",
        growth_trend="up", recommended_creator_tier="mid",
        top_keywords=["หูฟังบลูทูธ", "หูฟังไร้สาย", "AirPods", "ลำโพง"],
        tips="低价 TWS 耳机在泰国需求极大。$8-15 是甜蜜点。重点强调续航和音质。",
    ),
    # C级 - 家居生活
    CategoryInsight(
        category_id="home_storage", name_th="ที่เก็บของ", name_en="Home Storage",
        tier="C", avg_price=8.0, avg_margin=0.50, competition="low",
        growth_trend="up", recommended_creator_tier="koc",
        top_keywords=["ที่เก็บของ", "ตะกร้า", "กล่องเก็บของ", "ชั้นวางของ"],
        tips="收纳类是蓝海品类。泰国 housewife 是主要受众，通过生活场景短视频带货效果好。",
    ),
    CategoryInsight(
        category_id="home_fragrance", name_th="น้ำหอมปรับอากาศ", name_en="Home Fragrance",
        tier="C", avg_price=10.0, avg_margin=0.70, competition="low",
        growth_trend="up", recommended_creator_tier="koc",
        top_keywords=["น้ำหอม", "เทียนหอม", "เครื่องฟอกอากาศ", "น้ำมันหอมระเหย"],
        tips="香薰/精油在泰国增长很快。客单价适中、利润高、退货率极低。适合做 TikTok 氛围感视频。",
    ),
]


# ──────────────────────────────────────────────
# 选品分层策略
# ──────────────────────────────────────────────

_PRODUCT_TIERS: list[ProductTier] = [
    ProductTier(
        name="引流款",
        price_range=(3.0, 8.0),
        margin_target=0.30,
        purpose="吸引流量，拉高直播间在线人数。不求赚钱，求停留时长和互动。",
        examples=["手机壳", "发饰", "小零食", "袜子"],
    ),
    ProductTier(
        name="利润款",
        price_range=(10.0, 25.0),
        margin_target=0.50,
        purpose="核心盈利来源。直播间主力推荐品。",
        examples=["护肤品", "服饰", "无线耳机", "香薰"],
    ),
    ProductTier(
        name="形象款",
        price_range=(30.0, 60.0),
        margin_target=0.40,
        purpose="提升品牌调性。不一定卖很多，但展示品质感。",
        examples=["高端护肤品套装", "品牌包袋", "电子产品"],
    ),
]


# ──────────────────────────────────────────────
# 核心类
# ──────────────────────────────────────────────

class ThailandMarketOptimizer:
    """
    泰国市场深度优化器

    【达人分销】
    - 按品类推荐达人
    - 达人评分排序
    - 佣金策略建议

    【直播电商】
    - 黄金时段建议
    - 话术模板生成 (ChatGPT)
    - 选品组合策略

    【品类洞察】
    - 品类 Tiers 分级
    - 竞争度分析
    - 关键词建议

    使用示例:
        optimizer = ThailandMarketOptimizer()
        
        # 获取品类洞察
        cat = optimizer.get_category_insights("beauty_skincare")
        
        # 生成直播话术
        script = optimizer.generate_live_script(
            product_name="Whitening Sunscreen SPF50",
            price=299,
            language="th",
        )
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        self.api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self._categories = {c.category_id: c for c in _CATEGORY_DB}
        self._tiers = {t.name: t for t in _PRODUCT_TIERS}
        self._openai = None
        if self.api_key and not self.api_key.startswith("${"):
            from openai import OpenAI
            self._openai = OpenAI(api_key=self.api_key)

    # ── 品类洞察 ──

    def get_category_insights(self, category_id: Optional[str] = None
                              ) -> list[CategoryInsight]:
        """获取品类洞察。category_id=None 返回全部"""
        if category_id:
            cat = self._categories.get(category_id)
            return [cat] if cat else []
        return list(self._categories.values())

    def get_top_tier_categories(self, min_tier: str = "A") -> list[CategoryInsight]:
        """获取指定层级及以上的品类。min_tier: S/A/B/C"""
        tier_rank = {"S": 0, "A": 1, "B": 2, "C": 3}
        min_rank = tier_rank.get(min_tier, 3)
        return [
            c for c in self._categories.values()
            if tier_rank.get(c.tier, 9) <= min_rank
        ]

    def get_categories_by_tier(self, tier: str) -> list[CategoryInsight]:
        """按 Tiers 获取品类"""
        return [c for c in self._categories.values() if c.tier == tier]

    # ── 达人推荐 ──

    async def recommend_creators(
        self,
        category: str,
        budget: float = 500.0,
        min_followers: int = 5_000,
        api_key: Optional[str] = None,
    ) -> list[CreatorInfo]:
        """
        从 FastMoss 获取达人推荐

        Args:
            category: 品类 ID
            budget: 预算 (USD)
            min_followers: 最低粉丝数
            api_key: FastMoss API Key

        Returns:
            按综合评分排序的达人列表
        """
        # 获取品类信息
        cat = self._categories.get(category)
        if not cat:
            logger.warning("未知品类: %s", category)
            return []

        # 从 FastMoss 获取达人数据
        creators = await self._fetch_creators_from_fastmoss(
            category=cat.name_en,
            min_followers=min_followers,
            api_key=api_key,
        )

        # 评分排序
        for c in creators:
            c.score = self._score_creator(c, cat)
        creators.sort(key=lambda c: c.score, reverse=True)

        # 预算过滤
        affordable = [
            c for c in creators
            if c.price_per_video <= budget or c.price_per_live <= budget
        ]

        logger.info(
            "品类 %s: 找到 %d 个达人, 预算内 %d 个",
            category, len(creators), len(affordable),
        )
        return affordable[:20]

    def _score_creator(self, creator: CreatorInfo, category: CategoryInsight) -> float:
        """达人综合评分"""
        # 粉丝量得分 (0-40)
        follower_score = min(40, creator.followers / 25_000)

        # 互动率得分 (0-30)
        engagement_score = min(30, creator.engagement_rate * 5)

        # 品类匹配度 (0-20)
        match_score = 20 if category.name_en in creator.categories else 5

        # 性价比 (0-10)
        value_score = 10 if creator.price_per_video <= 100 else \
                      5 if creator.price_per_video <= 300 else 2

        return follower_score + engagement_score + match_score + value_score

    async def _fetch_creators_from_fastmoss(
        self,
        category: str,
        min_followers: int,
        api_key: Optional[str] = None,
    ) -> list[CreatorInfo]:
        """从 FastMoss 达人 API 获取数据"""
        key = api_key or os.getenv("FAST_MOSS_API_KEY", "")
        if not key or key.startswith("${"):
            logger.warning("FastMoss API Key 未配置，使用模拟数据")
            return self._get_mock_creators(category)

        try:
            import httpx
            async with httpx.AsyncClient(
                base_url="https://open.fastmoss.com/v1",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15.0,
            ) as client:
                resp = await client.get("/creator/list", params={
                    "category": category,
                    "minFollowers": min_followers,
                    "pageSize": 50,
                })
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", {}).get("items", [])
                return [self._parse_fastmoss_creator(item) for item in items]

        except Exception as exc:
            logger.error("FastMoss 达人 API 请求失败: %s", exc)
            return self._get_mock_creators(category)

    @staticmethod
    def _parse_fastmoss_creator(item: dict) -> CreatorInfo:
        """FastMoss JSON → CreatorInfo"""
        followers = int(item.get("followers", 0) or 0)
        if followers >= 1_000_000:
            tier = "head"
        elif followers >= 100_000:
            tier = "mid"
        else:
            tier = "koc"

        return CreatorInfo(
            creator_id=str(item.get("id", "")),
            nickname=str(item.get("nickname", "")),
            followers=followers,
            following=int(item.get("following", 0) or 0),
            likes=int(item.get("likes", 0) or 0),
            avg_views=int(item.get("avgViews", 0) or 0),
            engagement_rate=float(item.get("engagementRate", 0) or 0),
            categories=[str(c) for c in item.get("categories", [])],
            price_per_video=float(item.get("pricePerVideo", 0) or 0),
            price_per_live=float(item.get("pricePerLive", 0) or 0),
            commission_rate=float(item.get("commissionRate", 0.15) or 0.15),
            tier=tier,
        )

    @staticmethod
    def _get_mock_creators(category: str) -> list[CreatorInfo]:
        """FastMoss 不可用时的模拟数据"""
        import random
        mock_names = ["สมหญิง ใจดี", "มานี มีชัย", "พิม พิมพ์ใจ",
                       "สรวง สวยจริง", "มุก มุกดา", "แพรว พราวแสง",
                       "น้ำตาล น่ารัก", "ครีม ครีเอทีฟ"]
        creators = []
        for i, name in enumerate(mock_names):
            followers = random.randint(8_000, 500_000)
            if followers >= 100_000:
                tier = "mid"
            else:
                tier = "koc"

            creators.append(CreatorInfo(
                creator_id=f"mock_th_{i}",
                nickname=name,
                followers=followers,
                following=random.randint(100, 5000),
                likes=random.randint(10_000, 500_000),
                avg_views=random.randint(2_000, 50_000),
                engagement_rate=random.uniform(2.0, 12.0),
                categories=[category, "lifestyle"],
                price_per_video=random.choice([30, 50, 80, 150, 300]),
                price_per_live=random.choice([50, 100, 200, 400, 800]),
                commission_rate=random.uniform(0.10, 0.25),
                tier=tier,
            ))
        return creators

    # ── 直播话术生成 (ChatGPT) ──

    def generate_live_script(
        self,
        product_name: str,
        price: float,
        language: str = "th",
        scene: str = "product_intro",
    ) -> str:
        """
        生成泰国直播话术

        Args:
            product_name: 产品名
            price: 价格 (THB)
            language: th/en
            scene: product_intro / promotion / closing

        Returns:
            话术文本
        """
        if not self._openai:
            return self._template_script(product_name, price, scene, language)

        lang_label = {
            "th": "泰语",
            "en": "英语",
        }.get(language, "泰语")

        scene_prompts = {
            "product_intro": "商品介绍开场，吸引停留",
            "promotion": "促单逼单，制造紧迫感",
            "closing": "收尾，引导下单",
        }

        prompt = f"""
你是一位泰国 TikTok 直播带货主播。请用{lang_label}生成一段直播话术。

场景: {scene_prompts.get(scene, 'product_intro')}
产品: {product_name}
价格: {price} 泰铢

要求:
1. 语气亲切活泼，符合泰国主播风格
2. 包含 3 个必用泰语直播高频词: ถูกมาก(超便宜)、คุ้ม(划算)、สั่งเลย(马上下单)
3. 加入互动引导（点赞、分享、评论）
4. 时长约 30-45 秒
5. 如果是促单场景，加入限时抢购的紧迫感

只输出话术本身，不要额外说明。
"""
        try:
            resp = self._openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500,
            )
            content = resp.choices[0].message.content
            return content or self._template_script(product_name, price, scene, language)
        except Exception as exc:
            logger.warning("ChatGPT 话术生成失败: %s", exc)
            return self._template_script(product_name, price, scene, language)

    @staticmethod
    def _template_script(
        product_name: str, price: float, scene: str, language: str
    ) -> str:
        """离线话术模板"""
        if language == "th":
            templates = {
                "product_intro": (
                    f"สวัสดีค่าา~ วันนี้พิมมีสินค้าดีๆ มาป้ายยาค่ะ!\n\n"
                    f"{product_name} ราคาเพียง {price:.0f} บาทเท่านั้น!\n"
                    f"คุ้มมากๆ เลยนะคะทุกคน\n"
                    f"กดไลค์ให้พิมหน่อยค่าา แล้วมาดูรายละเอียดกันเลย~\n\n"
                    f"#ของดีบอกต่อ #ป้ายยาสินค้าดี #TikTok"
                ),
                "promotion": (
                    f"รีบเลยค่าา! ส่วนลดจำนวนจำกัด!\n\n"
                    f"{product_name} ปกติ {price*1.3:.0f} บาท\n"
                    f"วันนี้เพียง {price:.0f} บาทเท่านั้น!\n"
                    f"ถูกมากกก คุ้มสุดๆ\n"
                    f"สั่งเลยตอนนี้ รับของไวใน 3-5 วัน~\n\n"
                    f"สินค้ามีจำนวนจำกัดนะคะทุกคน!"
                ),
                "closing": (
                    f"เหลืออีกแค่ 5 ชิ้นสุดท้ายแล้วค่า!\n\n"
                    f"{product_name} ราคา {price:.0f} บาท ส่งฟรี!\n"
                    f"สั่งเลยตอนนี้ ได้รับส่วนลดเพิ่มอีก 10%\n"
                    f"แคปหน้าจอแล้วส่งมาที่แชทเลยค่ะ\n\n"
                    f"ขอบคุณทุกคนที่ติดตามนะคะ 🥰"
                ),
            }
        else:
            templates = {
                "product_intro": f"Hi everyone! Today I have an amazing product to share with you!\n\n{product_name} only {price:.0f} THB!\nGreat value, don't miss out!\nLike and follow for more deals~\n\n#TikTokShopping #Thailand",
                "promotion": f"LIMITED TIME OFFER!\n\n{product_name} was {price*1.3:.0f} THB\nToday only {price:.0f} THB!\nSuper cheap! Great deal!\nOrder now, delivery in 3-5 days!",
                "closing": f"Only 5 items left!\n\n{product_name} at {price:.0f} THB with free shipping!\nOrder now and get extra 10% off!\nScreenshot and message us!\n\nThank you for watching! 🥰",
            }

        return templates.get(scene, templates["product_intro"])

    # ── 策略输出 ──

    def get_strategy_summary(self, budget: float = 500.0) -> dict:
        """
        获取泰国市场策略摘要

        Args:
            budget: 月预算 (USD)

        Returns:
            包含品类建议、达人策略、直播策略的字典
        """
        s_tier = self.get_categories_by_tier("S")
        a_tier = self.get_categories_by_tier("A")

        return {
            "market": "Thailand",
            "recommended_entry_categories": [c.name_en for c in s_tier + a_tier],
            "budget_allocation_suggestion": {
                "引流款": f"预算 {budget*0.15:.0f} USD，拉流量求互动",
                "利润款": f"预算 {budget*0.55:.0f} USD，核心盈利来源",
                "形象款": f"预算 {budget*0.30:.0f} USD，品牌建设+测试市场",
            },
            "live_best_hours": "12:00-14:00 (午休) + 18:00-23:00 (晚间黄金档)",
            "creator_strategy": {
                "头部达人 (100万+粉)": "品牌背书，每月1-2次合作，佣金10-15%",
                "腰部达人 (10-100万粉)": "常规带货，每周3-5次，佣金15-20%",
                "KOC (1-10万粉)": "铺量为主，样品+纯佣，20-30个起",
            },
            "key_marketing_dates": [
                "1月: 新年促销",
                "4月: 宋干节(泼水节) - 全年最大消费季",
                "8月: 母亲节",
                "11月: 双11 + 年末促销",
                "12月: 双12 + 跨年",
            ],
        }

    # ── 快照报表 ──

    def generate_report(self, budget: float = 500.0) -> str:
        """生成一份可推送的泰国市场策略报告"""
        strategy = self.get_strategy_summary(budget)

        lines = [
            "🇹🇭 **泰国市场策略报告**\n",
            f"📅 {datetime.now().strftime('%Y-%m-%d')}\n",
            "**推荐切入品类:**",
        ]
        for cat in strategy["recommended_entry_categories"][:5]:
            lines.append(f"  • {cat}")

        lines.extend([
            "",
            "**预算分配建议:**",
        ])
        for k, v in strategy["budget_allocation_suggestion"].items():
            lines.append(f"  • {k}: {v}")

        lines.extend([
            "",
            "**黄金直播时段:**",
            f"  {strategy['live_best_hours']}",
            "",
            "**达人策略:**",
        ])
        for k, v in strategy["creator_strategy"].items():
            lines.append(f"  • {k}: {v}")

        lines.extend([
            "",
            "**重要营销节点:**",
        ])
        for d in strategy["key_marketing_dates"]:
            lines.append(f"  • {d}")

        return "\n".join(lines)


# ──────────────────────────────────────────────
# 便捷调用
# ──────────────────────────────────────────────

def get_thailand_optimizer() -> ThailandMarketOptimizer:
    """快速获取泰国优化器实例"""
    return ThailandMarketOptimizer()


async def recommend_thailand_creators(
    category: str = "beauty_skincare",
    budget: float = 500.0,
) -> list[CreatorInfo]:
    """便捷函数：推荐泰国达人"""
    opt = ThailandMarketOptimizer()
    return await opt.recommend_creators(category=category, budget=budget)
