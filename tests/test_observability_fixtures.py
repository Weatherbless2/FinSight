"""验证真实运行观测的 fixture 不会误访问情绪数据外部接口。"""

from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.agents.utils import (
    core_stock_tools,
    fundamental_data_tools,
    macro_data_tools,
    market_data_validation_tools,
    news_data_tools,
    prediction_markets_tools,
    technical_indicators_tools,
)
from tradingagents.observability.fixtures import install_fixture_data


def test_fixture_replaces_sentiment_network_references():
    """fixture 要替换分析师模块已经导入的函数引用，而不只是源模块属性。"""
    original_stocktwits = sentiment_analyst.fetch_stocktwits_messages
    original_reddit = sentiment_analyst.fetch_reddit_posts
    modules_with_route = [
        core_stock_tools,
        fundamental_data_tools,
        macro_data_tools,
        news_data_tools,
        prediction_markets_tools,
        technical_indicators_tools,
    ]
    original_routes = {
        module: module.route_to_vendor
        for module in modules_with_route
        if hasattr(module, "route_to_vendor")
    }
    original_snapshot = market_data_validation_tools.build_verified_market_snapshot
    try:
        install_fixture_data()
        assert "FIXTURE|StockTwits" in sentiment_analyst.fetch_stocktwits_messages("NVDA")
        assert "FIXTURE|Reddit" in sentiment_analyst.fetch_reddit_posts("NVDA")
    finally:
        # 避免 fixture 的模块级替换影响同一测试进程中的其他用例。
        sentiment_analyst.fetch_stocktwits_messages = original_stocktwits
        sentiment_analyst.fetch_reddit_posts = original_reddit
        for module, route in original_routes.items():
            module.route_to_vendor = route
        market_data_validation_tools.build_verified_market_snapshot = original_snapshot
