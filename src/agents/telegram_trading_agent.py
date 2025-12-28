#!/usr/bin/env python3
"""
Moon Dev's Telegram Trading Agent - SOLANA/JUPITER VERSION

A simple, self-contained trading bot that works on Railway.
Uses Jupiter DEX on Solana - works in the US!

Built with love by Moon Dev
"""

import os
import sys
import time
import requests
import json
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# OpenAI
OPENAI_KEY = os.getenv("OPENAI_KEY", "")

# Solana
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY", "")
RPC_ENDPOINT = os.getenv("RPC_ENDPOINT", "https://api.mainnet-beta.solana.com")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")

# Alert Thresholds
FEAR_GREED_EXTREME_LOW = 25   # Below this = extreme fear (buy signal)
FEAR_GREED_EXTREME_HIGH = 75  # Above this = extreme greed (sell signal)
PRICE_ALERT_THRESHOLD = 7     # % change to trigger big move alert

# Token Addresses
USDC_ADDRESS = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_ADDRESS = "So11111111111111111111111111111111111111112"  # WSOL - Wrapped SOL (ends with 2!)

# Trading Settings - All tradeable tokens
TOKENS = {
    "SOL": SOL_ADDRESS,
    "USDC": USDC_ADDRESS,
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
}
DEFAULT_TOKEN = "SOL"
TRADE_SIZE_USD = 10  # Default trade size in USD
SLIPPAGE_BPS = 500  # 5% slippage
CHECK_INTERVAL_MINUTES = 15
MIN_CONFIDENCE = 70  # Minimum confidence for auto-trading

# Autonomous Trading Settings
AUTO_TRADE_AMOUNT = 0.01  # Amount to trade in token units when auto mode is on
AUTO_CONFIRM_TIMEOUT = 60  # Seconds to wait for user confirmation (0 = no confirmation needed)
AUTO_MAX_DAILY_TRADES = 10  # Max trades per day in auto mode

# Full Autonomous Mode Settings
FULL_AUTO_MODE = False      # When True, trades execute WITHOUT confirmation
FULL_AUTO_REENTRY = True    # Re-enter positions after SL/TP triggers
FULL_AUTO_MAX_LOSS_USD = 50  # Max daily loss before pausing (safety limit)
FULL_AUTO_COOLDOWN = 5      # Minutes to wait between trades

# Risk Management Settings
DEFAULT_STOP_LOSS_PCT = 5.0      # Default stop loss percentage (5%)
DEFAULT_TAKE_PROFIT_PCT = 10.0  # Default take profit percentage (10%)
TRAILING_STOP_ENABLED = False    # Enable trailing stop loss
TRAILING_STOP_PCT = 3.0         # Trailing stop percentage from high

# Position Tracking (persisted in memory, reset on restart)
POSITIONS = {}  # {"token": {"entry_price": x, "amount": y, "stop_loss": z, "take_profit": w, "high": h}}

# External Agent Data (will be populated by agent feeds)
AGENT_DATA = {
    "sentiment": {"signal": None, "message": "", "updated": None},
    "volume": {"signal": None, "message": "", "updated": None},
    "tvl": {"signal": None, "message": "", "updated": None},
    "dominance": {"signal": None, "message": "", "updated": None},
    "dex_volume": {"signal": None, "message": "", "updated": None},
    "yields": {"signal": None, "message": "", "updated": None},
    "stablecoins": {"signal": None, "message": "", "updated": None},
    "whales": {"signal": None, "message": "", "updated": None},
}

# ============================================================================
# FREE DATA FEEDS (No API keys required)
# ============================================================================

def fetch_fear_greed() -> dict:
    """Fetch Fear & Greed Index from alternative.me (FREE, no API key)"""
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            print(f"Fear & Greed API error: {response.status_code}")
            return None

        data = response.json()
        if data.get("data"):
            fng = data["data"][0]
            return {
                "value": int(fng.get("value", 50)),
                "classification": fng.get("value_classification", "Neutral"),
                "timestamp": datetime.now()
            }
        return None

    except Exception as e:
        print(f"Error fetching Fear & Greed: {e}")
        return None


def fetch_sol_market_data() -> dict:
    """Fetch SOL market data from CoinGecko (FREE, no API key)"""
    try:
        url = "https://api.coingecko.com/api/v3/coins/solana"
        params = {
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false"
        }
        response = requests.get(url, params=params, timeout=10)

        if response.status_code != 200:
            print(f"CoinGecko API error: {response.status_code}")
            return None

        data = response.json()
        market = data.get("market_data", {})

        return {
            "price": market.get("current_price", {}).get("usd", 0),
            "price_change_24h": market.get("price_change_percentage_24h", 0),
            "price_change_7d": market.get("price_change_percentage_7d", 0),
            "volume_24h": market.get("total_volume", {}).get("usd", 0),
            "volume_change_24h": market.get("volume_change_24h", 0) if "volume_change_24h" in market else 0,
            "market_cap": market.get("market_cap", {}).get("usd", 0),
            "ath": market.get("ath", {}).get("usd", 0),
            "ath_change": market.get("ath_change_percentage", {}).get("usd", 0),
            "timestamp": datetime.now()
        }

    except Exception as e:
        print(f"Error fetching SOL market data: {e}")
        return None


def update_sentiment_data():
    """Update sentiment from Fear & Greed Index"""
    fng = fetch_fear_greed()
    if not fng:
        return

    value = fng["value"]
    classification = fng["classification"]

    # Determine signal based on Fear & Greed
    # Extreme Fear (<25) = potential buy opportunity
    # Extreme Greed (>75) = potential sell signal
    if value <= 25:
        signal = "BULLISH"  # Extreme fear = buy opportunity
        message = f"Extreme Fear ({value}/100) - Potential buy opportunity"
    elif value <= 40:
        signal = "NEUTRAL"
        message = f"Fear ({value}/100) - Market cautious"
    elif value <= 60:
        signal = "NEUTRAL"
        message = f"Neutral ({value}/100) - Market indecisive"
    elif value <= 75:
        signal = "NEUTRAL"
        message = f"Greed ({value}/100) - Market confident"
    else:
        signal = "BEARISH"  # Extreme greed = potential top
        message = f"Extreme Greed ({value}/100) - Potential correction ahead"

    AGENT_DATA["sentiment"]["signal"] = signal
    AGENT_DATA["sentiment"]["message"] = message
    AGENT_DATA["sentiment"]["updated"] = datetime.now()
    AGENT_DATA["sentiment"]["value"] = value
    AGENT_DATA["sentiment"]["classification"] = classification

    print(f"Sentiment update: {signal} - {message}")


def update_volume_data():
    """Update volume/market data for SOL"""
    market = fetch_sol_market_data()
    if not market:
        return

    price_change = market["price_change_24h"]
    volume = market["volume_24h"]

    # Determine signal based on price momentum and volume
    if price_change > 5:
        signal = "BULLISH"
        message = f"SOL up {price_change:.1f}% (24h), Vol: ${volume/1e9:.2f}B"
    elif price_change > 2:
        signal = "NEUTRAL"
        message = f"SOL up {price_change:.1f}% (24h), moderate momentum"
    elif price_change < -5:
        signal = "BEARISH"
        message = f"SOL down {abs(price_change):.1f}% (24h), Vol: ${volume/1e9:.2f}B"
    elif price_change < -2:
        signal = "NEUTRAL"
        message = f"SOL down {abs(price_change):.1f}% (24h), minor pullback"
    else:
        signal = "NEUTRAL"
        message = f"SOL flat ({price_change:+.1f}%), consolidating"

    AGENT_DATA["volume"]["signal"] = signal
    AGENT_DATA["volume"]["message"] = message
    AGENT_DATA["volume"]["updated"] = datetime.now()
    AGENT_DATA["volume"]["price_change"] = price_change
    AGENT_DATA["volume"]["volume_24h"] = volume
    AGENT_DATA["volume"]["market_data"] = market

    print(f"Volume update: {signal} - {message}")


def get_sentiment_status() -> str:
    """Get formatted sentiment status for Telegram"""
    data = AGENT_DATA.get("sentiment", {})

    if not data.get("updated"):
        return "No sentiment data available yet."

    age = datetime.now() - data["updated"]
    age_mins = age.total_seconds() / 60

    value = data.get("value", 50)
    classification = data.get("classification", "Neutral")
    signal = data.get("signal", "NEUTRAL")

    # Fear & Greed emoji scale
    if value <= 25:
        emoji = "😱"
    elif value <= 40:
        emoji = "😰"
    elif value <= 60:
        emoji = "😐"
    elif value <= 75:
        emoji = "😊"
    else:
        emoji = "🤑"

    signal_emoji = "🟢" if signal == "BULLISH" else "🔴" if signal == "BEARISH" else "⚪"

    return f"""{emoji} <b>Market Sentiment</b>

<b>Fear & Greed:</b> {value}/100 ({classification})
<b>Signal:</b> {signal_emoji} {signal}
<b>Updated:</b> {age_mins:.0f} min ago

<i>{'Buy opportunity - others are fearful' if value <= 25 else 'Caution - market may be overheated' if value >= 75 else 'Normal market conditions'}</i>"""


def get_market_status() -> str:
    """Get formatted market status for Telegram"""
    data = AGENT_DATA.get("volume", {})

    if not data.get("updated"):
        return "No market data available yet."

    age = datetime.now() - data["updated"]
    age_mins = age.total_seconds() / 60

    market = data.get("market_data", {})
    price = market.get("price", 0)
    change_24h = market.get("price_change_24h", 0)
    change_7d = market.get("price_change_7d", 0)
    volume = market.get("volume_24h", 0)
    ath = market.get("ath", 0)
    ath_change = market.get("ath_change", 0)

    trend_emoji = "📈" if change_24h > 0 else "📉"

    return f"""{trend_emoji} <b>SOL Market Data</b>

<b>Price:</b> ${price:,.2f}
<b>24h Change:</b> {change_24h:+.2f}%
<b>7d Change:</b> {change_7d:+.2f}%
<b>24h Volume:</b> ${volume/1e9:.2f}B
<b>ATH:</b> ${ath:,.2f} ({ath_change:.1f}%)

<b>Updated:</b> {age_mins:.0f} min ago"""


def fetch_trending_coins() -> list:
    """Fetch trending coins from CoinGecko (FREE)"""
    try:
        url = "https://api.coingecko.com/api/v3/search/trending"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            print(f"CoinGecko trending API error: {response.status_code}")
            return None

        data = response.json()
        coins = data.get("coins", [])

        trending = []
        for coin in coins[:7]:  # Top 7
            item = coin.get("item", {})
            trending.append({
                "name": item.get("name", "Unknown"),
                "symbol": item.get("symbol", "???").upper(),
                "rank": item.get("market_cap_rank", 0),
                "price_btc": item.get("price_btc", 0),
                "score": item.get("score", 0) + 1  # 0-indexed
            })

        return trending

    except Exception as e:
        print(f"Error fetching trending: {e}")
        return None


def fetch_btc_dominance() -> dict:
    """Fetch BTC dominance and global market data from CoinGecko (FREE)"""
    try:
        url = "https://api.coingecko.com/api/v3/global"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            print(f"CoinGecko global API error: {response.status_code}")
            return None

        data = response.json().get("data", {})

        return {
            "btc_dominance": data.get("market_cap_percentage", {}).get("btc", 0),
            "eth_dominance": data.get("market_cap_percentage", {}).get("eth", 0),
            "total_market_cap": data.get("total_market_cap", {}).get("usd", 0),
            "total_volume": data.get("total_volume", {}).get("usd", 0),
            "market_cap_change_24h": data.get("market_cap_change_percentage_24h_usd", 0),
            "active_cryptocurrencies": data.get("active_cryptocurrencies", 0),
            "timestamp": datetime.now()
        }

    except Exception as e:
        print(f"Error fetching BTC dominance: {e}")
        return None


def fetch_solana_tvl() -> dict:
    """Fetch Solana TVL from DeFiLlama (FREE)"""
    try:
        url = "https://api.llama.fi/v2/chains"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            print(f"DeFiLlama API error: {response.status_code}")
            return None

        chains = response.json()

        # Find Solana
        solana = None
        for chain in chains:
            if chain.get("name", "").lower() == "solana":
                solana = chain
                break

        if not solana:
            return None

        return {
            "tvl": solana.get("tvl", 0),
            "change_1d": solana.get("change_1d", 0),
            "change_7d": solana.get("change_7d", 0),
            "timestamp": datetime.now()
        }

    except Exception as e:
        print(f"Error fetching Solana TVL: {e}")
        return None


def fetch_top_gainers() -> dict:
    """Fetch top gainers and losers from CoinGecko (FREE)"""
    try:
        # Get top coins by market cap with price changes
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 100,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h"
        }
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"CoinGecko markets API error: {response.status_code}")
            return None

        coins = response.json()

        # Sort by 24h change
        sorted_coins = sorted(coins, key=lambda x: x.get("price_change_percentage_24h") or 0, reverse=True)

        gainers = []
        for coin in sorted_coins[:5]:
            gainers.append({
                "name": coin.get("name", "Unknown"),
                "symbol": coin.get("symbol", "???").upper(),
                "price": coin.get("current_price", 0),
                "change_24h": coin.get("price_change_percentage_24h", 0)
            })

        losers = []
        for coin in sorted_coins[-5:]:
            losers.append({
                "name": coin.get("name", "Unknown"),
                "symbol": coin.get("symbol", "???").upper(),
                "price": coin.get("current_price", 0),
                "change_24h": coin.get("price_change_percentage_24h", 0)
            })

        return {
            "gainers": gainers,
            "losers": list(reversed(losers)),  # Worst first
            "timestamp": datetime.now()
        }

    except Exception as e:
        print(f"Error fetching top gainers: {e}")
        return None


def get_trending_status() -> str:
    """Get formatted trending coins for Telegram"""
    trending = fetch_trending_coins()

    if not trending:
        return "Could not fetch trending coins."

    lines = ["🔥 <b>Trending Coins</b>\n"]

    for i, coin in enumerate(trending):
        rank = coin.get("rank", "?")
        rank_str = f"#{rank}" if rank else ""
        lines.append(f"{i+1}. <b>{coin['symbol']}</b> - {coin['name']} {rank_str}")

    lines.append("\n<i>Source: CoinGecko</i>")

    return "\n".join(lines)


def get_btc_dominance_status() -> str:
    """Get formatted BTC dominance for Telegram"""
    data = fetch_btc_dominance()

    if not data:
        return "Could not fetch market data."

    btc_dom = data["btc_dominance"]
    eth_dom = data["eth_dominance"]
    total_cap = data["total_market_cap"]
    cap_change = data["market_cap_change_24h"]

    # Determine alt season signal
    if btc_dom < 40:
        signal = "🚀 ALT SEASON"
        signal_msg = "BTC dominance low - alts outperforming"
    elif btc_dom > 55:
        signal = "🔶 BTC SEASON"
        signal_msg = "BTC dominance high - alts underperforming"
    else:
        signal = "⚖️ BALANCED"
        signal_msg = "Market in equilibrium"

    trend_emoji = "📈" if cap_change > 0 else "📉"

    return f"""₿ <b>Market Dominance</b>

<b>BTC:</b> {btc_dom:.1f}%
<b>ETH:</b> {eth_dom:.1f}%
<b>Others:</b> {100 - btc_dom - eth_dom:.1f}%

{trend_emoji} <b>Total Market Cap:</b> ${total_cap/1e12:.2f}T ({cap_change:+.1f}%)

<b>Signal:</b> {signal}
<i>{signal_msg}</i>"""


def get_tvl_status() -> str:
    """Get formatted Solana TVL for Telegram"""
    data = fetch_solana_tvl()

    if not data:
        return "Could not fetch TVL data."

    tvl = data["tvl"]
    change_1d = data.get("change_1d", 0) or 0
    change_7d = data.get("change_7d", 0) or 0

    # Determine signal
    if change_1d > 3:
        signal = "BULLISH"
        signal_emoji = "🟢"
        msg = "Money flowing into Solana DeFi"
    elif change_1d < -3:
        signal = "BEARISH"
        signal_emoji = "🔴"
        msg = "Money leaving Solana DeFi"
    else:
        signal = "NEUTRAL"
        signal_emoji = "⚪"
        msg = "Stable TVL"

    trend_emoji = "📈" if change_1d > 0 else "📉"

    return f"""🔒 <b>Solana TVL (DeFiLlama)</b>

<b>Total Value Locked:</b> ${tvl/1e9:.2f}B

{trend_emoji} <b>24h Change:</b> {change_1d:+.1f}%
<b>7d Change:</b> {change_7d:+.1f}%

<b>Signal:</b> {signal_emoji} {signal}
<i>{msg}</i>"""


def get_gainers_status() -> str:
    """Get formatted top gainers/losers for Telegram"""
    data = fetch_top_gainers()

    if not data:
        return "Could not fetch market data."

    lines = ["🏆 <b>Top Gainers (24h)</b>\n"]

    for coin in data["gainers"]:
        lines.append(f"🟢 <b>{coin['symbol']}</b> +{coin['change_24h']:.1f}% (${coin['price']:,.2f})")

    lines.append("\n📉 <b>Top Losers (24h)</b>\n")

    for coin in data["losers"]:
        lines.append(f"🔴 <b>{coin['symbol']}</b> {coin['change_24h']:.1f}% (${coin['price']:,.2f})")

    lines.append("\n<i>Top 100 by market cap</i>")

    return "\n".join(lines)


def update_tvl_data():
    """Update TVL data for AI context"""
    data = fetch_solana_tvl()
    if not data:
        return

    change_1d = data.get("change_1d", 0) or 0
    tvl = data.get("tvl", 0)

    if change_1d > 3:
        signal = "BULLISH"
        message = f"Solana TVL up {change_1d:.1f}% - money flowing in (${tvl/1e9:.1f}B)"
    elif change_1d < -3:
        signal = "BEARISH"
        message = f"Solana TVL down {abs(change_1d):.1f}% - money flowing out (${tvl/1e9:.1f}B)"
    else:
        signal = "NEUTRAL"
        message = f"Solana TVL stable at ${tvl/1e9:.1f}B"

    AGENT_DATA["tvl"]["signal"] = signal
    AGENT_DATA["tvl"]["message"] = message
    AGENT_DATA["tvl"]["updated"] = datetime.now()

    print(f"TVL update: {signal} - {message}")


def update_dominance_data():
    """Update BTC dominance data for AI context"""
    data = fetch_btc_dominance()
    if not data:
        return

    btc_dom = data.get("btc_dominance", 50)

    if btc_dom < 40:
        signal = "BULLISH"  # Alt season = good for SOL
        message = f"Alt season - BTC dominance low ({btc_dom:.1f}%)"
    elif btc_dom > 55:
        signal = "BEARISH"  # BTC season = bad for alts
        message = f"BTC season - dominance high ({btc_dom:.1f}%), alts underperforming"
    else:
        signal = "NEUTRAL"
        message = f"BTC dominance balanced at {btc_dom:.1f}%"

    AGENT_DATA["dominance"]["signal"] = signal
    AGENT_DATA["dominance"]["message"] = message
    AGENT_DATA["dominance"]["updated"] = datetime.now()

    print(f"Dominance update: {signal} - {message}")


# ============================================================================
# DEFILLAMA DATA FEEDS (Free, no API key)
# ============================================================================

def fetch_dex_volume() -> dict:
    """Fetch Solana DEX trading volume from DeFiLlama (FREE)"""
    try:
        url = "https://api.llama.fi/overview/dexs/solana"
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            print(f"DeFiLlama DEX API error: {response.status_code}")
            return None

        data = response.json()

        # Get total 24h volume and change
        total_24h = data.get("total24h", 0)
        total_48h_to_24h = data.get("total48hto24h", 0)
        change_1d = data.get("change_1d", 0)

        # Get top DEXes
        protocols = data.get("protocols", [])
        top_dexes = []
        for p in sorted(protocols, key=lambda x: x.get("total24h", 0) or 0, reverse=True)[:5]:
            top_dexes.append({
                "name": p.get("name", "Unknown"),
                "volume_24h": p.get("total24h", 0),
                "change_1d": p.get("change_1d", 0)
            })

        return {
            "total_24h": total_24h,
            "change_1d": change_1d,
            "top_dexes": top_dexes,
            "timestamp": datetime.now()
        }

    except Exception as e:
        print(f"Error fetching DEX volume: {e}")
        return None


def fetch_defi_yields() -> list:
    """Fetch best Solana DeFi yields from DeFiLlama (FREE)"""
    try:
        url = "https://yields.llama.fi/pools"
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            print(f"DeFiLlama Yields API error: {response.status_code}")
            return None

        data = response.json()
        pools = data.get("data", [])

        # Filter for Solana pools with good APY
        solana_pools = [p for p in pools if p.get("chain", "").lower() == "solana" and p.get("apy", 0) > 1]

        # Sort by APY
        solana_pools.sort(key=lambda x: x.get("apy", 0), reverse=True)

        top_yields = []
        for p in solana_pools[:10]:
            top_yields.append({
                "pool": p.get("symbol", "Unknown"),
                "project": p.get("project", "Unknown"),
                "apy": p.get("apy", 0),
                "tvl": p.get("tvlUsd", 0),
                "apy_base": p.get("apyBase", 0),
                "apy_reward": p.get("apyReward", 0)
            })

        return top_yields

    except Exception as e:
        print(f"Error fetching yields: {e}")
        return None


def fetch_stablecoin_flows() -> dict:
    """Fetch Solana stablecoin flows from DeFiLlama (FREE)"""
    try:
        url = "https://stablecoins.llama.fi/stablecoincharts/solana"
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            print(f"DeFiLlama Stablecoins API error: {response.status_code}")
            return None

        data = response.json()

        if not data or len(data) < 2:
            return None

        # Get latest and previous data points
        latest = data[-1]
        previous = data[-2] if len(data) > 1 else latest
        week_ago = data[-7] if len(data) > 7 else data[0]

        # Calculate total stablecoins
        total_now = sum(v.get("circulating", {}).get("peggedUSD", 0) for v in [latest])
        total_prev = sum(v.get("circulating", {}).get("peggedUSD", 0) for v in [previous])
        total_week = sum(v.get("circulating", {}).get("peggedUSD", 0) for v in [week_ago])

        # Get individual stablecoin amounts
        stables = latest.get("totalCirculating", {}).get("peggedUSD", 0)

        change_1d = ((total_now - total_prev) / total_prev * 100) if total_prev > 0 else 0
        change_7d = ((total_now - total_week) / total_week * 100) if total_week > 0 else 0

        return {
            "total_usd": stables,
            "change_1d": change_1d,
            "change_7d": change_7d,
            "timestamp": datetime.now()
        }

    except Exception as e:
        print(f"Error fetching stablecoin flows: {e}")
        return None


def fetch_exchange_volumes() -> list:
    """Fetch top exchange volumes from CoinGecko (FREE)"""
    try:
        url = "https://api.coingecko.com/api/v3/exchanges"
        params = {"per_page": 10}
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"CoinGecko Exchanges API error: {response.status_code}")
            return None

        exchanges = response.json()

        result = []
        for ex in exchanges[:10]:
            result.append({
                "name": ex.get("name", "Unknown"),
                "volume_24h_btc": ex.get("trade_volume_24h_btc", 0),
                "trust_score": ex.get("trust_score", 0),
                "year_established": ex.get("year_established")
            })

        return result

    except Exception as e:
        print(f"Error fetching exchange volumes: {e}")
        return None


# ============================================================================
# BIRDEYE DATA FEEDS (Requires API key)
# ============================================================================

def fetch_birdeye_token_overview(token_address: str) -> dict:
    """Fetch detailed token data from Birdeye"""
    if not BIRDEYE_API_KEY:
        return None

    try:
        url = f"https://public-api.birdeye.so/defi/token_overview?address={token_address}"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            print(f"Birdeye token overview error: {response.status_code}")
            return None

        data = response.json()
        if not data.get("success"):
            return None

        token = data.get("data", {})
        return {
            "price": token.get("price", 0),
            "price_change_24h": token.get("priceChange24hPercent", 0),
            "volume_24h": token.get("v24hUSD", 0),
            "volume_change_24h": token.get("v24hChangePercent", 0),
            "liquidity": token.get("liquidity", 0),
            "mc": token.get("mc", 0),
            "holder": token.get("holder", 0),
            "trade_24h": token.get("trade24h", 0),
            "buy_24h": token.get("buy24h", 0),
            "sell_24h": token.get("sell24h", 0),
            "timestamp": datetime.now()
        }

    except Exception as e:
        print(f"Error fetching Birdeye overview: {e}")
        return None


def fetch_birdeye_trades(token_address: str, limit: int = 20) -> list:
    """Fetch recent trades from Birdeye"""
    if not BIRDEYE_API_KEY:
        return None

    try:
        url = f"https://public-api.birdeye.so/defi/txs/token?address={token_address}&tx_type=swap&limit={limit}"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        if not data.get("success"):
            return None

        trades = data.get("data", {}).get("items", [])
        return trades

    except Exception as e:
        print(f"Error fetching Birdeye trades: {e}")
        return None


# ============================================================================
# HELIUS DATA FEEDS (Requires API key)
# ============================================================================

def fetch_helius_whale_transactions(min_sol: float = 100) -> list:
    """Fetch large SOL transactions from Helius using free-tier RPC"""
    if not HELIUS_API_KEY:
        return None

    try:
        # Use Helius RPC endpoint (free tier compatible)
        helius_rpc = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

        # Get recent signatures for a known whale wallet or use getRecentBlockhash
        # For simplicity, we'll get recent confirmed signatures
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",  # Known large wallet
                {"limit": 20}
            ]
        }

        response = requests.post(helius_rpc, json=payload, timeout=15)

        if response.status_code != 200:
            print(f"Helius RPC error: {response.status_code}")
            return None

        data = response.json()
        signatures = data.get("result", [])

        if not signatures:
            return []

        # Get transaction details for each signature
        whales = []
        for sig_info in signatures[:10]:
            sig = sig_info.get("signature")
            if not sig:
                continue

            # Get parsed transaction
            tx_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    sig,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
                ]
            }

            tx_response = requests.post(helius_rpc, json=tx_payload, timeout=10)
            if tx_response.status_code != 200:
                continue

            tx_data = tx_response.json().get("result")
            if not tx_data:
                continue

            # Look for large SOL transfers in pre/post balances
            meta = tx_data.get("meta", {})
            pre_balances = meta.get("preBalances", [])
            post_balances = meta.get("postBalances", [])

            if pre_balances and post_balances:
                # Calculate the largest balance change
                for i, (pre, post) in enumerate(zip(pre_balances, post_balances)):
                    change_lamports = abs(post - pre)
                    change_sol = change_lamports / 1_000_000_000

                    if change_sol >= min_sol:
                        whales.append({
                            "signature": sig[:16] + "...",
                            "amount_sol": change_sol,
                            "from": "whale",
                            "to": "transfer",
                            "timestamp": tx_data.get("blockTime", 0)
                        })
                        break

        return whales[:10]

    except Exception as e:
        print(f"Error fetching Helius whale data: {e}")
        return None


def fetch_helius_token_holders(token_address: str) -> dict:
    """Fetch token holder distribution from Helius"""
    if not HELIUS_API_KEY:
        return None

    try:
        url = f"https://api.helius.xyz/v0/token-metadata?api-key={HELIUS_API_KEY}"
        payload = {"mintAccounts": [token_address]}
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        if data and len(data) > 0:
            token = data[0]
            return {
                "name": token.get("onChainAccountInfo", {}).get("metadata", {}).get("name", "Unknown"),
                "symbol": token.get("onChainAccountInfo", {}).get("metadata", {}).get("symbol", "???"),
                "supply": token.get("onChainAccountInfo", {}).get("tokenAmount", {}).get("uiAmount", 0)
            }
        return None

    except Exception as e:
        print(f"Error fetching Helius holders: {e}")
        return None


# ============================================================================
# UPDATE FUNCTIONS FOR NEW FEEDS
# ============================================================================

def update_dex_volume_data():
    """Update DEX volume data for AI context"""
    data = fetch_dex_volume()
    if not data:
        return

    volume = data.get("total_24h", 0)
    change = data.get("change_1d", 0)

    if change > 20:
        signal = "BULLISH"
        message = f"Solana DEX volume surging +{change:.0f}% (${volume/1e9:.2f}B)"
    elif change > 5:
        signal = "NEUTRAL"
        message = f"Solana DEX volume up {change:.0f}% (${volume/1e9:.2f}B)"
    elif change < -20:
        signal = "BEARISH"
        message = f"Solana DEX volume dropping {change:.0f}% (${volume/1e9:.2f}B)"
    else:
        signal = "NEUTRAL"
        message = f"Solana DEX volume: ${volume/1e9:.2f}B ({change:+.0f}%)"

    AGENT_DATA["dex_volume"]["signal"] = signal
    AGENT_DATA["dex_volume"]["message"] = message
    AGENT_DATA["dex_volume"]["updated"] = datetime.now()
    AGENT_DATA["dex_volume"]["data"] = data

    print(f"DEX Volume update: {signal} - {message}")


def update_yields_data():
    """Update yields data for AI context"""
    yields = fetch_defi_yields()
    if not yields:
        return

    # Get average APY of top yields
    avg_apy = sum(y.get("apy", 0) for y in yields[:5]) / 5 if yields else 0
    max_apy = max(y.get("apy", 0) for y in yields) if yields else 0

    if avg_apy > 20:
        signal = "BULLISH"
        message = f"High DeFi yields on Solana - avg {avg_apy:.1f}% APY"
    elif avg_apy > 10:
        signal = "NEUTRAL"
        message = f"Moderate DeFi yields - avg {avg_apy:.1f}% APY"
    else:
        signal = "NEUTRAL"
        message = f"Low DeFi yields - avg {avg_apy:.1f}% APY"

    AGENT_DATA["yields"]["signal"] = signal
    AGENT_DATA["yields"]["message"] = message
    AGENT_DATA["yields"]["updated"] = datetime.now()
    AGENT_DATA["yields"]["data"] = yields

    print(f"Yields update: {signal} - {message}")


def update_stablecoin_data():
    """Update stablecoin flow data for AI context"""
    data = fetch_stablecoin_flows()
    if not data:
        return

    total = data.get("total_usd", 0)
    change_1d = data.get("change_1d", 0)
    change_7d = data.get("change_7d", 0)

    if change_1d > 2:
        signal = "BULLISH"
        message = f"Stablecoins flowing into Solana +{change_1d:.1f}% (${total/1e9:.2f}B)"
    elif change_1d < -2:
        signal = "BEARISH"
        message = f"Stablecoins leaving Solana {change_1d:.1f}% (${total/1e9:.2f}B)"
    else:
        signal = "NEUTRAL"
        message = f"Stablecoin supply stable at ${total/1e9:.2f}B"

    AGENT_DATA["stablecoins"]["signal"] = signal
    AGENT_DATA["stablecoins"]["message"] = message
    AGENT_DATA["stablecoins"]["updated"] = datetime.now()
    AGENT_DATA["stablecoins"]["data"] = data

    print(f"Stablecoin update: {signal} - {message}")


def update_whale_data():
    """Update whale transaction data for AI context"""
    if not HELIUS_API_KEY:
        return

    whales = fetch_helius_whale_transactions(min_sol=500)
    if not whales:
        return

    total_volume = sum(w.get("amount_sol", 0) for w in whales)
    count = len(whales)

    if count >= 5 and total_volume > 5000:
        signal = "BULLISH" if total_volume > 10000 else "NEUTRAL"
        message = f"Whale activity: {count} large txs ({total_volume:.0f} SOL moved)"
    else:
        signal = "NEUTRAL"
        message = f"Low whale activity: {count} large txs"

    AGENT_DATA["whales"]["signal"] = signal
    AGENT_DATA["whales"]["message"] = message
    AGENT_DATA["whales"]["updated"] = datetime.now()
    AGENT_DATA["whales"]["data"] = whales

    print(f"Whale update: {signal} - {message}")


# ============================================================================
# STATUS FUNCTIONS FOR NEW FEEDS
# ============================================================================

def get_dex_volume_status() -> str:
    """Get formatted DEX volume for Telegram"""
    data = fetch_dex_volume()

    if not data:
        return "Could not fetch DEX volume data."

    volume = data.get("total_24h", 0)
    change = data.get("change_1d", 0)
    top_dexes = data.get("top_dexes", [])

    trend_emoji = "📈" if change > 0 else "📉"

    lines = [f"""{trend_emoji} <b>Solana DEX Volume (24h)</b>

<b>Total Volume:</b> ${volume/1e9:.2f}B
<b>24h Change:</b> {change:+.1f}%

<b>Top DEXes:</b>"""]

    for dex in top_dexes:
        dex_vol = dex.get("volume_24h", 0)
        dex_change = dex.get("change_1d", 0)
        lines.append(f"• {dex['name']}: ${dex_vol/1e6:.1f}M ({dex_change:+.0f}%)")

    lines.append("\n<i>Source: DeFiLlama</i>")
    return "\n".join(lines)


def get_yields_status() -> str:
    """Get formatted DeFi yields for Telegram"""
    yields = fetch_defi_yields()

    if not yields:
        return "Could not fetch yield data."

    lines = ["🌾 <b>Top Solana DeFi Yields</b>\n"]

    for y in yields[:7]:
        pool = y.get("pool", "Unknown")
        project = y.get("project", "Unknown")
        apy = y.get("apy", 0)
        tvl = y.get("tvl", 0)

        lines.append(f"• <b>{pool}</b> ({project})")
        lines.append(f"  APY: {apy:.1f}% | TVL: ${tvl/1e6:.1f}M")

    lines.append("\n<i>Source: DeFiLlama</i>")
    return "\n".join(lines)


def get_stablecoin_status() -> str:
    """Get formatted stablecoin flows for Telegram"""
    data = fetch_stablecoin_flows()

    if not data:
        return "Could not fetch stablecoin data."

    total = data.get("total_usd", 0)
    change_1d = data.get("change_1d", 0)
    change_7d = data.get("change_7d", 0)

    trend_emoji = "📈" if change_1d > 0 else "📉"

    # Determine signal
    if change_1d > 2:
        signal = "🟢 INFLOWS"
        msg = "Capital entering Solana ecosystem"
    elif change_1d < -2:
        signal = "🔴 OUTFLOWS"
        msg = "Capital leaving Solana ecosystem"
    else:
        signal = "⚪ STABLE"
        msg = "Stablecoin supply unchanged"

    return f"""{trend_emoji} <b>Solana Stablecoin Flows</b>

<b>Total Stablecoins:</b> ${total/1e9:.2f}B

<b>24h Change:</b> {change_1d:+.2f}%
<b>7d Change:</b> {change_7d:+.2f}%

<b>Signal:</b> {signal}
<i>{msg}</i>

<i>Source: DeFiLlama</i>"""


def get_exchange_status() -> str:
    """Get formatted exchange volumes for Telegram"""
    exchanges = fetch_exchange_volumes()

    if not exchanges:
        return "Could not fetch exchange data."

    lines = ["🏦 <b>Top Crypto Exchanges (24h Volume)</b>\n"]

    for i, ex in enumerate(exchanges[:10], 1):
        name = ex.get("name", "Unknown")
        vol = ex.get("volume_24h_btc", 0)
        trust = ex.get("trust_score", 0)
        trust_bar = "🟢" * min(trust, 10) if trust else "⚪"

        lines.append(f"{i}. <b>{name}</b>")
        lines.append(f"   Vol: {vol:,.0f} BTC | Trust: {trust_bar}")

    lines.append("\n<i>Source: CoinGecko</i>")
    return "\n".join(lines)


def get_birdeye_status(token: str = "SOL") -> str:
    """Get formatted Birdeye token data for Telegram"""
    if not BIRDEYE_API_KEY:
        return "Birdeye API key not configured.\n\nGet your free key at: birdeye.so"

    token_address = TOKENS.get(token.upper(), SOL_ADDRESS)
    data = fetch_birdeye_token_overview(token_address)

    if not data:
        return "Could not fetch Birdeye data."

    price = data.get("price", 0)
    change = data.get("price_change_24h", 0)
    volume = data.get("volume_24h", 0)
    liquidity = data.get("liquidity", 0)
    trades = data.get("trade_24h", 0)
    buys = data.get("buy_24h", 0)
    sells = data.get("sell_24h", 0)

    buy_ratio = (buys / (buys + sells) * 100) if (buys + sells) > 0 else 50
    trend_emoji = "📈" if change > 0 else "📉"

    return f"""{trend_emoji} <b>Birdeye: {token}</b>

<b>Price:</b> ${price:,.4f} ({change:+.1f}%)
<b>24h Volume:</b> ${volume/1e6:.2f}M
<b>Liquidity:</b> ${liquidity/1e6:.2f}M

<b>Trading Activity:</b>
• Total Trades: {trades:,}
• Buys: {buys:,} ({buy_ratio:.0f}%)
• Sells: {sells:,} ({100-buy_ratio:.0f}%)

<i>Source: Birdeye</i>"""


def get_whale_status() -> str:
    """Get formatted whale activity for Telegram"""
    if not HELIUS_API_KEY:
        return "Helius API key not configured.\n\nGet your free key at: helius.dev"

    whales = fetch_helius_whale_transactions(min_sol=100)

    if not whales:
        return "No large whale transactions found recently."

    total_volume = sum(w.get("amount_sol", 0) for w in whales)

    lines = ["🐋 <b>Recent Whale Transactions</b>\n"]
    lines.append(f"<b>Total Volume:</b> {total_volume:,.0f} SOL\n")

    for w in whales[:7]:
        amount = w.get("amount_sol", 0)
        from_addr = w.get("from", "???")
        to_addr = w.get("to", "???")
        lines.append(f"• <b>{amount:,.0f} SOL</b>")
        lines.append(f"  {from_addr} → {to_addr}")

    lines.append("\n<i>Source: Helius</i>")
    return "\n".join(lines)


# ============================================================================
# POSITION & RISK MANAGEMENT
# ============================================================================

def open_position(token: str, amount: float, entry_price: float,
                  stop_loss_pct: float = None, take_profit_pct: float = None) -> dict:
    """Open/add to a tracked position with stop loss and take profit"""
    global POSITIONS

    sl_pct = stop_loss_pct if stop_loss_pct is not None else DEFAULT_STOP_LOSS_PCT
    tp_pct = take_profit_pct if take_profit_pct is not None else DEFAULT_TAKE_PROFIT_PCT

    stop_loss_price = entry_price * (1 - sl_pct / 100)
    take_profit_price = entry_price * (1 + tp_pct / 100)

    position = {
        "token": token.upper(),
        "amount": amount,
        "entry_price": entry_price,
        "stop_loss_pct": sl_pct,
        "take_profit_pct": tp_pct,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "high_price": entry_price,  # For trailing stop
        "opened_at": datetime.now(),
        "trailing_stop": TRAILING_STOP_ENABLED
    }

    POSITIONS[token.upper()] = position
    print(f"Position opened: {amount} {token} @ ${entry_price:.4f} | SL: ${stop_loss_price:.4f} | TP: ${take_profit_price:.4f}")

    return position


def close_position(token: str) -> dict:
    """Close/remove a tracked position"""
    global POSITIONS

    token = token.upper()
    if token in POSITIONS:
        position = POSITIONS.pop(token)
        print(f"Position closed: {token}")
        return position
    return None


def update_position_high(token: str, current_price: float):
    """Update the high price for trailing stop"""
    global POSITIONS

    token = token.upper()
    if token in POSITIONS:
        position = POSITIONS[token]
        if current_price > position["high_price"]:
            position["high_price"] = current_price

            # Update trailing stop if enabled
            if position.get("trailing_stop"):
                new_stop = current_price * (1 - TRAILING_STOP_PCT / 100)
                if new_stop > position["stop_loss_price"]:
                    position["stop_loss_price"] = new_stop
                    print(f"Trailing stop updated for {token}: ${new_stop:.4f}")


def check_position_triggers(token: str, current_price: float) -> dict:
    """Check if stop loss or take profit has been triggered"""
    token = token.upper()

    if token not in POSITIONS:
        return None

    position = POSITIONS[token]
    entry = position["entry_price"]
    sl_price = position["stop_loss_price"]
    tp_price = position["take_profit_price"]

    pnl_pct = ((current_price - entry) / entry) * 100
    pnl_usd = (current_price - entry) * position["amount"]

    result = {
        "triggered": None,
        "current_price": current_price,
        "entry_price": entry,
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "position": position
    }

    # Check stop loss
    if current_price <= sl_price:
        result["triggered"] = "STOP_LOSS"
        return result

    # Check take profit
    if current_price >= tp_price:
        result["triggered"] = "TAKE_PROFIT"
        return result

    # Update high for trailing stop
    update_position_high(token, current_price)

    return result


def get_position_status(token: str = None) -> str:
    """Get formatted position status for Telegram"""
    if not POSITIONS:
        return """📊 <b>No Open Positions</b>

You don't have any tracked positions.

When you buy with /buy, positions are automatically tracked with:
• Stop Loss: {sl}%
• Take Profit: {tp}%

Use /sl or /tp to adjust defaults.""".format(sl=DEFAULT_STOP_LOSS_PCT, tp=DEFAULT_TAKE_PROFIT_PCT)

    lines = ["📊 <b>Open Positions</b>\n"]

    tokens_to_show = [token.upper()] if token else POSITIONS.keys()

    for tok in tokens_to_show:
        if tok not in POSITIONS:
            continue

        pos = POSITIONS[tok]
        current_price = get_token_price(tok)
        entry = pos["entry_price"]
        amount = pos["amount"]

        pnl_pct = ((current_price - entry) / entry) * 100 if entry > 0 else 0
        pnl_usd = (current_price - entry) * amount

        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        value_usd = current_price * amount

        lines.append(f"<b>{tok}</b>")
        lines.append(f"• Amount: {amount:.4f} (${value_usd:.2f})")
        lines.append(f"• Entry: ${entry:.4f}")
        lines.append(f"• Current: ${current_price:.4f}")
        lines.append(f"• P&L: {pnl_emoji} {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
        lines.append(f"• Stop Loss: ${pos['stop_loss_price']:.4f} (-{pos['stop_loss_pct']:.1f}%)")
        lines.append(f"• Take Profit: ${pos['take_profit_price']:.4f} (+{pos['take_profit_pct']:.1f}%)")

        if pos.get("trailing_stop"):
            lines.append(f"• Trailing: ON (High: ${pos['high_price']:.4f})")

        lines.append("")

    return "\n".join(lines)


def set_stop_loss(token: str, stop_loss_pct: float = None, stop_loss_price: float = None) -> bool:
    """Set stop loss for an existing position"""
    global POSITIONS

    token = token.upper()
    if token not in POSITIONS:
        return False

    position = POSITIONS[token]

    if stop_loss_price:
        position["stop_loss_price"] = stop_loss_price
        position["stop_loss_pct"] = ((position["entry_price"] - stop_loss_price) / position["entry_price"]) * 100
    elif stop_loss_pct:
        position["stop_loss_pct"] = stop_loss_pct
        position["stop_loss_price"] = position["entry_price"] * (1 - stop_loss_pct / 100)

    return True


def set_take_profit(token: str, take_profit_pct: float = None, take_profit_price: float = None) -> bool:
    """Set take profit for an existing position"""
    global POSITIONS

    token = token.upper()
    if token not in POSITIONS:
        return False

    position = POSITIONS[token]

    if take_profit_price:
        position["take_profit_price"] = take_profit_price
        position["take_profit_pct"] = ((take_profit_price - position["entry_price"]) / position["entry_price"]) * 100
    elif take_profit_pct:
        position["take_profit_pct"] = take_profit_pct
        position["take_profit_price"] = position["entry_price"] * (1 + take_profit_pct / 100)

    return True


# ============================================================================
# TELEGRAM FUNCTIONS
# ============================================================================

def send_telegram(message: str) -> bool:
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Telegram disabled] {message}")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def check_telegram_commands() -> str:
    """Check for incoming Telegram commands"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    try:
        # Track last update
        data_dir = Path("/tmp")
        update_file = data_dir / "telegram_last_update.txt"
        last_update_id = 0
        if update_file.exists():
            try:
                last_update_id = int(update_file.read_text().strip())
            except:
                pass

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 1}
        response = requests.get(url, params=params, timeout=5)

        if response.status_code != 200:
            return None

        updates = response.json().get("result", [])

        for update in updates:
            update_id = update.get("update_id", 0)
            message = update.get("message", {})
            text = message.get("text", "").strip().lower()
            chat_id = str(message.get("chat", {}).get("id", ""))

            # Save update ID
            update_file.write_text(str(update_id))

            # Only respond to authorized chat
            if chat_id == TELEGRAM_CHAT_ID:
                return text

        return None
    except:
        return None

# ============================================================================
# SOLANA/JUPITER FUNCTIONS
# ============================================================================

# CoinGecko IDs for tokens
COINGECKO_IDS = {
    "SOL": "solana",
    "USDC": "usd-coin",
    "BONK": "bonk",
    "WIF": "dogwifcoin",
}

def get_sol_price() -> float:
    """Get SOL price from CoinGecko (more reliable than Jupiter API)"""
    try:
        # Try CoinGecko first (free, no API key needed)
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            price = data.get("solana", {}).get("usd", 0)
            if price > 0:
                return float(price)
    except Exception as e:
        print(f"CoinGecko error: {e}")

    # Fallback to Birdeye if available
    if BIRDEYE_API_KEY:
        try:
            url = f"https://public-api.birdeye.so/defi/price?address={SOL_ADDRESS}"
            headers = {"X-API-KEY": BIRDEYE_API_KEY}
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            if data.get("success"):
                return float(data.get("data", {}).get("value", 0))
        except Exception as e:
            print(f"Birdeye price error: {e}")

    return 0

def get_token_price(symbol: str) -> float:
    """Get token price from CoinGecko or Birdeye"""
    try:
        # Try CoinGecko first
        cg_id = COINGECKO_IDS.get(symbol)
        if cg_id:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                price = data.get(cg_id, {}).get("usd", 0)
                if price > 0:
                    return float(price)
    except Exception as e:
        print(f"CoinGecko error for {symbol}: {e}")

    # Fallback to Birdeye
    if BIRDEYE_API_KEY:
        try:
            mint = TOKENS.get(symbol, symbol)
            url = f"https://public-api.birdeye.so/defi/price?address={mint}"
            headers = {"X-API-KEY": BIRDEYE_API_KEY}
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            if data.get("success"):
                return float(data.get("data", {}).get("value", 0))
        except Exception as e:
            print(f"Birdeye price error for {symbol}: {e}")

    return 0

def get_jupiter_swap_url(input_token: str, output_token: str, amount: float = None) -> str:
    """Generate Jupiter swap URL for easy trading"""
    input_mint = TOKENS.get(input_token.upper(), USDC_ADDRESS)
    output_mint = TOKENS.get(output_token.upper(), SOL_ADDRESS)

    # Handle common aliases
    if input_token.upper() == "USDC":
        input_mint = USDC_ADDRESS
    if output_token.upper() == "USDC":
        output_mint = USDC_ADDRESS

    base_url = f"https://jup.ag/swap/{input_mint}-{output_mint}"
    return base_url

def get_birdeye_candles(token_address: str, interval: str = "1H", limit: int = 50) -> list:
    """Get OHLCV candles from Birdeye API"""
    if not BIRDEYE_API_KEY:
        print("Birdeye API key not configured")
        return []

    try:
        # Birdeye time format
        end_time = int(time.time())

        # Calculate start time based on interval
        if interval == "1H":
            start_time = end_time - (limit * 3600)
        elif interval == "15m":
            start_time = end_time - (limit * 900)
        else:
            start_time = end_time - (limit * 3600)

        url = f"https://public-api.birdeye.so/defi/ohlcv?address={token_address}&type={interval}&time_from={start_time}&time_to={end_time}"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()

        if data.get("success"):
            return data.get("data", {}).get("items", [])
        return []
    except Exception as e:
        print(f"Candles error: {e}")
        return []

def get_wallet_balance() -> dict:
    """Get wallet SOL and token balances"""
    if not SOLANA_PRIVATE_KEY:
        return {"sol": 0, "usdc": 0, "total_usd": 0}

    try:
        from solders.keypair import Keypair
        keypair = Keypair.from_base58_string(SOLANA_PRIVATE_KEY)
        address = str(keypair.pubkey())

        # Get SOL balance
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }
        response = requests.post(RPC_ENDPOINT, json=payload, timeout=10)
        data = response.json()
        sol_lamports = data.get("result", {}).get("value", 0)
        sol_balance = sol_lamports / 1_000_000_000  # Convert lamports to SOL

        # Get SOL price
        sol_price = get_sol_price()
        sol_usd = sol_balance * sol_price

        # Get USDC balance (SPL token)
        usdc_balance = get_token_balance(address, USDC_ADDRESS)

        return {
            "sol": sol_balance,
            "sol_usd": sol_usd,
            "usdc": usdc_balance,
            "total_usd": sol_usd + usdc_balance,
            "address": address
        }
    except Exception as e:
        print(f"Balance error: {e}")
        return {"sol": 0, "usdc": 0, "total_usd": 0}

def get_token_balance(wallet_address: str, token_mint: str) -> float:
    """Get SPL token balance for wallet"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_address,
                {"mint": token_mint},
                {"encoding": "jsonParsed"}
            ]
        }
        response = requests.post(RPC_ENDPOINT, json=payload, timeout=10)
        data = response.json()

        accounts = data.get("result", {}).get("value", [])
        if accounts:
            token_amount = accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {})
            return float(token_amount.get("uiAmount", 0))
        return 0
    except Exception as e:
        print(f"Token balance error: {e}")
        return 0

def execute_swap(input_mint: str, output_mint: str, amount: int) -> dict:
    """Execute a swap via Jupiter - using direct HTTP calls (no solana SDK needed)"""
    if not SOLANA_PRIVATE_KEY:
        return {"success": False, "error": "No private key configured"}

    try:
        import base64
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction

        keypair = Keypair.from_base58_string(SOLANA_PRIVATE_KEY)

        print(f"Executing swap: {input_mint[:8]}... -> {output_mint[:8]}...")
        print(f"Amount: {amount}")

        # Get quote from Jupiter
        quote_url = f"https://lite-api.jup.ag/swap/v1/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps={SLIPPAGE_BPS}"
        print(f"Getting quote...")
        quote_response = requests.get(quote_url, timeout=15)
        quote = quote_response.json()

        if "error" in quote:
            return {"success": False, "error": f"Quote error: {quote.get('error')}"}

        # Get expected output
        out_amount = int(quote.get("outAmount", 0))
        print(f"Expected output: {out_amount}")

        # Get swap transaction from Jupiter
        print("Getting swap transaction...")
        swap_response = requests.post(
            "https://lite-api.jup.ag/swap/v1/swap",
            headers={"Content-Type": "application/json"},
            json={
                "quoteResponse": quote,
                "userPublicKey": str(keypair.pubkey()),
                "wrapUnwrapSOL": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto"
            },
            timeout=30
        )
        swap_data = swap_response.json()

        if "error" in swap_data:
            return {"success": False, "error": f"Swap error: {swap_data.get('error')}"}

        if "swapTransaction" not in swap_data:
            return {"success": False, "error": "No transaction returned from Jupiter"}

        # Decode and sign transaction
        print("Signing transaction...")
        tx_bytes = base64.b64decode(swap_data["swapTransaction"])
        tx = VersionedTransaction.from_bytes(tx_bytes)

        # Sign the transaction using solders
        signed_tx = VersionedTransaction(tx.message, [keypair])
        signed_tx_bytes = bytes(signed_tx)
        signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode('utf-8')

        # Send transaction using direct HTTP call to Solana RPC (no SDK needed!)
        print("Sending transaction...")
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                signed_tx_base64,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 3
                }
            ]
        }

        rpc_response = requests.post(RPC_ENDPOINT, json=rpc_payload, timeout=30)
        rpc_result = rpc_response.json()

        # Check result
        if "result" in rpc_result:
            tx_sig = rpc_result["result"]
            print(f"Transaction sent: {tx_sig}")
            return {
                "success": True,
                "signature": tx_sig,
                "out_amount": out_amount,
                "url": f"https://solscan.io/tx/{tx_sig}"
            }
        elif "error" in rpc_result:
            error_msg = rpc_result["error"].get("message", str(rpc_result["error"]))
            return {"success": False, "error": f"RPC error: {error_msg}"}
        else:
            return {"success": False, "error": f"Unknown RPC response: {rpc_result}"}

    except Exception as e:
        print(f"Swap error: {e}")
        return {"success": False, "error": str(e)}


def buy_token(token_symbol: str, token_amount: float) -> dict:
    """Buy a specific amount of a token using USDC"""
    token_mint = TOKENS.get(token_symbol.upper())
    if not token_mint:
        return {"success": False, "error": f"Unknown token: {token_symbol}"}

    # Get current price to calculate USDC needed
    price = get_token_price(token_symbol)
    if price <= 0:
        return {"success": False, "error": "Could not get token price"}

    # Calculate USDC needed (add 5% buffer for slippage)
    usdc_needed = token_amount * price * 1.05
    usdc_units = int(usdc_needed * 1_000_000)  # USDC has 6 decimals

    return execute_swap(USDC_ADDRESS, token_mint, usdc_units)


def sell_token(token_symbol: str, token_amount: float) -> dict:
    """Sell a token for USDC"""
    token_mint = TOKENS.get(token_symbol.upper())
    if not token_mint:
        return {"success": False, "error": f"Unknown token: {token_symbol}"}

    # Get token decimals (SOL=9, most others=varies)
    if token_symbol.upper() == "SOL":
        amount_units = int(token_amount * 1_000_000_000)  # 9 decimals
    elif token_symbol.upper() == "BONK":
        amount_units = int(token_amount * 100_000)  # 5 decimals
    elif token_symbol.upper() == "WIF":
        amount_units = int(token_amount * 1_000_000)  # 6 decimals
    elif token_symbol.upper() == "USDC":
        amount_units = int(token_amount * 1_000_000)  # 6 decimals
    else:
        amount_units = int(token_amount * 1_000_000)  # Default 6 decimals

    return execute_swap(token_mint, USDC_ADDRESS, amount_units)


def swap_tokens(from_token: str, to_token: str, amount: float) -> dict:
    """Generic swap between any two tokens"""
    from_mint = TOKENS.get(from_token.upper())
    to_mint = TOKENS.get(to_token.upper())

    if not from_mint:
        return {"success": False, "error": f"Unknown token: {from_token}"}
    if not to_mint:
        return {"success": False, "error": f"Unknown token: {to_token}"}

    # Get decimals for from_token
    if from_token.upper() == "SOL":
        amount_units = int(amount * 1_000_000_000)  # 9 decimals
    elif from_token.upper() == "BONK":
        amount_units = int(amount * 100_000)  # 5 decimals
    else:
        amount_units = int(amount * 1_000_000)  # 6 decimals (USDC, WIF, etc.)

    return execute_swap(from_mint, to_mint, amount_units)

# ============================================================================
# AI ANALYSIS
# ============================================================================

def get_agent_context() -> str:
    """Get context from external agent feeds"""
    context_parts = []

    for agent_name, data in AGENT_DATA.items():
        if data.get("signal") and data.get("updated"):
            # Only use data less than 30 minutes old
            age = datetime.now() - data["updated"]
            if age.total_seconds() < 1800:
                context_parts.append(f"- {agent_name.upper()}: {data['message']}")

    if context_parts:
        return "External Signals:\n" + "\n".join(context_parts)
    return ""

def calculate_technicals(candles: list) -> dict:
    """Calculate simple technical indicators from candles"""
    if len(candles) < 10:
        return {}

    closes = []
    for c in candles:
        close = c.get('c', c.get('close', 0))
        if close:
            closes.append(float(close))

    if len(closes) < 10:
        return {}

    # Simple Moving Averages
    sma_5 = sum(closes[-5:]) / 5
    sma_20 = sum(closes[-20:]) / min(20, len(closes)) if len(closes) >= 20 else sum(closes) / len(closes)

    # Price momentum
    current = closes[-1]
    prev_5 = closes[-6] if len(closes) > 5 else closes[0]
    momentum = ((current - prev_5) / prev_5) * 100 if prev_5 > 0 else 0

    # Trend
    trend = "BULLISH" if sma_5 > sma_20 else "BEARISH"

    # Simple RSI approximation (gains vs losses over last 14 periods)
    if len(closes) >= 14:
        gains = []
        losses = []
        for i in range(-14, 0):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))

        avg_gain = sum(gains) / 14 if gains else 0.001
        avg_loss = sum(losses) / 14 if losses else 0.001
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
    else:
        rsi = 50

    return {
        "sma_5": sma_5,
        "sma_20": sma_20,
        "momentum_5": momentum,
        "trend": trend,
        "rsi": rsi,
        "current_price": current
    }

def analyze_with_ai(symbol: str, candles: list, wallet_balance: dict = None) -> tuple:
    """Get AI trading decision using OpenAI with enhanced context"""
    if not OPENAI_KEY:
        print("OpenAI key not configured")
        return "NOTHING", 0, "No AI available"

    try:
        # Calculate technicals
        technicals = calculate_technicals(candles)

        # Get agent context
        agent_context = get_agent_context()

        # Format wallet info
        wallet_info = ""
        if wallet_balance:
            wallet_info = f"""
Current Position:
- SOL Balance: {wallet_balance.get('sol', 0):.4f} (${wallet_balance.get('sol_usd', 0):.2f})
- USDC Balance: ${wallet_balance.get('usdc', 0):.2f}
- Total Value: ${wallet_balance.get('total_usd', 0):.2f}
"""

        # Format technical analysis
        tech_info = ""
        if technicals:
            tech_info = f"""
Technical Analysis:
- Current Price: ${technicals.get('current_price', 0):.4f}
- SMA(5): ${technicals.get('sma_5', 0):.4f}
- SMA(20): ${technicals.get('sma_20', 0):.4f}
- 5-period Momentum: {technicals.get('momentum_5', 0):.2f}%
- RSI(14): {technicals.get('rsi', 50):.1f}
- Trend: {technicals.get('trend', 'NEUTRAL')}
"""

        # Format recent candles (last 10)
        candle_text = f"Recent {symbol} hourly candles:\n"
        for i, c in enumerate(candles[-10:]):
            o = c.get('o', c.get('open', 'N/A'))
            h = c.get('h', c.get('high', 'N/A'))
            l = c.get('l', c.get('low', 'N/A'))
            close = c.get('c', c.get('close', 'N/A'))
            try:
                candle_text += f"  {i+1}. O:{float(o):.4f} H:{float(h):.4f} L:{float(l):.4f} C:{float(close):.4f}\n"
            except:
                candle_text += f"  {i+1}. O:{o} H:{h} L:{l} C:{close}\n"

        prompt = f"""You are an AI trading assistant analyzing {symbol}.

{tech_info}
{candle_text}
{wallet_info}
{agent_context}

Based on this data, provide a trading recommendation.

RESPOND IN THIS EXACT FORMAT:
DECISION: [BUY/SELL/HOLD]
CONFIDENCE: [0-100]
REASON: [One sentence explanation]

Guidelines:
- BUY when: RSI < 35 (oversold), bullish trend, positive momentum
- SELL when: RSI > 70 (overbought), bearish trend, negative momentum
- HOLD when: Mixed signals, RSI between 40-60, unclear trend
- Confidence should reflect signal strength (70+ for clear signals)

Your analysis:"""

        headers = {
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a crypto trading AI. Always respond in the exact format requested: DECISION, CONFIDENCE, REASON."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 100,
            "temperature": 0.3
        }

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )

        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        # Parse response
        decision = "HOLD"
        confidence = 50
        reason = "Analysis complete"

        for line in content.split('\n'):
            line = line.strip()
            if line.upper().startswith("DECISION:"):
                decision_text = line.split(":", 1)[1].strip().upper()
                if "BUY" in decision_text:
                    decision = "BUY"
                elif "SELL" in decision_text:
                    decision = "SELL"
                else:
                    decision = "HOLD"
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    conf_text = line.split(":", 1)[1].strip().replace("%", "")
                    confidence = int(float(conf_text))
                    confidence = max(0, min(100, confidence))
                except:
                    confidence = 50
            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()

        return decision, confidence, reason

    except Exception as e:
        print(f"AI error: {e}")
        return "HOLD", 0, f"AI error: {str(e)}"

# ============================================================================
# MAIN BOT
# ============================================================================

class TelegramTradingBot:
    def __init__(self):
        self.is_paused = False
        self.running = True
        self.daily_trades = 0
        self.last_trade_date = datetime.now().date()
        self.active_token = DEFAULT_TOKEN

        # Autonomous trading settings
        self.auto_mode = False  # When True, AI can auto-execute trades
        self.auto_confirm = True  # When True, ask for confirmation before executing
        self.pending_trade = None  # {"action": "BUY", "amount": 0.01, "token": "SOL", "expires": datetime}
        self.auto_trades_today = 0

        # Full autonomous mode
        self.full_auto = FULL_AUTO_MODE  # When True, NO confirmation needed
        self.daily_pnl = 0.0  # Track daily profit/loss
        self.last_trade_time = None  # For cooldown
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        print("=" * 50)
        print("Moon Dev Telegram Trading Bot")
        print("Exchange: Solana + Jupiter DEX")
        print("=" * 50)

        # Check configuration
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("WARNING: Telegram not configured!")
        else:
            print("Telegram: OK")

        if not OPENAI_KEY:
            print("WARNING: OpenAI not configured!")
        else:
            print("OpenAI: OK")

        if not SOLANA_PRIVATE_KEY:
            print("WARNING: Solana wallet not configured!")
        else:
            print("Solana Wallet: OK")

        if not BIRDEYE_API_KEY:
            print("WARNING: Birdeye API not configured (using Jupiter for prices)")
        else:
            print("Birdeye: OK")

        print(f"Active Token: {self.active_token}")
        print(f"Check interval: {CHECK_INTERVAL_MINUTES} min")
        print("=" * 50)

        # Get wallet info
        wallet = get_wallet_balance()

        # Send startup message
        auto_status = "FULL AUTO 🤖" if self.full_auto else ("ON" if self.auto_mode else "OFF")
        send_telegram(f"""<b>Moon Dev Trading Bot Started!</b>

<b>Exchange:</b> Solana + Jupiter DEX
<b>Token:</b> {self.active_token}
<b>Interval:</b> {CHECK_INTERVAL_MINUTES} min
<b>Auto Mode:</b> {auto_status}

<b>Wallet:</b>
SOL: {wallet.get('sol', 0):.4f} (${wallet.get('sol_usd', 0):.2f})
USDC: ${wallet.get('usdc', 0):.2f}
<b>Total:</b> ${wallet.get('total_usd', 0):.2f}

<b>Risk Management:</b>
🛑 Stop Loss: {DEFAULT_STOP_LOSS_PCT}%
🎯 Take Profit: {DEFAULT_TAKE_PROFIT_PCT}%

Send /fullauto for hands-free trading
Send /help for all commands""")

    def handle_command(self, cmd: str):
        """Handle Telegram command"""
        global DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT, TRAILING_STOP_ENABLED

        if cmd == "/help" or cmd == "/start":
            auto_status = "ON" if self.auto_mode else "OFF"
            send_telegram(f"""<b>Trading Bot Commands</b>

<b>Auto Trading:</b>
/fullauto - FULL autonomous mode
/auto - Semi-auto (needs confirm)
/confirm - Confirm trade
/cancel - Cancel trade

<b>Trading:</b>
/buy [amt] [token] - Buy token
/sell [amt] [token] - Sell token
/analyze - AI analysis

<b>Market Data:</b>
/sentiment - Fear & Greed
/market - SOL price
/btc - BTC dominance
/trending - Hot coins
/gainers - Top movers

<b>DeFi Data:</b>
/dex - DEX volume
/yields - Best yields
/stables - Stablecoin flows
/tvl - Solana TVL

<b>Pro Data (API key):</b>
/birdeye - Token details
/whales - Whale activity
/exchanges - CEX volumes

<b>Risk Management:</b>
/position - View positions
/sl [%] - Set stop loss
/tp [%] - Set take profit
/close [token] - Close position
/trailing - Toggle trailing

<b>Controls:</b>
/status - Bot status
/pause /resume
/data - All data feeds

<i>SL/TP auto-execute when triggered!</i>""")

        elif cmd == "/status":
            wallet = get_wallet_balance()
            status = "PAUSED" if self.is_paused else "ACTIVE"
            auto_status = "ON" if self.auto_mode else "OFF"
            pending = ""
            if self.pending_trade:
                pending = f"\n<b>Pending:</b> {self.pending_trade['action']} {self.pending_trade['amount']} {self.pending_trade['token']}"

            send_telegram(f"""<b>Bot Status</b>

<b>Status:</b> {status}
<b>Auto Mode:</b> {auto_status}
<b>Active Token:</b> {self.active_token}
<b>Today's Trades:</b> {self.auto_trades_today}/{AUTO_MAX_DAILY_TRADES}{pending}

<b>Wallet Balance:</b>
SOL: {wallet.get('sol', 0):.4f} (${wallet.get('sol_usd', 0):.2f})
USDC: ${wallet.get('usdc', 0):.2f}
<b>Total:</b> ${wallet.get('total_usd', 0):.2f}""")

        elif cmd == "/pause":
            self.is_paused = True
            send_telegram("<b>Trading Signals Paused</b>\n\nSend /resume to continue")

        elif cmd == "/resume":
            self.is_paused = False
            send_telegram("<b>Trading Signals Resumed</b>")

        elif cmd == "/price":
            sol_price = get_sol_price()
            send_telegram(f"<b>SOL:</b> ${sol_price:,.2f}")

        elif cmd == "/tokens":
            token_list = "\n".join([f"- {name}" for name in TOKENS.keys()])
            send_telegram(f"""<b>Available Tokens:</b>

{token_list}

Current: {self.active_token}""")

        # Full autonomous trading mode
        elif cmd == "/fullauto" or cmd == "/fullauto toggle":
            self.full_auto = not self.full_auto
            self.auto_mode = self.full_auto  # Full auto requires auto mode on

            if self.full_auto:
                send_telegram(f"""🤖 <b>FULL AUTO MODE: ON</b>

The bot will now trade <b>completely autonomously</b>:

<b>How it works:</b>
1. AI analyzes market every {CHECK_INTERVAL_MINUTES} mins
2. When signal is strong (≥{MIN_CONFIDENCE}% confidence), it BUYS
3. Position tracked with SL/TP
4. Auto-sells on stop loss or take profit
5. Looks for next opportunity and repeats

<b>Settings:</b>
• Trade Amount: {AUTO_TRADE_AMOUNT} {self.active_token}
• Stop Loss: {DEFAULT_STOP_LOSS_PCT}%
• Take Profit: {DEFAULT_TAKE_PROFIT_PCT}%
• Max Daily Trades: {AUTO_MAX_DAILY_TRADES}
• Max Daily Loss: ${FULL_AUTO_MAX_LOSS_USD}
• Cooldown: {FULL_AUTO_COOLDOWN} min between trades

<b>Safety:</b> Bot pauses if daily loss exceeds ${FULL_AUTO_MAX_LOSS_USD}

Send /fullauto off to disable
Send /position to monitor
Send /stats to see performance""")
            else:
                send_telegram("""🤖 <b>FULL AUTO MODE: OFF</b>

Autonomous trading disabled.
Use /auto for semi-auto (requires confirmation).""")

        elif cmd == "/fullauto on":
            self.full_auto = True
            self.auto_mode = True
            send_telegram(f"""🤖 <b>FULL AUTO MODE: ON</b>

Bot is now trading autonomously!

• Amount: {AUTO_TRADE_AMOUNT} {self.active_token}
• SL: {DEFAULT_STOP_LOSS_PCT}% | TP: {DEFAULT_TAKE_PROFIT_PCT}%
• Max loss: ${FULL_AUTO_MAX_LOSS_USD}/day

Use /position to monitor positions.""")

        elif cmd == "/fullauto off":
            self.full_auto = False
            send_telegram("🤖 <b>FULL AUTO MODE: OFF</b>\n\nAutonomous trading disabled.")

        elif cmd == "/stats" or cmd == "/performance":
            win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
            send_telegram(f"""📊 <b>Trading Statistics</b>

<b>Today:</b>
• Trades: {self.auto_trades_today}/{AUTO_MAX_DAILY_TRADES}
• P&L: ${self.daily_pnl:+.2f}

<b>Session:</b>
• Total Trades: {self.total_trades}
• Winning: {self.winning_trades} ({win_rate:.0f}%)
• Losing: {self.losing_trades}

<b>Mode:</b> {'🤖 FULL AUTO' if self.full_auto else ('⚡ Semi-Auto' if self.auto_mode else '👤 Manual')}
<b>Status:</b> {'⏸ PAUSED' if self.is_paused else '▶️ RUNNING'}""")

        # Semi-auto trading commands
        elif cmd == "/auto" or cmd == "/auto toggle":
            if self.full_auto:
                send_telegram("Full auto is ON. Use /fullauto off first, then /auto for semi-auto mode.")
                return

            self.auto_mode = not self.auto_mode
            status = "ON" if self.auto_mode else "OFF"
            if self.auto_mode:
                send_telegram(f"""<b>Semi-Auto Trading: {status}</b>

AI will analyze every {CHECK_INTERVAL_MINUTES} mins and propose trades.

<b>Settings:</b>
• Trade Amount: {AUTO_TRADE_AMOUNT} {self.active_token}
• Requires Confirmation: Yes
• Max Daily Trades: {AUTO_MAX_DAILY_TRADES}

When AI finds a signal, you'll get a notification to /confirm or /cancel.

For hands-free trading, use /fullauto instead.""")
            else:
                send_telegram(f"<b>Auto Trading: {status}</b>\n\nAI will only send signals, no trade proposals.")

        elif cmd == "/auto on":
            if self.full_auto:
                send_telegram("Full auto is ON. Use /fullauto off first.")
                return
            self.auto_mode = True
            send_telegram(f"""<b>Semi-Auto Trading: ON</b>

AI will analyze every {CHECK_INTERVAL_MINUTES} mins and propose trades.

• Amount: {AUTO_TRADE_AMOUNT} {self.active_token}
• You must /confirm each trade
• Max {AUTO_MAX_DAILY_TRADES} trades/day

For hands-free: /fullauto""")

        elif cmd == "/auto off":
            self.auto_mode = False
            self.full_auto = False
            self.pending_trade = None
            send_telegram("<b>Auto Trading: OFF</b>\n\nAll auto trading disabled.")

        elif cmd == "/confirm" or cmd == "/yes":
            if not self.pending_trade:
                send_telegram("No pending trade to confirm.\n\nUse /analyze to get AI recommendation.")
                return

            trade = self.pending_trade
            self.pending_trade = None

            send_telegram(f"<b>Executing {trade['action']}...</b>\n\n{trade['amount']} {trade['token']}")

            if trade['action'] == "BUY":
                result = buy_token(trade['token'], trade['amount'])
            else:
                result = sell_token(trade['token'], trade['amount'])

            if result.get("success"):
                self.auto_trades_today += 1
                current_price = get_token_price(trade['token'])

                if trade['action'] == "BUY":
                    # Track position with SL/TP
                    pos = open_position(trade['token'], trade['amount'], current_price)
                    send_telegram(f"""<b>{trade['action']} SUCCESS!</b>

<b>Amount:</b> {trade['amount']} {trade['token']}
<b>Entry:</b> ${current_price:.4f}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

<b>Risk Management:</b>
🛑 SL: ${pos['stop_loss_price']:.4f} (-{pos['stop_loss_pct']:.1f}%)
🎯 TP: ${pos['take_profit_price']:.4f} (+{pos['take_profit_pct']:.1f}%)

Trades today: {self.auto_trades_today}/{AUTO_MAX_DAILY_TRADES}""")
                else:
                    # Calculate P&L for sells
                    pnl_msg = ""
                    if trade['token'] in POSITIONS:
                        pos = POSITIONS[trade['token']]
                        entry = pos["entry_price"]
                        pnl_pct = ((current_price - entry) / entry) * 100
                        pnl_usd = (current_price - entry) * trade['amount']
                        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                        pnl_msg = f"\n<b>P&L:</b> {pnl_emoji} {pnl_pct:+.2f}% (${pnl_usd:+.2f})"
                        close_position(trade['token'])

                    send_telegram(f"""<b>{trade['action']} SUCCESS!</b>

<b>Amount:</b> {trade['amount']} {trade['token']}
<b>Exit:</b> ${current_price:.4f}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>{pnl_msg}

Trades today: {self.auto_trades_today}/{AUTO_MAX_DAILY_TRADES}""")
            else:
                send_telegram(f"""<b>{trade['action']} FAILED</b>

<b>Error:</b> {result.get('error')}

Try /analyze to get a new signal.""")

        elif cmd == "/cancel" or cmd == "/no":
            if self.pending_trade:
                trade = self.pending_trade
                self.pending_trade = None
                send_telegram(f"<b>Trade Cancelled</b>\n\n{trade['action']} {trade['amount']} {trade['token']} cancelled.")
            else:
                send_telegram("No pending trade to cancel.")

        elif cmd == "/analyze" or cmd == "/signal":
            send_telegram("<b>Analyzing market...</b>\n\nPlease wait...")

            wallet = get_wallet_balance()
            token_address = TOKENS.get(self.active_token, SOL_ADDRESS)
            candles = get_birdeye_candles(token_address, "1H", 50) if BIRDEYE_API_KEY else []

            if not candles:
                price = get_token_price(self.active_token)
                candles = [{"close": price}]

            action, confidence, reason = analyze_with_ai(self.active_token, candles, wallet)

            # Calculate technicals for display
            technicals = calculate_technicals(candles)

            tech_display = ""
            if technicals:
                tech_display = f"""
<b>Technicals:</b>
• RSI: {technicals.get('rsi', 50):.1f}
• Trend: {technicals.get('trend', 'N/A')}
• Momentum: {technicals.get('momentum_5', 0):.2f}%"""

            emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"

            msg = f"""<b>{emoji} AI Analysis: {self.active_token}</b>

<b>Decision:</b> {action}
<b>Confidence:</b> {confidence}%
<b>Reason:</b> {reason}
{tech_display}
<b>Price:</b> ${get_token_price(self.active_token):,.4f}"""

            if self.auto_mode and action != "HOLD" and confidence >= MIN_CONFIDENCE:
                if self.auto_trades_today < AUTO_MAX_DAILY_TRADES:
                    # Create pending trade
                    self.pending_trade = {
                        "action": action,
                        "amount": AUTO_TRADE_AMOUNT,
                        "token": self.active_token,
                        "expires": datetime.now() + timedelta(seconds=AUTO_CONFIRM_TIMEOUT)
                    }
                    msg += f"""

<b>Proposed Trade:</b>
{action} {AUTO_TRADE_AMOUNT} {self.active_token}

Reply /confirm to execute
Reply /cancel to skip"""
                else:
                    msg += "\n\n<i>Daily trade limit reached.</i>"

            send_telegram(msg)

        elif cmd == "/sentiment" or cmd == "/fear" or cmd == "/greed":
            send_telegram("<b>Checking market sentiment...</b>")
            update_sentiment_data()
            send_telegram(get_sentiment_status())

        elif cmd == "/market" or cmd == "/sol":
            send_telegram("<b>Fetching SOL market data...</b>")
            update_volume_data()
            send_telegram(get_market_status())

        elif cmd == "/trending" or cmd == "/hot":
            send_telegram("<b>Fetching trending coins...</b>")
            send_telegram(get_trending_status())

        elif cmd == "/btc" or cmd == "/dominance":
            send_telegram("<b>Fetching BTC dominance...</b>")
            send_telegram(get_btc_dominance_status())

        elif cmd == "/tvl" or cmd == "/defi":
            send_telegram("<b>Fetching Solana TVL...</b>")
            send_telegram(get_tvl_status())

        elif cmd == "/gainers" or cmd == "/losers" or cmd == "/movers":
            send_telegram("<b>Fetching top movers...</b>")
            send_telegram(get_gainers_status())

        # New DeFi data commands
        elif cmd == "/dex" or cmd == "/dexvolume":
            send_telegram("<b>Fetching Solana DEX volume...</b>")
            send_telegram(get_dex_volume_status())

        elif cmd == "/yields" or cmd == "/apy" or cmd == "/yield":
            send_telegram("<b>Fetching best DeFi yields...</b>")
            send_telegram(get_yields_status())

        elif cmd == "/stables" or cmd == "/stablecoins" or cmd == "/stable":
            send_telegram("<b>Fetching stablecoin flows...</b>")
            send_telegram(get_stablecoin_status())

        elif cmd == "/exchanges" or cmd == "/cex":
            send_telegram("<b>Fetching exchange volumes...</b>")
            send_telegram(get_exchange_status())

        # API key required commands
        elif cmd == "/birdeye" or cmd.startswith("/birdeye "):
            token = "SOL"
            if cmd.startswith("/birdeye "):
                token = cmd.replace("/birdeye ", "").strip().upper()
            send_telegram(f"<b>Fetching Birdeye data for {token}...</b>")
            send_telegram(get_birdeye_status(token))

        elif cmd == "/whales" or cmd == "/whale":
            send_telegram("<b>Fetching whale transactions...</b>")
            send_telegram(get_whale_status())

        # Overview of all data feeds
        elif cmd == "/data" or cmd == "/feeds" or cmd == "/all":
            send_telegram("<b>Refreshing all data feeds...</b>")

            # Update all feeds
            update_sentiment_data()
            update_volume_data()
            update_tvl_data()
            update_dominance_data()
            update_dex_volume_data()
            update_yields_data()
            update_stablecoin_data()
            if HELIUS_API_KEY:
                update_whale_data()

            # Build summary
            lines = ["📊 <b>All Data Feeds</b>\n"]

            for name, data in AGENT_DATA.items():
                if data.get("signal") and data.get("updated"):
                    age = datetime.now() - data["updated"]
                    age_mins = age.total_seconds() / 60

                    signal_emoji = "🟢" if data["signal"] == "BULLISH" else "🔴" if data["signal"] == "BEARISH" else "⚪"
                    lines.append(f"{signal_emoji} <b>{name.upper()}</b>: {data['message']}")

            # Add API key status
            lines.append("\n<b>API Status:</b>")
            lines.append(f"• Birdeye: {'✅' if BIRDEYE_API_KEY else '❌ (get at birdeye.so)'}")
            lines.append(f"• Helius: {'✅' if HELIUS_API_KEY else '❌ (get at helius.dev)'}")

            lines.append("\n<i>Use individual commands for details</i>")
            send_telegram("\n".join(lines))

        # ============================================
        # RISK MANAGEMENT COMMANDS
        # ============================================

        elif cmd == "/position" or cmd == "/positions" or cmd == "/pos":
            send_telegram(get_position_status())

        elif cmd.startswith("/sl ") or cmd.startswith("/stoploss "):
            # Set stop loss: /sl 5 or /sl 5 sol
            parts = cmd.replace("/sl ", "").replace("/stoploss ", "").strip().split()
            try:
                sl_pct = float(parts[0])
                token = parts[1].upper() if len(parts) > 1 else self.active_token

                if token in POSITIONS:
                    if set_stop_loss(token, stop_loss_pct=sl_pct):
                        pos = POSITIONS[token]
                        send_telegram(f"""✅ <b>Stop Loss Updated</b>

<b>{token}</b>
🛑 Stop Loss: ${pos['stop_loss_price']:.4f} (-{sl_pct:.1f}%)
Entry: ${pos['entry_price']:.4f}""")
                    else:
                        send_telegram(f"Failed to update stop loss for {token}")
                else:
                    # Update default
                    DEFAULT_STOP_LOSS_PCT = sl_pct
                    send_telegram(f"""✅ <b>Default Stop Loss Updated</b>

New default: {sl_pct}%
(Applied to future trades)

No open {token} position to update.""")
            except (ValueError, IndexError):
                send_telegram("""<b>Set Stop Loss</b>

Usage: /sl [percentage] [token]

<b>Examples:</b>
• /sl 5 - Set 5% stop loss for active token
• /sl 3 sol - Set 3% stop loss for SOL

Current default: {0}%""".format(DEFAULT_STOP_LOSS_PCT))

        elif cmd.startswith("/tp ") or cmd.startswith("/takeprofit "):
            # Set take profit: /tp 10 or /tp 10 sol
            parts = cmd.replace("/tp ", "").replace("/takeprofit ", "").strip().split()
            try:
                tp_pct = float(parts[0])
                token = parts[1].upper() if len(parts) > 1 else self.active_token

                if token in POSITIONS:
                    if set_take_profit(token, take_profit_pct=tp_pct):
                        pos = POSITIONS[token]
                        send_telegram(f"""✅ <b>Take Profit Updated</b>

<b>{token}</b>
🎯 Take Profit: ${pos['take_profit_price']:.4f} (+{tp_pct:.1f}%)
Entry: ${pos['entry_price']:.4f}""")
                    else:
                        send_telegram(f"Failed to update take profit for {token}")
                else:
                    # Update default
                    DEFAULT_TAKE_PROFIT_PCT = tp_pct
                    send_telegram(f"""✅ <b>Default Take Profit Updated</b>

New default: {tp_pct}%
(Applied to future trades)

No open {token} position to update.""")
            except (ValueError, IndexError):
                send_telegram("""<b>Set Take Profit</b>

Usage: /tp [percentage] [token]

<b>Examples:</b>
• /tp 10 - Set 10% take profit for active token
• /tp 15 sol - Set 15% take profit for SOL

Current default: {0}%""".format(DEFAULT_TAKE_PROFIT_PCT))

        elif cmd.startswith("/close ") or cmd == "/close":
            # Close position tracking (doesn't sell, just removes tracking)
            token = cmd.replace("/close ", "").replace("/close", "").strip().upper()
            if not token:
                token = self.active_token

            if token in POSITIONS:
                pos = close_position(token)
                send_telegram(f"""✅ <b>Position Closed</b>

<b>{token}</b> position tracking removed.

Entry was: ${pos['entry_price']:.4f}
Amount: {pos['amount']}

<i>Note: This only removes tracking. To sell, use /sell</i>""")
            else:
                send_telegram(f"No open position for {token}.\n\nUse /position to see tracked positions.")

        elif cmd == "/trailing" or cmd == "/trail":
            TRAILING_STOP_ENABLED = not TRAILING_STOP_ENABLED
            status = "ON" if TRAILING_STOP_ENABLED else "OFF"

            # Update existing positions
            for token in POSITIONS:
                POSITIONS[token]["trailing_stop"] = TRAILING_STOP_ENABLED

            send_telegram(f"""🔄 <b>Trailing Stop: {status}</b>

{'Trailing stops will automatically move up as price increases.' if TRAILING_STOP_ENABLED else 'Trailing stops disabled. SL stays at fixed price.'}

Trail distance: {TRAILING_STOP_PCT}%""")

        elif cmd.startswith("/buy") or cmd.startswith("buy "):
            # Parse various formats:
            # /buy 0.5 sol, /buy sol with 0.5 usdc, /buy 0.5 usdc worth of sol
            text = cmd.replace("/buy", "").replace("buy", "").strip()
            text = text.replace(" with ", " ").replace(" worth of ", " ").replace(" of ", " ").replace(" for ", " ")
            parts = [p for p in text.split() if p]

            # Try to find amount and token
            amount = None
            token = None

            for p in parts:
                try:
                    amount = float(p)
                except ValueError:
                    if p.upper() in TOKENS and p.upper() != "USDC":
                        token = p.upper()

            if amount and token:
                # Get price to show estimated cost
                price = get_token_price(token)
                est_cost = amount * price if price > 0 else 0

                send_telegram(f"""<b>Executing BUY...</b>

Buying {amount} {token}
Est. cost: ~${est_cost:.2f} USDC
Please wait...""")

                # Execute the trade (buy with USDC)
                result = buy_token(token, amount)

                if result.get("success"):
                    # Track position with SL/TP
                    entry_price = get_token_price(token)
                    pos = open_position(token, amount, entry_price)

                    send_telegram(f"""<b>BUY SUCCESS!</b>

<b>Bought:</b> {amount} {token}
<b>Entry:</b> ${entry_price:.4f}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

<b>Risk Management Active:</b>
🛑 Stop Loss: ${pos['stop_loss_price']:.4f} (-{pos['stop_loss_pct']:.1f}%)
🎯 Take Profit: ${pos['take_profit_price']:.4f} (+{pos['take_profit_pct']:.1f}%)

Use /position to view, /sl or /tp to adjust.""")
                else:
                    send_telegram(f"""<b>BUY FAILED</b>

<b>Error:</b> {result.get('error')}

Try again or use /trade for manual swap.""")
            else:
                send_telegram("""<b>Buy Command</b>

Usage: /buy [amount] [token]

<b>Examples:</b>
• /buy 0.01 sol - Buy 0.01 SOL
• /buy 1000 bonk - Buy 1000 BONK
• /buy 0.5 wif - Buy 0.5 WIF

Amount is in token units.""")

        elif cmd.startswith("/sell") or cmd.startswith("sell "):
            # Parse various formats:
            # /sell 0.01 sol, /sell 0.01 sol for usdc
            text = cmd.replace("/sell", "").replace("sell", "").strip()
            text = text.replace(" for ", " ").replace(" to ", " ")
            parts = [p for p in text.split() if p]

            # Try to find amount and token
            amount = None
            token = None

            for i, p in enumerate(parts):
                try:
                    amount = float(p)
                    # Token should be next
                    if i + 1 < len(parts) and parts[i + 1].upper() in TOKENS:
                        token = parts[i + 1].upper()
                except ValueError:
                    pass

            if amount and token:
                send_telegram(f"""<b>Executing SELL...</b>

Selling {amount} {token} for USDC
Please wait...""")

                # Execute the trade
                result = sell_token(token, amount)

                if result.get("success"):
                    exit_price = get_token_price(token)

                    # Calculate P&L if we had a tracked position
                    pnl_msg = ""
                    if token in POSITIONS:
                        pos = POSITIONS[token]
                        entry = pos["entry_price"]
                        pnl_pct = ((exit_price - entry) / entry) * 100
                        pnl_usd = (exit_price - entry) * amount
                        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                        pnl_msg = f"\n\n<b>P&L:</b> {pnl_emoji} {pnl_pct:+.2f}% (${pnl_usd:+.2f})"

                        # Close position if selling full amount
                        if amount >= pos["amount"]:
                            close_position(token)

                    send_telegram(f"""<b>SELL SUCCESS!</b>

<b>Sold:</b> {amount} {token}
<b>Exit:</b> ${exit_price:.4f}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>{pnl_msg}""")
                else:
                    send_telegram(f"""<b>SELL FAILED</b>

<b>Error:</b> {result.get('error')}

Try again or use /trade for manual swap.""")
            else:
                send_telegram("""<b>Sell Command</b>

Usage: /sell [amount] [token]

<b>Examples:</b>
• /sell 0.01 sol - Sell 0.01 SOL
• /sell 1000 bonk - Sell 1000 BONK
• /sell 0.5 wif - Sell 0.5 WIF

Amount is in token units.""")

        elif cmd.startswith("/trade") or cmd.startswith("trade"):
            # Parse trade command: /trade usdc sol or "trade usdc to sol"
            parts = cmd.replace("/trade", "").replace("trade", "").strip()
            parts = parts.replace(" to ", " ").replace(" for ", " ").split()

            if len(parts) >= 2:
                input_token = parts[0].upper()
                output_token = parts[1].upper()

                # Get prices
                sol_price = get_sol_price()

                # Generate Jupiter URL
                swap_url = get_jupiter_swap_url(input_token, output_token)

                send_telegram(f"""<b>Trade: {input_token} → {output_token}</b>

<b>Current SOL Price:</b> ${sol_price:,.2f}

<b>Click to trade on Jupiter:</b>
{swap_url}

<i>This opens Jupiter DEX where you can:
1. Connect your Phantom wallet
2. Enter amount
3. Confirm swap</i>""")
            else:
                send_telegram("""<b>Trade Command</b>

Usage: /trade [from] [to]

<b>Examples:</b>
• /trade usdc sol - Buy SOL with USDC
• /trade sol usdc - Sell SOL for USDC
• /trade usdc bonk - Buy BONK

<b>Quick Links:</b>
• <a href="https://jup.ag/swap/USDC-SOL">Buy SOL</a>
• <a href="https://jup.ag/swap/SOL-USDC">Sell SOL</a>""")

        else:
            # Unknown command - provide help
            if cmd and not cmd.startswith("/"):
                send_telegram(f"""I don't understand "{cmd}"

Try /help for available commands
Or /trade usdc sol to get a swap link""")

    def run_cycle(self):
        """Run one trading cycle"""
        if self.is_paused:
            print("Bot is paused, skipping cycle")
            return

        # Check for expired pending trades
        if self.pending_trade:
            if datetime.now() > self.pending_trade.get("expires", datetime.now()):
                print("Pending trade expired, clearing...")
                self.pending_trade = None

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running trading cycle...")

        try:
            # Update free data feeds (sentiment + market data)
            print("Updating sentiment data...")
            old_sentiment = AGENT_DATA.get("sentiment", {}).get("value", 50)
            update_sentiment_data()
            new_sentiment = AGENT_DATA.get("sentiment", {}).get("value", 50)

            # Alert on extreme sentiment changes
            if new_sentiment <= 25 and old_sentiment > 25:
                send_telegram(f"""<b>😱 EXTREME FEAR ALERT!</b>

Fear & Greed: {new_sentiment}/100
<b>Signal:</b> 🟢 BULLISH

<i>Market is fearful - potential buy opportunity!</i>""")
            elif new_sentiment >= 75 and old_sentiment < 75:
                send_telegram(f"""<b>🤑 EXTREME GREED ALERT!</b>

Fear & Greed: {new_sentiment}/100
<b>Signal:</b> 🔴 BEARISH

<i>Market may be overheated - consider taking profits!</i>""")

            print("Updating market data...")
            update_volume_data()

            # Alert on big price moves
            price_change = AGENT_DATA.get("volume", {}).get("price_change", 0)
            if abs(price_change) > 7:
                direction = "up" if price_change > 0 else "down"
                emoji = "🚀" if price_change > 0 else "💥"
                send_telegram(f"""<b>{emoji} BIG MOVE ALERT!</b>

SOL is {direction} <b>{abs(price_change):.1f}%</b> in 24h!

<i>Check /market for details</i>""")

            # Update TVL and dominance data (for AI context)
            print("Updating TVL and dominance...")
            update_tvl_data()
            update_dominance_data()

            # Update new DeFi data feeds
            print("Updating DeFi data (DEX, yields, stables)...")
            update_dex_volume_data()
            update_yields_data()
            update_stablecoin_data()

            # Update whale data if Helius is configured
            if HELIUS_API_KEY:
                print("Updating whale data...")
                update_whale_data()

            # ============================================
            # POSITION MONITORING - Check SL/TP triggers
            # ============================================
            if POSITIONS:
                print(f"Checking {len(POSITIONS)} open position(s)...")
                for token in list(POSITIONS.keys()):
                    current_price = get_token_price(token)
                    trigger = check_position_triggers(token, current_price)

                    if trigger and trigger.get("triggered"):
                        trigger_type = trigger["triggered"]
                        pos = trigger["position"]
                        pnl_pct = trigger["pnl_pct"]
                        pnl_usd = trigger["pnl_usd"]
                        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"

                        if trigger_type == "STOP_LOSS":
                            send_telegram(f"""🛑 <b>STOP LOSS TRIGGERED!</b>

<b>{token}</b> hit stop loss at ${current_price:.4f}

<b>Entry:</b> ${pos['entry_price']:.4f}
<b>P&L:</b> {pnl_emoji} {pnl_pct:.2f}% (${pnl_usd:.2f})

<b>Auto-selling to protect capital...</b>""")

                            # Execute stop loss sell
                            result = sell_token(token, pos['amount'])
                            if result.get("success"):
                                close_position(token)
                                # Track stats
                                self.daily_pnl += pnl_usd
                                self.total_trades += 1
                                self.losing_trades += 1
                                self.last_trade_time = datetime.now()

                                reentry_msg = ""
                                if self.full_auto and FULL_AUTO_REENTRY:
                                    reentry_msg = "\n\n<i>Looking for next opportunity...</i>"

                                send_telegram(f"""<b>Stop Loss Executed!</b>

<b>Sold:</b> {pos['amount']} {token}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

<b>Daily P&L:</b> ${self.daily_pnl:.2f}{reentry_msg}""")
                            else:
                                send_telegram(f"""<b>Stop Loss FAILED!</b>

Error: {result.get('error')}

<b>MANUAL ACTION REQUIRED</b>
Use /sell {pos['amount']} {token.lower()}""")

                        elif trigger_type == "TAKE_PROFIT":
                            send_telegram(f"""🎯 <b>TAKE PROFIT TRIGGERED!</b>

<b>{token}</b> hit target at ${current_price:.4f}

<b>Entry:</b> ${pos['entry_price']:.4f}
<b>P&L:</b> {pnl_emoji} +{pnl_pct:.2f}% (+${pnl_usd:.2f})

<b>Auto-selling to lock in profit...</b>""")

                            # Execute take profit sell
                            result = sell_token(token, pos['amount'])
                            if result.get("success"):
                                close_position(token)
                                # Track stats
                                self.daily_pnl += pnl_usd
                                self.total_trades += 1
                                self.winning_trades += 1
                                self.last_trade_time = datetime.now()

                                reentry_msg = ""
                                if self.full_auto and FULL_AUTO_REENTRY:
                                    reentry_msg = "\n\n<i>Looking for next opportunity...</i>"

                                send_telegram(f"""<b>Take Profit Executed!</b>

<b>Sold:</b> {pos['amount']} {token}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

<b>Daily P&L:</b> ${self.daily_pnl:.2f} 🎉{reentry_msg}""")
                            else:
                                send_telegram(f"""<b>Take Profit FAILED!</b>

Error: {result.get('error')}

<b>MANUAL ACTION REQUIRED</b>
Use /sell {pos['amount']} {token.lower()}""")

            symbol = self.active_token
            token_address = TOKENS.get(symbol, SOL_ADDRESS)

            # Get price
            price = get_token_price(symbol)
            print(f"{symbol}: ${price:,.4f}")

            # Get wallet balance for context
            wallet = get_wallet_balance()

            # Get candles (if Birdeye is configured)
            candles = []
            if BIRDEYE_API_KEY:
                candles = get_birdeye_candles(token_address, "1H", 50)

            if not candles:
                # Use simple price-based analysis
                print("No candle data, using price-only analysis")
                candles = [{"close": price}]

            # Get AI analysis with enhanced context
            action, confidence, reasoning = analyze_with_ai(symbol, candles, wallet)
            print(f"AI Decision: {action} ({confidence}%) - {reasoning}")

            # Check for actionable signals
            if confidence >= MIN_CONFIDENCE and action != "HOLD":
                self.daily_trades += 1

                emoji = "🟢" if action == "BUY" else "🔴"

                # Calculate technicals for display
                technicals = calculate_technicals(candles)
                tech_display = ""
                if technicals:
                    tech_display = f"""
<b>Technicals:</b>
• RSI: {technicals.get('rsi', 50):.1f}
• Trend: {technicals.get('trend', 'N/A')}"""

                # Check if we can trade
                can_trade = (
                    self.auto_mode and
                    self.auto_trades_today < AUTO_MAX_DAILY_TRADES and
                    self.daily_pnl > -FULL_AUTO_MAX_LOSS_USD
                )

                # Check cooldown
                cooldown_ok = True
                if self.last_trade_time:
                    mins_since_trade = (datetime.now() - self.last_trade_time).total_seconds() / 60
                    cooldown_ok = mins_since_trade >= FULL_AUTO_COOLDOWN

                # FULL AUTO MODE - Execute immediately without confirmation
                if self.full_auto and can_trade and cooldown_ok:
                    # Don't open if we already have a position in this token
                    if symbol in POSITIONS and action == "BUY":
                        print(f"Already have {symbol} position, skipping buy")
                    else:
                        send_telegram(f"""🤖 <b>FULL AUTO: {action}</b>

<b>{symbol}</b> @ ${price:,.4f}
<b>Confidence:</b> {confidence}%
<b>Reason:</b> {reasoning}

<b>Executing trade automatically...</b>""")

                        if action == "BUY":
                            result = buy_token(symbol, AUTO_TRADE_AMOUNT)
                            if result.get("success"):
                                self.auto_trades_today += 1
                                self.total_trades += 1
                                self.last_trade_time = datetime.now()

                                # Position is already tracked by buy_token
                                pos = POSITIONS.get(symbol, {})
                                send_telegram(f"""✅ <b>AUTO BUY EXECUTED</b>

<b>Bought:</b> {AUTO_TRADE_AMOUNT} {symbol}
<b>Entry:</b> ${price:.4f}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

<b>Auto Risk Management:</b>
🛑 SL: ${pos.get('stop_loss_price', 0):.4f}
🎯 TP: ${pos.get('take_profit_price', 0):.4f}

Trades today: {self.auto_trades_today}/{AUTO_MAX_DAILY_TRADES}""")
                            else:
                                send_telegram(f"❌ Auto buy failed: {result.get('error')}")

                        elif action == "SELL" and symbol in POSITIONS:
                            result = sell_token(symbol, POSITIONS[symbol]["amount"])
                            if result.get("success"):
                                self.auto_trades_today += 1
                                self.last_trade_time = datetime.now()
                                send_telegram(f"""✅ <b>AUTO SELL EXECUTED</b>

<b>Sold:</b> {symbol}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>""")

                # SEMI-AUTO MODE - Propose and wait for confirmation
                elif self.auto_mode and can_trade and not self.full_auto:
                    if not self.pending_trade:  # Don't overwrite existing pending trade
                        self.pending_trade = {
                            "action": action,
                            "amount": AUTO_TRADE_AMOUNT,
                            "token": symbol,
                            "expires": datetime.now() + timedelta(seconds=AUTO_CONFIRM_TIMEOUT)
                        }

                        send_telegram(f"""<b>{emoji} {action} SIGNAL</b> - {symbol}

<b>Price:</b> ${price:,.4f}
<b>Confidence:</b> {confidence}%
<b>Reason:</b> {reasoning}
{tech_display}

<b>Proposed Trade:</b>
{action} {AUTO_TRADE_AMOUNT} {symbol}

/confirm - Execute trade
/cancel - Skip this signal

<i>Expires in 60 seconds</i>""")

                # MANUAL MODE or limits reached - Just show signal
                else:
                    reason_msg = ""
                    if not cooldown_ok:
                        reason_msg = f"\n<i>Cooldown: {FULL_AUTO_COOLDOWN - mins_since_trade:.0f} min remaining</i>"
                    elif self.auto_trades_today >= AUTO_MAX_DAILY_TRADES:
                        reason_msg = "\n<i>Daily trade limit reached</i>"
                    elif self.daily_pnl <= -FULL_AUTO_MAX_LOSS_USD:
                        reason_msg = "\n<i>⚠️ Daily loss limit reached - auto paused</i>"

                    send_telegram(f"""<b>{emoji} {action} SIGNAL</b> - {symbol}

<b>Price:</b> ${price:,.4f}
<b>Confidence:</b> {confidence}%
<b>Reason:</b> {reasoning}
{tech_display}

<i>Use /buy or /sell to trade manually</i>{reason_msg}""")

        except Exception as e:
            print(f"Error in cycle: {e}")

    def run(self):
        """Main loop"""
        print("\nBot running... Press Ctrl+C to stop\n")

        while self.running:
            try:
                # Reset daily counters at midnight
                if datetime.now().date() != self.last_trade_date:
                    self.daily_trades = 0
                    self.auto_trades_today = 0
                    self.daily_pnl = 0.0
                    self.last_trade_date = datetime.now().date()
                    print("Daily counters reset")
                    if self.full_auto:
                        send_telegram(f"""📅 <b>New Trading Day</b>

Daily counters reset.
Max trades: {AUTO_MAX_DAILY_TRADES}
Max loss: ${FULL_AUTO_MAX_LOSS_USD}

Full auto trading continues...""")

                # Check Telegram commands
                cmd = check_telegram_commands()
                if cmd:
                    print(f"Command received: {cmd}")
                    self.handle_command(cmd)

                # Run trading cycle
                self.run_cycle()

                # Wait for next cycle
                print(f"Next check in {CHECK_INTERVAL_MINUTES} minutes...")

                # Sleep with periodic command checks
                for _ in range(CHECK_INTERVAL_MINUTES * 6):
                    if not self.running:
                        break
                    cmd = check_telegram_commands()
                    if cmd:
                        print(f"Command received: {cmd}")
                        self.handle_command(cmd)
                    time.sleep(10)

            except KeyboardInterrupt:
                print("\nShutting down...")
                self.running = False
                send_telegram("<b>Bot Stopped</b>")
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(60)


def main():
    bot = TelegramTradingBot()
    bot.run()


if __name__ == "__main__":
    main()
