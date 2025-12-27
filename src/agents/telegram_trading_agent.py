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
AUTO_MAX_DAILY_TRADES = 5  # Max trades per day in auto mode

# External Agent Data (will be populated by agent feeds)
AGENT_DATA = {
    "whale": {"signal": None, "message": "", "updated": None},
    "funding": {"signal": None, "message": "", "updated": None},
    "liquidation": {"signal": None, "message": "", "updated": None},
    "volume": {"signal": None, "message": "", "updated": None},
    "sentiment": {"signal": None, "message": "", "updated": None},
}

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
        auto_status = "OFF"
        send_telegram(f"""<b>Moon Dev Trading Bot Started!</b>

<b>Exchange:</b> Solana + Jupiter DEX
<b>Token:</b> {self.active_token}
<b>Interval:</b> {CHECK_INTERVAL_MINUTES} min
<b>Auto Mode:</b> {auto_status}

<b>Wallet:</b>
SOL: {wallet.get('sol', 0):.4f} (${wallet.get('sol_usd', 0):.2f})
USDC: ${wallet.get('usdc', 0):.2f}
<b>Total:</b> ${wallet.get('total_usd', 0):.2f}

Send /help for commands
Send /auto to enable AI trading""")

    def handle_command(self, cmd: str):
        """Handle Telegram command"""
        if cmd == "/help" or cmd == "/start":
            auto_status = "ON" if self.auto_mode else "OFF"
            send_telegram(f"""<b>Trading Bot Commands</b>

<b>Auto Trading:</b>
/auto - Toggle autonomous AI trading ({auto_status})
/auto on - Enable AI auto-trading
/auto off - Disable AI auto-trading
/confirm - Confirm pending trade
/cancel - Cancel pending trade

<b>Manual Trading:</b>
/buy [amount] [token] - Buy token
/sell [amount] [token] - Sell token

<b>Info:</b>
/status - Bot status + wallet
/price [token] - Get price
/analyze - Run AI analysis now

<b>Controls:</b>
/pause - Pause all trading
/resume - Resume trading
/tokens - List tokens
/help - This message

<b>Examples:</b>
• /auto on - Let AI trade for you
• /buy 0.01 sol - Buy 0.01 SOL
• /analyze - See what AI thinks""")

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

        # Auto trading commands
        elif cmd == "/auto" or cmd == "/auto toggle":
            self.auto_mode = not self.auto_mode
            status = "ON" if self.auto_mode else "OFF"
            if self.auto_mode:
                send_telegram(f"""<b>Auto Trading: {status}</b>

AI will now analyze the market every {CHECK_INTERVAL_MINUTES} mins and propose trades.

<b>Settings:</b>
• Trade Amount: {AUTO_TRADE_AMOUNT} {self.active_token}
• Requires Confirmation: Yes
• Max Daily Trades: {AUTO_MAX_DAILY_TRADES}

When AI finds a signal, you'll get a notification to /confirm or /cancel.

Send /auto off to disable.""")
            else:
                send_telegram(f"<b>Auto Trading: {status}</b>\n\nAI will only send signals, no trade proposals.")

        elif cmd == "/auto on":
            self.auto_mode = True
            send_telegram(f"""<b>Auto Trading: ON</b>

AI will analyze every {CHECK_INTERVAL_MINUTES} mins and propose trades.

• Amount: {AUTO_TRADE_AMOUNT} {self.active_token}
• You must /confirm each trade
• Max {AUTO_MAX_DAILY_TRADES} trades/day""")

        elif cmd == "/auto off":
            self.auto_mode = False
            self.pending_trade = None
            send_telegram("<b>Auto Trading: OFF</b>\n\nAI signals only, no trade proposals.")

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
                send_telegram(f"""<b>{trade['action']} SUCCESS!</b>

<b>Amount:</b> {trade['amount']} {trade['token']}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

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
                    send_telegram(f"""<b>BUY SUCCESS!</b>

<b>Bought:</b> {amount} {token}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

Your balance has been updated.""")
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
                    send_telegram(f"""<b>SELL SUCCESS!</b>

<b>Sold:</b> {amount} {token}
<b>TX:</b> <a href="{result.get('url')}">View on Solscan</a>

Your balance has been updated.""")
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

                # Auto mode: propose trade for confirmation
                if self.auto_mode and self.auto_trades_today < AUTO_MAX_DAILY_TRADES:
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
                else:
                    # Signal only mode (auto mode off or limit reached)
                    send_telegram(f"""<b>{emoji} {action} SIGNAL</b> - {symbol}

<b>Price:</b> ${price:,.4f}
<b>Confidence:</b> {confidence}%
<b>Reason:</b> {reasoning}
{tech_display}

<i>Use /buy or /sell to trade manually</i>""")

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
                    self.last_trade_date = datetime.now().date()
                    print("Daily counters reset")

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
