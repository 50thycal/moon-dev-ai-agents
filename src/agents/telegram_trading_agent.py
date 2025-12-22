#!/usr/bin/env python3
"""
Moon Dev's Telegram Trading Agent - STANDALONE VERSION

A simple, self-contained trading bot that works on Railway.
No complex dependencies - just Telegram + HyperLiquid + OpenAI.

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

# HyperLiquid
HL_PRIVATE_KEY = os.getenv("HYPER_LIQUID_ETH_PRIVATE_KEY", "")

# Trading Settings
SYMBOLS = ["BTC"]
LEVERAGE = 5
MAX_POSITION_PERCENTAGE = 50
STOP_LOSS_PERCENTAGE = 10.0
TAKE_PROFIT_PERCENTAGE = 15.0
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
# HYPERLIQUID FUNCTIONS
# ============================================================================

def get_hl_price(symbol: str) -> float:
    """Get current price from HyperLiquid"""
    try:
        url = "https://api.hyperliquid.xyz/info"
        payload = {"type": "allMids"}
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        return float(data.get(symbol, 0))
    except Exception as e:
        print(f"Price error: {e}")
        return 0

def get_hl_candles(symbol: str, interval: str = "1h", limit: int = 50) -> list:
    """Get OHLCV candles from HyperLiquid"""
    try:
        url = "https://api.hyperliquid.xyz/info"
        end_time = int(time.time() * 1000)
        start_time = end_time - (limit * 3600 * 1000)  # hours back

        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time
            }
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Candles error: {e}")
        return []

def get_hl_account_value() -> float:
    """Get account value from HyperLiquid"""
    if not HL_PRIVATE_KEY:
        return 0

    try:
        from eth_account import Account
        account = Account.from_key(HL_PRIVATE_KEY)
        address = account.address

        url = "https://api.hyperliquid.xyz/info"
        payload = {"type": "clearinghouseState", "user": address}
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()

        margin_summary = data.get("marginSummary", {})
        return float(margin_summary.get("accountValue", 0))
    except Exception as e:
        print(f"Account error: {e}")
        return 0

def get_hl_position(symbol: str) -> dict:
    """Get position for symbol"""
    if not HL_PRIVATE_KEY:
        return None

    try:
        from eth_account import Account
        account = Account.from_key(HL_PRIVATE_KEY)
        address = account.address

        url = "https://api.hyperliquid.xyz/info"
        payload = {"type": "clearinghouseState", "user": address}
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()

        for pos in data.get("assetPositions", []):
            position = pos.get("position", {})
            if position.get("coin") == symbol:
                size = float(position.get("szi", 0))
                if size != 0:
                    entry_px = float(position.get("entryPx", 0))
                    mark_px = get_hl_price(symbol)
                    pnl_pct = ((mark_px - entry_px) / entry_px * 100) if entry_px else 0
                    if size < 0:  # Short position
                        pnl_pct = -pnl_pct

                    return {
                        "symbol": symbol,
                        "size": size,
                        "entry_price": entry_px,
                        "mark_price": mark_px,
                        "pnl_percentage": pnl_pct,
                        "notional": abs(size) * mark_px
                    }
        return None
    except Exception as e:
        print(f"Position error: {e}")
        return None

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
        candle_text = "Recent price data (last 20 candles):\n"
        for c in candles[-20:]:
            candle_text += f"Open: {c.get('o', 'N/A')}, High: {c.get('h', 'N/A')}, Low: {c.get('l', 'N/A')}, Close: {c.get('c', 'N/A')}\n"

        prompt = f"""Analyze this {symbol} market data and decide: BUY, SELL, or HOLD.

{candle_text}

Rules:
- Respond with ONLY one word: BUY, SELL, or HOLD
- BUY = bullish, good entry point
- SELL = bearish, exit or short
- HOLD = unclear, wait

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

        print("=" * 50)
        print("Moon Dev Telegram Trading Bot")
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

        if not HL_PRIVATE_KEY:
            print("WARNING: HyperLiquid not configured!")
        else:
            print("HyperLiquid: OK")

        print(f"Symbols: {SYMBOLS}")
        print(f"Leverage: {LEVERAGE}x")
        print(f"Check interval: {CHECK_INTERVAL_MINUTES} min")
        print("=" * 50)

        # Send startup message
        send_telegram(f"""<b>🌙 Moon Dev Trading Bot Started!</b>

<b>Exchange:</b> HyperLiquid
<b>Symbols:</b> {', '.join(SYMBOLS)}
<b>Leverage:</b> {LEVERAGE}x
<b>Interval:</b> {CHECK_INTERVAL_MINUTES} min

Send /help for commands""")

    def handle_command(self, cmd: str):
        """Handle Telegram command"""
        if cmd == "/help" or cmd == "/start":
            send_telegram("""<b>🤖 Trading Bot Commands</b>

/status - Check balance & positions
/pause - Pause trading
/resume - Resume trading
/price - Get current BTC price
/help - Show this message

Bot checks markets every """ + str(CHECK_INTERVAL_MINUTES) + """ minutes""")

        elif cmd == "/status":
            balance = get_hl_account_value()
            pos_text = ""

            for symbol in SYMBOLS:
                pos = get_hl_position(symbol)
                if pos:
                    emoji = "📈" if pos["pnl_percentage"] >= 0 else "📉"
                    pos_text += f"\n{symbol}: {pos['pnl_percentage']:+.2f}% {emoji}"

            if not pos_text:
                pos_text = "\nNo open positions"

            status = "⏸️ PAUSED" if self.is_paused else "✅ ACTIVE"

            send_telegram(f"""<b>📊 Bot Status</b>

<b>Status:</b> {status}
<b>Balance:</b> ${balance:,.2f}
<b>Today's Trades:</b> {self.daily_trades}

<b>Positions:</b>{pos_text}""")

        elif cmd == "/pause":
            self.is_paused = True
            send_telegram("⏸️ <b>Trading Paused</b>\n\nSend /resume to continue")

        elif cmd == "/resume":
            self.is_paused = False
            send_telegram("▶️ <b>Trading Resumed</b>")

        elif cmd == "/price":
            for symbol in SYMBOLS:
                price = get_hl_price(symbol)
                send_telegram(f"💰 <b>{symbol}</b>: ${price:,.2f}")

    def run_cycle(self):
        """Run one trading cycle"""
        if self.is_paused:
            print("Bot is paused, skipping cycle")
            return

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running trading cycle...")

        for symbol in SYMBOLS:
            try:
                # Get market data
                price = get_hl_price(symbol)
                candles = get_hl_candles(symbol, "1h", 50)

                if not candles:
                    print(f"No candles for {symbol}")
                    continue

                print(f"{symbol}: ${price:,.2f}")

                # Check current position
                pos = get_hl_position(symbol)
                has_position = pos is not None

                if has_position:
                    print(f"Position: {pos['size']} @ ${pos['entry_price']:,.2f}, P&L: {pos['pnl_percentage']:+.2f}%")

                    # Check stop loss / take profit
                    if pos["pnl_percentage"] <= -STOP_LOSS_PERCENTAGE:
                        send_telegram(f"🛑 <b>STOP LOSS</b> - {symbol}\n\nP&L: {pos['pnl_percentage']:+.2f}%\n\n<i>Manual close recommended</i>")
                    elif pos["pnl_percentage"] >= TAKE_PROFIT_PERCENTAGE:
                        send_telegram(f"🎯 <b>TAKE PROFIT</b> - {symbol}\n\nP&L: {pos['pnl_percentage']:+.2f}%\n\n<i>Consider taking profits</i>")

                # Get AI analysis
                action, confidence, reasoning = analyze_with_ai(symbol, candles)
                print(f"AI Decision: {action} ({confidence}%)")

                # Alert on high-confidence signals
                if confidence >= MIN_CONFIDENCE:
                    if action == "BUY" and not has_position:
                        send_telegram(f"""📈 <b>BUY SIGNAL</b> - {symbol}

<b>Price:</b> ${price:,.2f}
<b>Confidence:</b> {confidence}%

<i>This is a signal only - manual trade required on HyperLiquid</i>""")

                    elif action == "SELL" and has_position:
                        send_telegram(f"""📉 <b>SELL SIGNAL</b> - {symbol}

<b>Price:</b> ${price:,.2f}
<b>Confidence:</b> {confidence}%
<b>Current P&L:</b> {pos['pnl_percentage']:+.2f}%

<i>Consider closing position</i>""")

            except Exception as e:
                print(f"Error analyzing {symbol}: {e}")

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
                send_telegram("🛑 <b>Bot Stopped</b>")
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(60)


def main():
    bot = TelegramTradingBot()
    bot.run()


if __name__ == "__main__":
    main()
