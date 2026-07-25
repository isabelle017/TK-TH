"""
TikTok 选品分析看板 (Streamlit)

使用方式:
    pip install streamlit plotly pandas
    streamlit run dashboard.py

功能:
    - 选品数据总览 (商品数/平均分/爆品数)
    - 商品排名表 (按趋势评分排序)
    - 评分分布图
    - 市场对比分析
    - 历史趋势
    - 分析日志

数据来源: SQLite 数据库 (data/tk_products_sea.db / data/tk_products_us.db)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ──────────────────────────────────────────────
# 页面配置 (必须是第一个 streamlit 命令)
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="TikTok 选品分析看板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# 数据库连接
# ──────────────────────────────────────────────

DB_PATHS = {
    "🌏 东南亚 (SEA)": "data/tk_products_sea.db",
    "🇺🇸 欧美 (US/EU)": "data/tk_products_us.db",
}


@st.cache_resource
def get_engine(db_path: str):
    """创建数据库引擎 (带缓存)"""
    from sqlalchemy import create_engine
    abs_path = os.path.join(os.path.dirname(__file__), db_path)
    if not os.path.exists(abs_path):
        return None
    return create_engine(f"sqlite:///{abs_path}")


def load_products(db_path: str) -> pd.DataFrame:
    """
    从 SQLite 加载商品数据

    Returns:
        DataFrame 包含商品信息、评分、市场等
    """
    engine = get_engine(db_path)
    if engine is None:
        return pd.DataFrame()

    query = """
        SELECT
            product_id,
            title,
            price,
            sales_volume,
            sales_growth_7d,
            seller_count,
            engagement_rate,
            source,
            market,
            trend_score,
            trend_direction,
            fetched_at,
            created_at
        FROM products
        ORDER BY fetched_at DESC
    """
    try:
        df = pd.read_sql(query, engine)
        if not df.empty:
            df["fetched_at"] = pd.to_datetime(df["fetched_at"])
            df["created_at"] = pd.to_datetime(df["created_at"])
            df["fetched_date"] = df["fetched_at"].dt.date
        return df
    except Exception:
        return pd.DataFrame()


def load_analysis_logs(db_path: str) -> pd.DataFrame:
    """加载分析日志"""
    engine = get_engine(db_path)
    if engine is None:
        return pd.DataFrame()

    query = """
        SELECT
            run_id, source, market, product_count,
            top_score, hot_count, trending_count, errors,
            ran_at
        FROM analysis_logs
        ORDER BY ran_at DESC
        LIMIT 100
    """
    try:
        df = pd.read_sql(query, engine)
        if not df.empty:
            df["ran_at"] = pd.to_datetime(df["ran_at"])
            df["date"] = df["ran_at"].dt.date
        return df
    except Exception:
        return pd.DataFrame()


# ──────────────────────────────────────────────
# 侧边栏
# ──────────────────────────────────────────────

def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.markdown("## 📊 选品看板")
        st.markdown("---")

        # 数据库选择
        db_label = st.radio(
            "选择区域",
            options=list(DB_PATHS.keys()),
            index=0,
            key="region_selector",
        )
        db_path = DB_PATHS[db_label]

        # 加载数据
        df = load_products(db_path)

        if df.empty:
            st.warning("⚠️ 暂无数据")
            st.info(
                "请先运行选品分析:\n\n"
                "```bash\n"
                "python scheduler.py --region sea --once\n"
                "```"
            )
            return df, db_path, db_label

        # 过滤器
        st.markdown("### 🔍 过滤条件")

        # 市场筛选
        markets = sorted(df["market"].unique())
        selected_markets = st.multiselect(
            "市场",
            options=markets,
            default=markets,
        )

        # 评分范围
        min_score, max_score = st.slider(
            "趋势评分",
            min_value=0.0,
            max_value=100.0,
            value=(0.0, 100.0),
        )

        # 销量范围
        min_sales, max_sales = st.slider(
            "销量范围",
            min_value=int(df["sales_volume"].min()),
            max_value=int(df["sales_volume"].max()),
            value=(int(df["sales_volume"].min()),
                   int(df["sales_volume"].max())),
        )

        # 应用过滤
        mask = (
            df["market"].isin(selected_markets)
            & (df["trend_score"] >= min_score)
            & (df["trend_score"] <= max_score)
            & (df["sales_volume"] >= min_sales)
            & (df["sales_volume"] <= max_sales)
        )
        filtered_df = df[mask]

        st.markdown("---")
        st.markdown(
            f"**显示**: {len(filtered_df)} / {len(df)} 条商品"
        )

        return filtered_df, db_path, db_label


# ──────────────────────────────────────────────
# 指标卡片
# ──────────────────────────────────────────────

def render_metric_cards(df: pd.DataFrame):
    """渲染顶部指标卡片"""
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            "📦 商品总数",
            len(df),
            delta=None,
        )

    with col2:
        avg_score = df["trend_score"].mean()
        st.metric(
            "⭐ 平均评分",
            f"{avg_score:.1f}",
            delta=f"Hot: ≥{85}" if avg_score < 85 else "🔥",
        )

    with col3:
        hot_count = len(df[df["trend_score"] >= 85])
        st.metric(
            "🔥 爆品潜力",
            hot_count,
            delta=f"占比 {hot_count/max(len(df),1)*100:.1f}%",
        )

    with col4:
        trending_count = len(
            df[(df["trend_score"] >= 75) & (df["trend_score"] < 85)]
        )
        st.metric(
            "📈 趋势上升",
            trending_count,
            delta=None,
        )

    with col5:
        markets = df["market"].nunique()
        total_sales = int(df["sales_volume"].sum())
        st.metric(
            "🌍 覆盖市场",
            f"{markets} 个",
            delta=f"总销量 {total_sales:,}",
        )


# ──────────────────────────────────────────────
# 评分分布图
# ──────────────────────────────────────────────

def render_score_distribution(df: pd.DataFrame):
    """评分分布直方图"""
    fig = px.histogram(
        df,
        x="trend_score",
        nbins=20,
        color="market",
        title="趋势评分分布",
        labels={"trend_score": "评分", "count": "商品数"},
        color_discrete_sequence=px.colors.qualitative.Bold,
    )
    fig.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    # 添加参考线
    fig.add_vline(x=85, line_dash="dash", line_color="red",
                  annotation_text="爆品线")
    fig.add_vline(x=75, line_dash="dash", line_color="orange",
                  annotation_text="趋势线")
    st.plotly_chart(fig, width='stretch')


# ──────────────────────────────────────────────
# 市场对比图
# ──────────────────────────────────────────────

def render_market_comparison(df: pd.DataFrame):
    """市场对比分析"""
    market_stats = df.groupby("market").agg({
        "trend_score": ["mean", "max", "min", "count"],
        "sales_volume": "sum",
        "price": "mean",
    }).round(1)

    market_stats.columns = ["平均分", "最高分", "最低分", "商品数",
                            "总销量", "均价"]
    market_stats = market_stats.sort_values("平均分", ascending=False)
    market_stats["总销量"] = market_stats["总销量"].astype(int)

    st.dataframe(
        market_stats,
        width='stretch',
        column_config={
            "总销量": st.column_config.NumberColumn(format="%d"),
            "均价": st.column_config.NumberColumn(format="$%.2f"),
        },
    )


# ──────────────────────────────────────────────
# 商品排名表
# ──────────────────────────────────────────────

def render_top_products(df: pd.DataFrame):
    """Top 商品排名表"""
    top_df = df.nlargest(50, "trend_score")[
        ["title", "market", "price", "sales_volume",
         "sales_growth_7d", "trend_score", "trend_direction",
         "seller_count", "engagement_rate"]
    ].copy()

    top_df.columns = [
        "商品标题", "市场", "价格 ($)", "销量",
        "7日增长率 (%)", "趋势评分", "趋势方向",
        "在售卖家", "互动率 (%)",
    ]

    # 格式化
    top_df["7日增长率 (%)"] = top_df["7日增长率 (%)"].round(1)
    top_df["互动率 (%)"] = (top_df["互动率 (%)"] * 100).round(2)
    top_df["价格 ($)"] = top_df["价格 ($)"].round(2)

    # 趋势方向着色
    def color_direction(val):
        colors = {"rising": "🟢", "stable": "🟡", "declining": "🔴"}
        return colors.get(val, "")

    top_df["趋势方向"] = top_df["趋势方向"].apply(color_direction)

    st.dataframe(
        top_df,
        width='stretch',
        height=600,
        column_config={
            "商品标题": st.column_config.TextColumn(width="large"),
            "市场": st.column_config.TextColumn(width="small"),
            "价格 ($)": st.column_config.NumberColumn(format="$%.2f"),
            "销量": st.column_config.NumberColumn(format="%d"),
            "趋势评分": st.column_config.NumberColumn(
                format="%.1f",
                help="综合趋势评分 (0-100)",
            ),
        },
    )


# ──────────────────────────────────────────────
# 历史趋势图
# ──────────────────────────────────────────────

def render_trend_chart(df: pd.DataFrame):
    """评分和销量的时间趋势"""
    if "fetched_date" not in df.columns:
        return

    daily = df.groupby("fetched_date").agg({
        "trend_score": "mean",
        "sales_volume": "sum",
        "product_id": "count",
    }).reset_index()
    daily = daily.sort_values("fetched_date")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=daily["fetched_date"],
        y=daily["trend_score"],
        name="平均评分",
        yaxis="y",
        line=dict(color="#636EFA", width=2),
        mode="lines+markers",
    ))

    fig.add_trace(go.Bar(
        x=daily["fetched_date"],
        y=daily["product_id"],
        name="商品数量",
        yaxis="y2",
        marker_color="#AB63FA",
        opacity=0.5,
    ))

    fig.update_layout(
        title="每日分析趋势",
        height=350,
        yaxis=dict(title="平均评分", range=[0, 100]),
        yaxis2=dict(
            title="商品数",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
        margin=dict(l=20, r=20, t=40, b=20),
    )

    st.plotly_chart(fig, width='stretch')


# ──────────────────────────────────────────────
# 分析日志
# ──────────────────────────────────────────────

def render_analysis_logs(db_path: str):
    """显示最近的分析运行日志"""
    logs = load_analysis_logs(db_path)
    if logs.empty:
        st.info("暂无分析日志")
        return

    st.subheader("📋 分析运行记录")

    # 显示最近的 20 条
    recent = logs.head(20)[
        ["date", "source", "market", "product_count",
         "top_score", "hot_count", "trending_count", "errors"]
    ]
    recent.columns = ["日期", "数据源", "市场", "商品数",
                      "最高分", "爆品数", "趋势数", "错误"]

    st.dataframe(recent, width='stretch', height=400)


# ──────────────────────────────────────────────
# 主页面
# ──────────────────────────────────────────────

def main():
    st.markdown(
        """
        <style>
        .main-header {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0;
        }
        .sub-header {
            color: #666;
            font-size: 0.9rem;
            margin-top: 0;
        }
        .stApp {
            background-color: #f8f9fa;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 侧边栏
    df, db_path, db_label = render_sidebar()

    if df.empty:
        return

    # 主内容区
    st.markdown(
        f'<p class="main-header">{db_label} 选品分析</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="sub-header">'
        f'数据更新: {datetime.now().strftime("%Y-%m-%d %H:%M")} | '
        f'商品总数: {len(df):,}'
        f'</p>',
        unsafe_allow_html=True,
    )

    # ── 指标卡片 ──
    render_metric_cards(df)

    st.markdown("---")

    # ── 双栏：评分分布 + 市场对比 ──
    col_left, col_right = st.columns([3, 2])

    with col_left:
        render_score_distribution(df)

    with col_right:
        st.subheader("📊 市场对比")
        render_market_comparison(df)

    st.markdown("---")

    # ── 趋势图 ──
    render_trend_chart(df)

    st.markdown("---")

    # ── 商品排名 ──
    st.subheader("🏆 Top 50 商品排名")
    render_top_products(df)

    st.markdown("---")

    # ── 分析日志 ──
    render_analysis_logs(db_path)


if __name__ == "__main__":
    main()
