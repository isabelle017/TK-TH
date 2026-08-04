# TikTok 选品自动化工具

> 投资安全更新：生产模式不再用随机 Mock 数据兜底，也不再把售价高低当作利润。
> 系统会估算贡献利润、最大 CPA 和保本 ROAS，并只推送同时通过趋势与利润闸门的真实数据。

## 泰国市场推荐用法（零 API 成本）

1. 从 TikTok Creative Center / Seller Center 收集真实泰国商品数据。
2. 复制 `data/input/products.example.csv` 为 `data/input/products.csv`，替换示例数据。
3. 用真实合同与经营数据更新 `config.sea.yaml` 的 `unit_economics.markets.th`。
4. 运行：`python scheduler.py --region sea --once --markets th`。
5. 仅演示功能时使用 `--demo`；Demo 数据永远不会通过投资推送闸门。

完整投资逻辑、免费工具、资金闸门和人工事项见 `docs/TH_PROFIT_PLAYBOOK.md`。

店铺尚未注册也可运行。每个候选会被分到“询价/合规验证、样品测试、观察、淘汰”之一，
结果写入 `reports/latest_selection.md`。店铺注册后只需更新 `config.sea.yaml` 的
`store_profile`，平台费率会覆盖原假设，历史研究无需重做。

可审计商品数据 → 趋势与单位经济评分 → 投资硬闸门 → 存储与通知。
默认优先读取标准 CSV，其次尝试 FastMoss 官方 MCP，再降级读取会员官方导出的 Excel/CSV。
EchoTik 无额度时保持关闭；
所有真实来源都不可用则安全停止。

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

CSV 分析本身不需要 API Key。以下变量只在启用对应可选功能时配置：

| 环境变量 | 必填 | 获取方式 |
|----------|:----:|----------|
| `ECHOTIK_USERNAME` / `ECHOTIK_PASSWORD` | ❌ | EchoTik API Dashboard；仅官方 API 连接器使用 |
| `FASTMOSS_MCP_KEY` | ❌ | FastMoss Developer Center；MCP 启用时必填，3 天免费试用 |
| `OPENAI_API_KEY` | ❌ | 开启评论 AI 分析后使用 |
| `SMTP_USER` / `SMTP_PASSWORD` | ❌ | 开启邮件通知后使用 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | ❌ | 开启 Telegram 通知后使用 |

> FastMoss MCP 走官方远程服务；服务异常或免费额度结束时自动降级到官方 Data Export，
> 不抓取会员网页。OpenAPI 只在试用审批通过后启用。
> 旧 EchoTik Cookie/网页抓取模块不进入生产流水线。

FastMoss OpenAPI 使用 `FASTMOSS_CLIENT_ID` 与 `FASTMOSS_CLIENT_SECRET` 换取短期 Access Token；
凭据只保存在本机用户环境变量，不提交仓库。

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

### 方案 A：GitHub Actions（真实 CSV 更新后手动触发）

1. 将代码推送到 GitHub 仓库
2. 提交不敏感的标准化输入数据，或在本地运行以保护经营数据
3. 在 Actions 中手动触发 `sea_research.yml`

静态 CSV 不应定时重复分析；需要完全自动化时再接入有授权的稳定 API。

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
│   ├── fetcher_csv.py       # 免费、可审计的标准 CSV 导入
│   ├── fetcher_fastmoss_mcp.py # FastMoss 官方 MCP 客户端
│   ├── fetcher_fastmoss_export.py # FastMoss 官方导出导入
│   ├── unit_economics.py    # 贡献利润、最大 CPA、保本 ROAS
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
真实 CSV / 已授权 API ──→ 趋势+单位经济评分 ──→ 投资闸门 ──→ DB ──→ 通知
无真实数据              ──→ 安全停止（不生成投资信号）
```

## 推送示例

```
🔥 爆品潜力 | Yoga Leggings Women High Waist

💰 售价: $24.99 | 销量: 45,830
📈 7日增长: 128.5%
🏪 在售卖家: 23 | 互动率: 8.72%
💹 贡献利润率(估): 18.0% | 保本ROAS: 3.10 | 最大CPA: $6.20
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
