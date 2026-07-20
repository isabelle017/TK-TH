"""
ChatGPT 评论情感分析 - 支持多语言 (中文/英文/泰语/越南语/马来语)

从 FastMoss/EchoTik 获取商品评论，调用 OpenAI API 进行情感分析，
提取用户好评点、痛点和优化建议。

SEA 语言说明:
- 泰语 (th): ChatGPT 原生支持良好，无需预处理
- 越南语 (vi): ChatGPT 支持良好，注意有音调符号
- 马来语 (ms): 使用拉丁字母，ChatGPT 处理无压力
- 印尼语 (id): 与马来语相近，基本互通
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from openai import OpenAI

from product_research import SentimentResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 多语言系统 Prompt
# ──────────────────────────────────────────────

_SYSTEM_PROMPT_ZH = """你是一位资深的 TikTok 电商选品分析师。

你的任务：分析 TikTok 商品评论，输出结构化的洞察报告。

要求：
1. 用中文输出（无论评论原文是什么语言）
2. 提取最核心的3个好评点
3. 提取最核心的3个痛点/差评点
4. 给出2-3条可落地的优化建议
5. 整体情感判断 (positive/neutral/negative)

注意：保持客观，不要编造评论中没有的信息。"""

_SYSTEM_PROMPT_EN = """You are a senior TikTok e-commerce product research analyst.

Your task: Analyze TikTok product reviews and output structured insights.

Requirements:
1. Output in English (regardless of review language)
2. Extract top 3 positive points
3. Extract top 3 pain points/negative feedback
4. Give 2-3 actionable improvement suggestions
5. Overall sentiment (positive/neutral/negative)

Be objective. Do not fabricate information not present in the reviews."""

_SYSTEM_PROMPT_TH = """คุณคือนักวิเคราะห์สินค้า TikTok E-commerce อาวุโส

วิเคราะห์รีวิวสินค้าบน TikTok และให้ข้อมูลเชิงลึกที่มีโครงสร้าง

ข้อกำหนด:
1. ให้ผลลัพธ์เป็นภาษาไทย
2. ดึงจุดบวก 3 อันดับแรก
3. ดึงจุดด้อย/ข้อร้องเรียน 3 อันดับแรก
4. ให้คำแนะนำในการปรับปรุง 2-3 ข้อ
5. ความรู้สึกโดยรวม (positive/neutral/negative)

มีวัตถุประสงค์ อย่าสร้างข้อมูลที่ไม่มีในรีวิว"""

_SYSTEM_PROMPT_VI = """Bạn là chuyên gia phân tích sản phẩm TikTok E-commerce cao cấp.

Nhiệm vụ: Phân tích đánh giá sản phẩm trên TikTok và đưa ra thông tin chi tiết có cấu trúc.

Yêu cầu:
1. Xuất kết quả bằng tiếng Việt
2. Trích xuất 3 điểm tích cực chính
3. Trích xuất 3 điểm đau/đánh giá tiêu cực chính
4. Đưa ra 2-3 gợi ý cải thiện khả thi
5. Đánh giá tổng thể (positive/neutral/negative)

Khách quan. Không bịa đặt thông tin không có trong đánh giá."""

_SYSTEM_PROMPT_MS = """Anda adalah penganalisis produk TikTok E-commerce senior.

Tugas: Menganalisis ulasan produk TikTok dan memberikan pandangan berstruktur.

Keperluan:
1. Keluarkan hasil dalam Bahasa Melayu
2. Ekstrak 3 titik positif utama
3. Ekstrak 3 titik kesakitan/aduam utama
4. Beri 2-3 cadangan penambahbaikan yang boleh dilaksanakan
5. Sentimen keseluruhan (positive/neutral/negative)

Bersikap objektif. Jangan merekacipta maklumat yang tiada dalam ulasan."""

# 输出语言 → System Prompt 映射
_SYSTEM_PROMPTS = {
    "zh-CN": _SYSTEM_PROMPT_ZH,
    "en": _SYSTEM_PROMPT_EN,
    "th": _SYSTEM_PROMPT_TH,
    "vi": _SYSTEM_PROMPT_VI,
    "ms": _SYSTEM_PROMPT_MS,
    "id": _SYSTEM_PROMPT_MS,  # 印尼语与马来语相近
}


def _detect_comment_languages(comments: list[str]) -> list[str]:
    """
    简单检测评论使用的主要语言
    返回语言代码列表，如 ["th", "vi", "en"]
    """
    # 泰语检测：Unicode 泰语字符范围 U+0E00–U+0E7F
    import re
    thai_pattern = re.compile(r'[\u0E00-\u0E7F]')
    # 越南语检测：带音调的拉丁字母
    viet_pattern = re.compile(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', re.IGNORECASE)

    langs = set()
    for comment in comments:
        if thai_pattern.search(comment):
            langs.add("th")
        elif viet_pattern.search(comment):
            langs.add("vi")
        else:
            langs.add("en")  # 默认为英语

    return list(langs)


class SentimentAnalyzer:
    """
    评论情感分析器 (多语言版)

    支持分析 中文/英文/泰语/越南语/马来语/印尼语 的评论，
    并指定输出语言。

    使用示例:
        analyzer = SentimentAnalyzer(output_lang="zh-CN")
        result = analyzer.analyze("prod_123", comments)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        max_comments: int = 50,
        output_lang: str = "zh-CN",
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key or self.api_key.startswith("${"):
            raise ValueError(
                "缺少 OpenAI API Key。请通过环境变量 OPENAI_API_KEY 设置。"
            )
        self.model = model
        self.max_comments = max_comments
        self.output_lang = output_lang

        self._client = OpenAI(api_key=self.api_key)

    def analyze(
        self,
        product_id: str,
        comments: list[str],
        output_lang: Optional[str] = None,
        source_lang: Optional[str] = None,
    ) -> Optional[SentimentResult]:
        """
        分析一组评论的情感

        Args:
            product_id: 商品 ID
            comments: 评论文本列表
            output_lang: 输出语言 (zh-CN/en/th/vi/ms)，默认使用初始化时的设置
            source_lang: 评论原文语言，None = 自动检测

        Returns:
            SentimentResult 或 None（分析失败时）
        """
        if not comments:
            logger.info("商品 %s 无评论，跳过分析", product_id)
            return None

        lang = output_lang or self.output_lang
        system_prompt = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PROMPT_EN)

        # 自动检测评论语言（用于日志和调试）
        detected = source_lang or _detect_comment_languages(comments)
        logger.info("商品 %s 评论语言检测: %s", product_id, detected)

        # 截取前 N 条
        comments_sample = comments[:self.max_comments]
        comments_text = "\n---\n".join(
            f"{i+1}. {c.strip()}" for i, c in enumerate(comments_sample)
        )

        user_prompt = f"""
以下是 TikTok 上一个商品的 {len(comments_sample)} 条评论。请分析：

{comments_text}

请严格按以下 JSON 格式输出（不要包含 markdown 代码块标记）：
{{
    "positive_points": ["好评点1", "好评点2", "好评点3"],
    "pain_points": ["痛点1", "痛点2", "痛点3"],
    "improvement_suggestions": ["建议1", "建议2"],
    "overall_sentiment": "positive/neutral/negative"
}}
"""

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                logger.warning("ChatGPT 返回空内容，商品 %s", product_id)
                return None

            result = json.loads(content)

            return SentimentResult(
                product_id=product_id,
                positive_points=result.get("positive_points", []),
                pain_points=result.get("pain_points", []),
                improvement_suggestions=result.get("improvement_suggestions", []),
                overall_sentiment=result.get("overall_sentiment", "neutral"),
            )

        except Exception as exc:
            logger.error("ChatGPT 分析失败 (商品 %s): %s", product_id, exc)
            return None

    def analyze_with_translation(
        self,
        product_id: str,
        comments: list[str],
        output_lang: str = "zh-CN",
    ) -> Optional[SentimentResult]:
        """
        分析 + 自动翻译评论（评论语言 → output_lang）

        与 analyze() 的区别: 会先让 ChatGPT 翻译评论为 output_lang 再分析。
        适合评论语言混杂的场景（如马来西亚的英语+马来语混杂评论）。

        实际使用中，ChatGPT 在一个调用中即可完成翻译+分析，
        所以这个方法是单独保留作为显式翻译选项。
        """
        # 让 ChatGPT 同时做翻译+分析
        lang = output_lang
        system_prompt = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PROMPT_EN)

        comments_sample = comments[:self.max_comments]
        comments_text = "\n---\n".join(
            f"{i+1}. {c.strip()}" for i, c in enumerate(comments_sample)
        )

        user_prompt = f"""
以下是一个 TikTok 商品的 {len(comments_sample)} 条评论，包含多种语言。
请先将其翻译为{'中文' if lang == 'zh-CN' else lang.upper()}，
然后进行分析。

评论:
{comments_text}

请严格按以下 JSON 格式输出：
{{
    "positive_points": ["点1", "点2", "点3"],
    "pain_points": ["点1", "点2", "点3"],
    "improvement_suggestions": ["建议1", "建议2"],
    "overall_sentiment": "positive/neutral/negative"
}}
"""

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                return None

            result = json.loads(content)
            return SentimentResult(
                product_id=product_id,
                positive_points=result.get("positive_points", []),
                pain_points=result.get("pain_points", []),
                improvement_suggestions=result.get("improvement_suggestions", []),
                overall_sentiment=result.get("overall_sentiment", "neutral"),
            )

        except Exception as exc:
            logger.error("翻译分析失败 (商品 %s): %s", product_id, exc)
            return None

    def batch_analyze(
        self,
        product_comments: dict[str, list[str]],
        output_lang: Optional[str] = None,
    ) -> dict[str, Optional[SentimentResult]]:
        """
        批量分析多个商品的评论

        Args:
            product_comments: {product_id: [comment, ...]}
            output_lang: 输出语言

        Returns:
            {product_id: SentimentResult}
        """
        results = {}
        for pid, comments in product_comments.items():
            result = self.analyze(pid, comments, output_lang=output_lang)
            results[pid] = result
        return results


# ──────────────────────────────────────────────
# Google Translate 辅助 (SEA 语言兜底翻译)
# ──────────────────────────────────────────────

class GoogleTranslateClient:
    """
    Google Cloud Translation API 客户端

    DeepL 不支持 泰语/越南语/菲律宾语，
    Google Translate 用于这些语言的批量翻译。

    API Key 获取:
    https://cloud.google.com/translate/docs/setup
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_TRANSLATE_API_KEY", "")

    def translate(
        self,
        texts: list[str],
        target_lang: str = "zh-CN",
        source_lang: Optional[str] = None,
    ) -> list[str]:
        """
        批量翻译

        Args:
            texts: 待翻译文本
            target_lang: 目标语言
            source_lang: 源语言 (None = 自动检测)

        Returns:
            翻译后的文本列表
        """
        if not self.api_key or self.api_key.startswith("${"):
            logger.warning("Google Translate API Key 未配置，跳过翻译")
            return texts

        import httpx

        results: list[str] = []
        # Google Translate API 一次最大 128 条
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            payload = {
                "q": batch,
                "target": target_lang,
            }
            if source_lang:
                payload["source"] = source_lang

            try:
                resp = httpx.post(
                    f"https://translation.googleapis.com/language/translate/v2",
                    params={"key": self.api_key},
                    json=payload,
                    timeout=15.0,
                )
                resp.raise_for_status()
                data = resp.json()
                translations = data.get("data", {}).get("translations", [])
                for t in translations:
                    results.append(t.get("translatedText", ""))
            except Exception as exc:
                logger.error("Google Translate 批量翻译失败: %s", exc)
                results.extend(batch)  # 失败时返回原文

        return results
