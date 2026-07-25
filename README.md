# TikTok 选品自动化工具

多数据源自动抓取 TikTok 趋势商品 → 趋势评分 → ChatGPT 情感分析 → 多通道推送爆品线索。
数据源优先级：EchoTik Cookie 抓取 → Mock 数据（无 API Key 也可运行）。

## 快速开始

### 1. 安装

```bash
# 克隆项目
cd tk-automation

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置

复制环境变量模板并填入真实值：

```bash
cp .env.example .env
```

需要配置以下 API Key：

| 环境变量 | 必填 | 获取方式 |
|----------|:----:|----------|
| `ECHO_TIK_COOKIE` | ❌ | EchoTik 浏览器登录后从 Cookie 获取（选配，不用时走 Mock 数据） |
| `OPENAI_API_KEY` | ✅ | [OpenAI Platform](https://platform.openai.com/api-keys) 或 DeepSeek |
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram 搜索 @BotFather，创建 Bot |
| `TELEGRAM_CHAT_ID` | ✅ | 向你的 Bot 发一条消息后访问 `https://api.telegram.org/bot<token>/getUpdates` 获取 |

> **FastMoss 说明**：FastMoss 没有公开的 REST API，代码中的 FastMoss 客户端已降级为占位符。实际运行时 pipeline 会自动尝试 EchoTik，若均不可用则使用 Mock 数据，**无需额外配置 FastMoss**。

### 3. 测试配置

```bash
python scheduler.py --test-notify
```

如果 Telegram 收到测试消息，说明配置成功。

### 4. 运行

```bash
# 一次性运行
python scheduler.py --once

# 定时模式（按 config.yaml 设置的时间执行）
python scheduler.py

# 指定市场
python scheduler.py --once --markets us,uk,jp,de
```

## 部署方案

### 方案 A：GitHub Actions（推荐，免费）

1. 将代码推送到 GitHub 仓库
2. 在 Settings → Secrets and variables → Actions 中设置所有环境变量
3. 推送后自动启用 `.github/workflows/product_research.yml`

每日自动在 08:00 / 12:00 / 20:00（北京时间）执行。

### 方案 B：Linux VPS

```bash
# 添加 crontab 条目（每天 8/12/20 点运行）
0 8,12,20 * * * cd /path/to/tk-automation && .venv/bin/python scheduler.py --once >> logs/cron.log 2>&1
```

### 方案 C：Windows Task Scheduler

```powershell
# 创建计划任务，每天 08:00 / 12:00 / 20:00 执行
# 操作: C:\path\to\.venv\Scripts\python.exe C:\path\to\tk-automation\scheduler.py --once
```

## 项目结构

```
tk-automation/
├── product_research/
│   ├── __init__.py          # 数据模型 (ProductInsight, TrendScore, PushMessage)
│   ├── fetcher_fastmoss.py  # FastMoss API 客户端
│   ├── fetcher_echotik.py   # EchoTik 数据抓取（可选）
│   ├── analyzer_trend.py    # 趋势评分算法
│   └── analyzer_sentiment.py # ChatGPT 评论情感分析
├── notify/
│   └── __init__.py          # Telegram / 企业微信推送
├── storage/
│   └── __init__.py          # SQLite / PostgreSQL 存储
├── .github/workflows/
│   └── product_research.yml # GitHub Actions 工作流（免费部署）
├── scheduler.py             # 主入口 & 定时调度
├── config.yaml              # 配置文件
├── .env.example             # 环境变量模板
└── requirements.txt         # Python 依赖
```

## 工作流程

```
EchoTik / Mock ──→ 趋势评分 ──→ ChatGPT 分析 ──→ DB 存储 ──→ 多通道推送
                    ↓
              评论情感摘要
```

## 推送示例

```
🔥 爆品潜力 | Yoga Leggings Women High Waist

💰 售价: $24.99 | 销量: 45,830
📈 7日增长: 128.5%
🏪 在售卖家: 23 | 互动率: 8.72%
📊 综合评分: 92/100 | 增长分=100, 竞争分=72, ...

💬 评论洞察
好评:
  ✅ 面料柔软舒适
  ✅ 高腰设计显瘦
  ✅ 运动瑜伽都适合
痛点:
  ❌ 浅色款透色
  ❌ 尺码偏小一码

🕐 2025-07-20 08:00
```

## 自定义

编辑 `config.yaml` 调整：

- **评分权重**：调整各维度的权重系数
- **推送阈值**：设置多少分的商品才推送
- **抓取市场**：选择要监控的国家/地区
- **抓取时间**：设置定时执行的时间点
