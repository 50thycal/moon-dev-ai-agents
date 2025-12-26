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
SOL_ADDRESS = "So11111111111111111111111111111111111111111"

# Trading Settings
TOKENS = {
    "SOL": SOL_ADDRESS,
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
}
DEFAULT_TOKEN = "SOL"
TRADE_SIZE_USD = 10  # Default trade size in USD
SLIPPAGE_BPS = 500  # 5% slippage
CHECK_INTERVAL_MINUTES = 15
MIN_CONFIDENCE = 60

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

def get_sol_price() -> float:
    """Get SOL price from Jupiter"""
    try:
        url = "https://price.jup.ag/v6/price?ids=SOL"
        response = requests.get(url, timeout=10)
        data = response.json()
        return float(data.get("data", {}).get("SOL", {}).get("price", 0))
    except Exception as e:
        print(f"Price error: {e}")
        return 0

def get_token_price(symbol: str) -> float:
    """Get token price from Jupiter"""
    try:
        mint = TOKENS.get(symbol, symbol)
        url = f"https://price.jup.ag/v6/price?ids={mint}"
        response = requests.get(url, timeout=10)
        data = response.json()
        return float(data.get("data", {}).get(mint, {}).get("price", 0))
    except Exception as e:
        print(f"Price error for {symbol}: {e}")
        return 0

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

def execute_swap(input_mint: str, output_mint: str, amount_lamports: int) -> dict:
    """Execute a swap via Jupiter"""
    if not SOLANA_PRIVATE_KEY:
        return {"success": False, "error": "No private key configured"}

    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
        from solana.rpc.api import Client

        keypair = Keypair.from_base58_string(SOLANA_PRIVATE_KEY)
        http_client = Client(RPC_ENDPOINT)

        # Get quote from Jupiter
        quote_url = f"https://lite-api.jup.ag/swap/v1/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps={SLIPPAGE_BPS}"
        quote_response = requests.get(quote_url, timeout=10)
        quote = quote_response.json()

        if "error" in quote:
            return {"success": False, "error": quote.get("error")}

        # Get swap transaction
        swap_response = requests.post(
            "https://lite-api.jup.ag/swap/v1/swap",
            headers={"Content-Type": "application/json"},
            json={
                "quoteResponse": quote,
                "userPublicKey": str(keypair.pubkey()),
                "wrapUnwrapSOL": True
            },
            timeout=30
        )
        swap_data = swap_response.json()

        if "error" in swap_data:
            return {"success": False, "error": swap_data.get("error")}

        # Sign and send transaction
        import base64
        tx_bytes = base64.b64decode(swap_data["swapTransaction"])
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = keypair.sign_message(bytes(tx.message))

        # This is a simplified version - full implementation would need proper signing
        return {
            "success": True,
            "quote": quote,
            "message": "Swap prepared (manual execution on Jupiter recommended for safety)"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# AI ANALYSIS
# ============================================================================

def analyze_with_ai(symbol: str, candles: list) -> tuple:
    """Get AI trading decision using OpenAI"""
    if not OPENAI_KEY:
        print("OpenAI key not configured")
        return "NOTHING", 0, "No AI available"

    try:
        # Format candle data
        candle_text = f"Recent {symbol} price data (last 20 candles):\n"
        for c in candles[-20:]:
            o = c.get('o', c.get('open', 'N/A'))
            h = c.get('h', c.get('high', 'N/A'))
            l = c.get('l', c.get('low', 'N/A'))
            close = c.get('c', c.get('close', 'N/A'))
            candle_text += f"Open: {o}, High: {h}, Low: {l}, Close: {close}\n"

        prompt = f"""Analyze this {symbol} market data and decide: BUY, SELL, or HOLD.

{candle_text}

Rules:
- Respond with ONLY one word: BUY, SELL, or HOLD
- BUY = bullish, good entry point
- SELL = bearish, exit or take profits
- HOLD = unclear, wait for better setup

Your decision:"""

        headers = {
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a crypto trading AI. Respond with only BUY, SELL, or HOLD."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 10,
            "temperature": 0.3
        }

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )

        result = response.json()
        decision = result["choices"][0]["message"]["content"].strip().upper()

        if "BUY" in decision:
            return "BUY", 75, "AI recommends BUY"
        elif "SELL" in decision:
            return "SELL", 75, "AI recommends SELL"
        else:
            return "HOLD", 50, "AI recommends HOLD"

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
        send_telegram(f"""<b>Moon Dev Trading Bot Started!</b>

<b>Exchange:</b> Solana + Jupiter DEX
<b>Token:</b> {self.active_token}
<b>Interval:</b> {CHECK_INTERVAL_MINUTES} min

<b>Wallet:</b>
SOL: {wallet.get('sol', 0):.4f} (${wallet.get('sol_usd', 0):.2f})
USDC: ${wallet.get('usdc', 0):.2f}
<b>Total:</b> ${wallet.get('total_usd', 0):.2f}

Send /help for commands""")

    def handle_command(self, cmd: str):
        """Handle Telegram command"""
        if cmd == "/help" or cmd == "/start":
            send_telegram("""<b>Trading Bot Commands</b>

/status - Check wallet balance
/price - Get current SOL price
/tokens - List available tokens
/pause - Pause trading signals
/resume - Resume trading signals
/help - Show this message

<b>Available Tokens:</b> SOL, BONK, WIF

Bot checks markets every """ + str(CHECK_INTERVAL_MINUTES) + """ minutes
<i>Note: This is a SIGNAL bot - trades require manual execution on Jupiter</i>""")

        elif cmd == "/status":
            wallet = get_wallet_balance()
            status = "PAUSED" if self.is_paused else "ACTIVE"

            send_telegram(f"""<b>Bot Status</b>

<b>Status:</b> {status}
<b>Active Token:</b> {self.active_token}
<b>Today's Signals:</b> {self.daily_trades}

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

    def run_cycle(self):
        """Run one trading cycle"""
        if self.is_paused:
            print("Bot is paused, skipping cycle")
            return

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running trading cycle...")

        try:
            symbol = self.active_token
            token_address = TOKENS.get(symbol, SOL_ADDRESS)

            # Get price
            price = get_token_price(symbol)
            print(f"{symbol}: ${price:,.4f}")

            # Get candles (if Birdeye is configured)
            candles = []
            if BIRDEYE_API_KEY:
                candles = get_birdeye_candles(token_address, "1H", 50)

            if not candles:
                # Use simple price-based analysis
                print("No candle data, using price-only analysis")
                candles = [{"close": price}]

            # Get AI analysis
            action, confidence, reasoning = analyze_with_ai(symbol, candles)
            print(f"AI Decision: {action} ({confidence}%)")

            # Alert on high-confidence signals
            if confidence >= MIN_CONFIDENCE and action != "HOLD":
                self.daily_trades += 1

                if action == "BUY":
                    send_telegram(f"""<b>BUY SIGNAL</b> - {symbol}

<b>Price:</b> ${price:,.4f}
<b>Confidence:</b> {confidence}%

<i>Execute on Jupiter: jup.ag</i>
<i>This is a signal only - manual trade required</i>""")

                elif action == "SELL":
                    send_telegram(f"""<b>SELL SIGNAL</b> - {symbol}

<b>Price:</b> ${price:,.4f}
<b>Confidence:</b> {confidence}%

<i>Execute on Jupiter: jup.ag</i>
<i>Consider taking profits if in position</i>""")

        except Exception as e:
            print(f"Error in cycle: {e}")

    def run(self):
        """Main loop"""
        print("\nBot running... Press Ctrl+C to stop\n")

        while self.running:
            try:
                # Reset daily trades at midnight
                if datetime.now().date() != self.last_trade_date:
                    self.daily_trades = 0
                    self.last_trade_date = datetime.now().date()

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
