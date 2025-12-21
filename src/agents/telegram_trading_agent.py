#!/usr/bin/env python3
"""
Moon Dev's Telegram Trading Agent

AUTONOMOUS AI TRADING BOT WITH MOBILE ALERTS

This agent combines:
1. Autonomous AI trading (6-model swarm consensus)
2. Telegram alerts for all trades and status updates
3. Mobile-friendly controls via Telegram commands

FEATURES:
- /status - Check current positions, balance, and P&L
- /pause - Pause autonomous trading
- /resume - Resume autonomous trading
- /closeall - Emergency close all positions
- /settings - View current trading settings
- /help - Show available commands

The bot runs autonomously, making trades based on AI consensus,
while keeping you informed via Telegram push notifications.

SETUP:
1. Create a Telegram bot via @BotFather
2. Get your bot token and add to .env as TELEGRAM_BOT_TOKEN
3. Get your chat ID (send /start to your bot, then check updates)
4. Add your chat ID to .env as TELEGRAM_CHAT_ID
5. Run: python src/agents/telegram_trading_agent.py

Built with love by Moon Dev
"""

import os
import sys
import asyncio
import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from termcolor import cprint
from dotenv import load_dotenv

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Load environment variables
load_dotenv()

# ============================================================================
# TELEGRAM TRADING AGENT CONFIGURATION
# ============================================================================

# Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Exchange Selection (same as trading_agent.py)
EXCHANGE = "ASTER"  # Options: "ASTER", "HYPERLIQUID", "SOLANA"

# AI Mode
USE_SWARM_MODE = True  # Always use 6-model consensus for autonomous trading

# Trading Mode
LONG_ONLY = True  # True = Long positions only, False = Long & Short

# Position Sizing for Mobile ($100 starting capital friendly)
MAX_POSITION_PERCENTAGE = 50  # Use 50% of balance per trade (more conservative for small accounts)
LEVERAGE = 5  # Lower leverage for safety with small capital
STOP_LOSS_PERCENTAGE = 10.0  # 10% stop loss (wider for volatile crypto)
TAKE_PROFIT_PERCENTAGE = 15.0  # 15% take profit

# Trading Intervals
SLEEP_BETWEEN_RUNS_MINUTES = 15  # Check markets every 15 minutes
PNL_CHECK_INTERVAL = 10  # Check P&L every 10 seconds when position is open

# Market Data
DAYSBACK_4_DATA = 3
DATA_TIMEFRAME = '1H'

# Tokens to Trade
SYMBOLS = ['BTC']  # Start with just BTC for simplicity

# For Solana (if using SOLANA exchange)
MONITORED_TOKENS = [
    # Add Solana token addresses here if using SOLANA exchange
]

# Safety Settings
MIN_CONFIDENCE_TO_TRADE = 60  # Only trade if AI consensus is >= 60%
MAX_DAILY_TRADES = 10  # Maximum trades per day
COOLDOWN_AFTER_LOSS_MINUTES = 30  # Wait 30 min after a losing trade

# ============================================================================
# END CONFIGURATION
# ============================================================================

# Dynamic imports based on exchange
if EXCHANGE == "ASTER":
    from src import nice_funcs_aster as n
elif EXCHANGE == "HYPERLIQUID":
    from src import nice_funcs_hyperliquid as n
elif EXCHANGE == "SOLANA":
    from src import nice_funcs as n

from src.data.ohlcv_collector import collect_all_tokens
from src.agents.swarm_agent import SwarmAgent

# Trading prompt for swarm
SWARM_TRADING_PROMPT = """You are an expert cryptocurrency trading AI analyzing market data.

CRITICAL RULES:
1. Your response MUST be EXACTLY one of these three words: Buy, Sell, or Do Nothing
2. Do NOT provide any explanation, reasoning, or additional text
3. Respond with ONLY the action word

Analyze the market data below and decide:
- "Buy" = Strong bullish signals, recommend opening/holding position
- "Sell" = Bearish signals, recommend closing position
- "Do Nothing" = Unclear signals, stay out or hold current state

RESPOND WITH ONLY ONE WORD: Buy, Sell, or Do Nothing"""


class TelegramTradingAgent:
    """Autonomous trading bot with Telegram alerts and controls"""

    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.is_paused = False
        self.daily_trades = 0
        self.last_trade_time = None
        self.last_loss_time = None
        self.swarm = None
        self.running = True

        # Validate Telegram config
        if not self.bot_token or not self.chat_id:
            cprint("=" * 60, "red")
            cprint(" TELEGRAM NOT CONFIGURED!", "red", attrs=['bold'])
            cprint("=" * 60, "red")
            cprint("\nTo set up Telegram alerts:", "yellow")
            cprint("1. Message @BotFather on Telegram", "white")
            cprint("2. Send /newbot and follow instructions", "white")
            cprint("3. Copy the bot token to .env as TELEGRAM_BOT_TOKEN", "white")
            cprint("4. Message your new bot and send /start", "white")
            cprint("5. Visit: https://api.telegram.org/bot<TOKEN>/getUpdates", "white")
            cprint("6. Find your chat_id and add to .env as TELEGRAM_CHAT_ID", "white")
            cprint("\nBot will run WITHOUT Telegram alerts for now.\n", "yellow")
            self.telegram_enabled = False
        else:
            self.telegram_enabled = True
            cprint(" Telegram alerts enabled!", "green", attrs=['bold'])

        # Initialize swarm
        cprint("\n Initializing AI Swarm (6 models)...", "cyan", attrs=['bold'])
        self.swarm = SwarmAgent()
        cprint(" Swarm ready!", "green")

        # Send startup message
        self._send_startup_message()

    def _send_telegram(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message via Telegram"""
        if not self.telegram_enabled:
            return False

        try:
            import requests
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode
            }
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            cprint(f" Telegram error: {e}", "red")
            return False

    def _send_startup_message(self):
        """Send bot startup notification"""
        msg = """
<b>Moon Dev Trading Bot Started!</b>

<b>Exchange:</b> {exchange}
<b>Mode:</b> {'Long Only' if LONG_ONLY else 'Long/Short'}
<b>Leverage:</b> {leverage}x
<b>Max Position:</b> {max_pos}%
<b>Stop Loss:</b> {sl}%
<b>Take Profit:</b> {tp}%

<b>Trading:</b> {symbols}

<i>Send /help for commands</i>
        """.format(
            exchange=EXCHANGE,
            leverage=LEVERAGE,
            max_pos=MAX_POSITION_PERCENTAGE,
            sl=STOP_LOSS_PERCENTAGE,
            tp=TAKE_PROFIT_PERCENTAGE,
            symbols=", ".join(SYMBOLS if EXCHANGE != "SOLANA" else ["Solana tokens"])
        )
        self._send_telegram(msg)

    def _get_account_balance(self) -> float:
        """Get current account balance"""
        try:
            if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                if EXCHANGE == "ASTER":
                    balance_dict = n.get_account_balance()
                    return balance_dict.get('total_equity', 0)
                else:
                    account = n._get_account_from_env()
                    return n.get_account_value(account)
            else:
                from src.config import USDC_ADDRESS
                return n.get_token_balance_usd(USDC_ADDRESS)
        except Exception as e:
            cprint(f" Error getting balance: {e}", "red")
            return 0

    def _get_position(self, symbol: str) -> Optional[Dict]:
        """Get current position for a symbol"""
        try:
            if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                return n.get_position(symbol)
            else:
                position_usd = n.get_token_balance_usd(symbol)
                if position_usd > 0:
                    return {"position_amount": position_usd, "pnl_percentage": 0}
                return None
        except Exception as e:
            cprint(f" Error getting position: {e}", "red")
            return None

    def _calculate_position_size(self, balance: float) -> float:
        """Calculate position size based on balance"""
        margin = balance * (MAX_POSITION_PERCENTAGE / 100)
        if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
            return margin * LEVERAGE
        return margin

    def _format_market_data(self, symbol: str, data) -> str:
        """Format market data for swarm analysis"""
        if hasattr(data, 'to_string'):
            return f"""
TOKEN: {symbol}
TIMEFRAME: {DATA_TIMEFRAME}
TOTAL BARS: {len(data)}

RECENT PRICE ACTION (Last 10 bars):
{data.tail(10).to_string()}

FULL DATA:
{data.to_string()}
"""
        return str(data)

    def _calculate_consensus(self, swarm_result: Dict) -> tuple:
        """Calculate consensus from swarm votes"""
        votes = {"BUY": 0, "SELL": 0, "NOTHING": 0}
        model_votes = []

        for provider, data in swarm_result.get("responses", {}).items():
            if not data.get("success"):
                continue

            response = data.get("response", "").strip().upper()

            if "BUY" in response:
                votes["BUY"] += 1
                model_votes.append(f"{provider}: BUY")
            elif "SELL" in response:
                votes["SELL"] += 1
                model_votes.append(f"{provider}: SELL")
            else:
                votes["NOTHING"] += 1
                model_votes.append(f"{provider}: HOLD")

        total = sum(votes.values())
        if total == 0:
            return "NOTHING", 0, "No valid responses"

        action = max(votes, key=votes.get)
        confidence = int((votes[action] / total) * 100)
        reasoning = f"Votes: BUY={votes['BUY']}, SELL={votes['SELL']}, HOLD={votes['NOTHING']}"

        return action, confidence, reasoning

    def send_trade_alert(self, action: str, symbol: str, size: float,
                         confidence: int, reasoning: str):
        """Send trade execution alert"""
        emoji = "" if action == "BUY" else "" if action == "SELL" else ""

        msg = f"""
<b>{emoji} {action} SIGNAL - {symbol}</b>

<b>Position Size:</b> ${size:,.2f}
<b>AI Confidence:</b> {confidence}%
<b>Leverage:</b> {LEVERAGE}x

<b>AI Analysis:</b>
{reasoning}

<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>
"""
        self._send_telegram(msg)

    def send_position_update(self, symbol: str, pnl_pct: float,
                            pnl_usd: float, action: str):
        """Send position update (stop loss / take profit hit)"""
        emoji = "" if pnl_pct >= 0 else ""
        action_emoji = "" if action == "TAKE_PROFIT" else ""

        msg = f"""
<b>{action_emoji} {action.replace('_', ' ')} - {symbol}</b>

<b>P&L:</b> {pnl_pct:+.2f}% (${pnl_usd:+,.2f})
<b>Result:</b> {'Profit!' if pnl_pct >= 0 else 'Loss'}

<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>
"""
        self._send_telegram(msg)

        # Track loss for cooldown
        if pnl_pct < 0:
            self.last_loss_time = datetime.now()

    def send_status(self):
        """Send current status via Telegram"""
        balance = self._get_account_balance()

        positions_text = ""
        tokens = SYMBOLS if EXCHANGE != "SOLANA" else MONITORED_TOKENS

        for symbol in tokens:
            pos = self._get_position(symbol)
            if pos and pos.get('position_amount', 0) != 0:
                pnl = pos.get('pnl_percentage', 0)
                emoji = "" if pnl >= 0 else ""
                positions_text += f"\n  {symbol}: {pnl:+.2f}% {emoji}"

        if not positions_text:
            positions_text = "\n  No open positions"

        status = "PAUSED" if self.is_paused else "ACTIVE"
        status_emoji = "" if self.is_paused else ""

        msg = f"""
<b> Trading Bot Status</b>

<b>Status:</b> {status_emoji} {status}
<b>Balance:</b> ${balance:,.2f}
<b>Daily Trades:</b> {self.daily_trades}/{MAX_DAILY_TRADES}

<b>Open Positions:</b>{positions_text}

<b>Settings:</b>
  Exchange: {EXCHANGE}
  Leverage: {LEVERAGE}x
  Stop Loss: {STOP_LOSS_PERCENTAGE}%
  Take Profit: {TAKE_PROFIT_PERCENTAGE}%

<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>
"""
        self._send_telegram(msg)
        return msg

    def close_all_positions(self) -> bool:
        """Emergency close all positions"""
        cprint("\n EMERGENCY: Closing all positions!", "red", attrs=['bold'])
        self._send_telegram("<b> EMERGENCY CLOSE ALL</b>\n\nClosing all positions...")

        try:
            tokens = SYMBOLS if EXCHANGE != "SOLANA" else MONITORED_TOKENS
            closed = 0

            for symbol in tokens:
                pos = self._get_position(symbol)
                if pos and pos.get('position_amount', 0) != 0:
                    if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                        position_size = abs(pos['position_amount']) * pos.get('mark_price', 0)
                        if pos['position_amount'] > 0:
                            n.limit_sell(symbol, position_size, slippage=0, leverage=LEVERAGE)
                        else:
                            n.limit_buy(symbol, position_size, slippage=0, leverage=LEVERAGE)
                    else:
                        n.chunk_kill(symbol, 3, 199)
                    closed += 1
                    cprint(f" Closed {symbol}", "green")

            msg = f"<b> All Positions Closed</b>\n\nClosed {closed} position(s)"
            self._send_telegram(msg)
            return True

        except Exception as e:
            cprint(f" Error closing positions: {e}", "red")
            self._send_telegram(f"<b> Error closing positions:</b>\n{str(e)}")
            return False

    def _can_trade(self) -> tuple:
        """Check if we can make a trade (safety checks)"""
        # Check if paused
        if self.is_paused:
            return False, "Bot is paused"

        # Check daily trade limit
        if self.daily_trades >= MAX_DAILY_TRADES:
            return False, f"Daily trade limit reached ({MAX_DAILY_TRADES})"

        # Check cooldown after loss
        if self.last_loss_time:
            cooldown_end = self.last_loss_time + timedelta(minutes=COOLDOWN_AFTER_LOSS_MINUTES)
            if datetime.now() < cooldown_end:
                remaining = (cooldown_end - datetime.now()).seconds // 60
                return False, f"Loss cooldown: {remaining} min remaining"

        return True, "OK"

    def _monitor_position(self, symbol: str):
        """Monitor position for stop loss / take profit"""
        cprint(f"\n Monitoring {symbol} position...", "cyan")
        cprint(f"   Stop Loss: -{STOP_LOSS_PERCENTAGE}% | Take Profit: +{TAKE_PROFIT_PERCENTAGE}%", "white")

        while self.running:
            try:
                pos = self._get_position(symbol)

                if not pos or pos.get('position_amount', 0) == 0:
                    cprint(f" Position closed for {symbol}", "green")
                    return

                if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                    pnl_pct = pos.get('pnl_percentage', 0)
                    pnl_usd = pos.get('pnl', 0)
                    position_size = abs(pos['position_amount']) * pos.get('mark_price', 0)

                    cprint(f" {symbol}: P&L {pnl_pct:+.2f}% (${pnl_usd:+,.2f})", "cyan")

                    # Stop loss
                    if pnl_pct <= -STOP_LOSS_PERCENTAGE:
                        cprint(f" STOP LOSS HIT!", "red", attrs=['bold'])

                        if pos['position_amount'] > 0:
                            n.limit_sell(symbol, position_size, slippage=0, leverage=LEVERAGE)
                        else:
                            n.limit_buy(symbol, position_size, slippage=0, leverage=LEVERAGE)

                        self.send_position_update(symbol, pnl_pct, pnl_usd, "STOP_LOSS")
                        return

                    # Take profit
                    if pnl_pct >= TAKE_PROFIT_PERCENTAGE:
                        cprint(f" TAKE PROFIT HIT!", "green", attrs=['bold'])

                        if pos['position_amount'] > 0:
                            n.limit_sell(symbol, position_size, slippage=0, leverage=LEVERAGE)
                        else:
                            n.limit_buy(symbol, position_size, slippage=0, leverage=LEVERAGE)

                        self.send_position_update(symbol, pnl_pct, pnl_usd, "TAKE_PROFIT")
                        return

                time.sleep(PNL_CHECK_INTERVAL)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                cprint(f" Monitor error: {e}", "red")
                time.sleep(PNL_CHECK_INTERVAL)

    def run_trading_cycle(self):
        """Run one complete trading cycle"""
        try:
            # Safety checks
            can_trade, reason = self._can_trade()
            if not can_trade:
                cprint(f" Cannot trade: {reason}", "yellow")
                return

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cprint(f"\n Trading Cycle Starting at {current_time}", "cyan", attrs=['bold'])

            # Get tokens to trade
            tokens = SYMBOLS if EXCHANGE != "SOLANA" else MONITORED_TOKENS

            # Collect market data
            cprint(" Collecting market data...", "blue")
            market_data = collect_all_tokens(
                tokens=tokens,
                days_back=DAYSBACK_4_DATA,
                timeframe=DATA_TIMEFRAME,
                exchange=EXCHANGE
            )

            if not market_data:
                cprint(" No market data received", "red")
                return

            # Analyze each token
            for symbol, data in market_data.items():
                cprint(f"\n Analyzing {symbol} with AI Swarm...", "cyan")

                # Check if we already have a position
                pos = self._get_position(symbol)
                has_position = pos and pos.get('position_amount', 0) != 0

                # Format data and query swarm
                formatted_data = self._format_market_data(symbol, data)
                swarm_result = self.swarm.query(formatted_data, SWARM_TRADING_PROMPT)

                if not swarm_result:
                    cprint(f" No swarm response for {symbol}", "red")
                    continue

                # Calculate consensus
                action, confidence, reasoning = self._calculate_consensus(swarm_result)

                cprint(f"\n Swarm Decision for {symbol}:", "yellow", attrs=['bold'])
                cprint(f"   Action: {action}", "white")
                cprint(f"   Confidence: {confidence}%", "white")
                cprint(f"   {reasoning}", "white")

                # Check confidence threshold
                if confidence < MIN_CONFIDENCE_TO_TRADE:
                    cprint(f" Confidence too low ({confidence}% < {MIN_CONFIDENCE_TO_TRADE}%)", "yellow")
                    continue

                # Execute based on action
                if action == "BUY" and not has_position:
                    # Open new position
                    balance = self._get_account_balance()
                    position_size = self._calculate_position_size(balance)

                    cprint(f"\n Opening {symbol} position: ${position_size:,.2f}", "green", attrs=['bold'])

                    self.send_trade_alert("BUY", symbol, position_size, confidence, reasoning)

                    try:
                        if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                            n.ai_entry(symbol, position_size, leverage=LEVERAGE)
                        else:
                            n.ai_entry(symbol, position_size)

                        self.daily_trades += 1
                        self.last_trade_time = datetime.now()

                        # Monitor position
                        self._monitor_position(symbol)

                    except Exception as e:
                        cprint(f" Error opening position: {e}", "red")
                        self._send_telegram(f"<b> Trade Error</b>\n\n{str(e)}")

                elif action == "SELL" and has_position:
                    # Close position
                    cprint(f"\n Closing {symbol} position", "yellow", attrs=['bold'])

                    pnl_pct = pos.get('pnl_percentage', 0)
                    self.send_trade_alert("SELL", symbol, 0, confidence, reasoning)

                    try:
                        if EXCHANGE in ["ASTER", "HYPERLIQUID"]:
                            position_size = abs(pos['position_amount']) * pos.get('mark_price', 0)
                            if pos['position_amount'] > 0:
                                n.limit_sell(symbol, position_size, slippage=0, leverage=LEVERAGE)
                            else:
                                n.limit_buy(symbol, position_size, slippage=0, leverage=LEVERAGE)
                        else:
                            n.chunk_kill(symbol, 3, 199)

                        self.daily_trades += 1
                        if pnl_pct < 0:
                            self.last_loss_time = datetime.now()

                    except Exception as e:
                        cprint(f" Error closing position: {e}", "red")

                elif has_position:
                    cprint(f" Holding {symbol} position (AI says: {action})", "blue")
                else:
                    cprint(f" No action for {symbol} (AI says: {action})", "blue")

            cprint("\n Trading cycle complete!", "green")

        except Exception as e:
            cprint(f"\n Error in trading cycle: {e}", "red")
            self._send_telegram(f"<b> Trading Error</b>\n\n{str(e)}")

    def _check_telegram_commands(self):
        """Check for Telegram commands (polling)"""
        if not self.telegram_enabled:
            return

        try:
            import requests
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"

            # Get last update ID from file if exists
            update_file = Path(project_root) / "src" / "data" / "telegram_last_update.txt"
            last_update_id = 0
            if update_file.exists():
                last_update_id = int(update_file.read_text().strip())

            params = {"offset": last_update_id + 1, "timeout": 1}
            response = requests.get(url, params=params, timeout=5)

            if response.status_code != 200:
                return

            updates = response.json().get("result", [])

            for update in updates:
                update_id = update.get("update_id", 0)
                message = update.get("message", {})
                text = message.get("text", "").strip().lower()
                chat_id = str(message.get("chat", {}).get("id", ""))

                # Only respond to our authorized chat
                if chat_id != self.chat_id:
                    continue

                # Save update ID
                update_file.parent.mkdir(parents=True, exist_ok=True)
                update_file.write_text(str(update_id))

                # Handle commands
                if text == "/status":
                    self.send_status()

                elif text == "/pause":
                    self.is_paused = True
                    self._send_telegram("<b> Trading Paused</b>\n\nBot will not make new trades.\nSend /resume to continue.")

                elif text == "/resume":
                    self.is_paused = False
                    self._send_telegram("<b> Trading Resumed</b>\n\nBot is now actively trading.")

                elif text == "/closeall":
                    self.close_all_positions()

                elif text == "/settings":
                    msg = f"""
<b> Current Settings</b>

<b>Exchange:</b> {EXCHANGE}
<b>Leverage:</b> {LEVERAGE}x
<b>Max Position:</b> {MAX_POSITION_PERCENTAGE}%
<b>Stop Loss:</b> {STOP_LOSS_PERCENTAGE}%
<b>Take Profit:</b> {TAKE_PROFIT_PERCENTAGE}%
<b>Min Confidence:</b> {MIN_CONFIDENCE_TO_TRADE}%
<b>Trading Interval:</b> {SLEEP_BETWEEN_RUNS_MINUTES} min
<b>Max Daily Trades:</b> {MAX_DAILY_TRADES}
"""
                    self._send_telegram(msg)

                elif text == "/help":
                    msg = """
<b> Moon Dev Trading Bot Commands</b>

/status - Check positions & balance
/pause - Pause trading
/resume - Resume trading
/closeall - Emergency close all
/settings - View settings
/help - Show this message

<i>Bot trades automatically every {interval} minutes</i>
""".format(interval=SLEEP_BETWEEN_RUNS_MINUTES)
                    self._send_telegram(msg)

        except Exception as e:
            # Silent fail for command checking
            pass

    def run(self):
        """Main run loop"""
        cprint("\n" + "=" * 60, "cyan")
        cprint(" Moon Dev Telegram Trading Bot Starting!", "cyan", attrs=['bold'])
        cprint("=" * 60, "cyan")

        cprint(f"\n Exchange: {EXCHANGE}", "yellow")
        cprint(f" Leverage: {LEVERAGE}x", "yellow")
        cprint(f" Interval: Every {SLEEP_BETWEEN_RUNS_MINUTES} minutes", "yellow")
        cprint(f" Tokens: {SYMBOLS if EXCHANGE != 'SOLANA' else MONITORED_TOKENS}", "yellow")

        # Reset daily trades at midnight
        last_reset_date = datetime.now().date()

        while self.running:
            try:
                # Reset daily trades at midnight
                if datetime.now().date() != last_reset_date:
                    self.daily_trades = 0
                    last_reset_date = datetime.now().date()
                    cprint(" Daily trade counter reset", "green")

                # Check for Telegram commands
                self._check_telegram_commands()

                # Run trading cycle
                self.run_trading_cycle()

                # Calculate next run time
                next_run = datetime.now() + timedelta(minutes=SLEEP_BETWEEN_RUNS_MINUTES)
                cprint(f"\n Next run at {next_run.strftime('%H:%M:%S')}", "cyan")

                # Sleep with periodic command checks
                for _ in range(SLEEP_BETWEEN_RUNS_MINUTES * 6):  # Check every 10 seconds
                    if not self.running:
                        break
                    self._check_telegram_commands()
                    time.sleep(10)

            except KeyboardInterrupt:
                cprint("\n\n Shutting down gracefully...", "yellow")
                self.running = False
                self._send_telegram("<b> Bot Stopped</b>\n\nTrading bot has been shut down.")
                break
            except Exception as e:
                cprint(f"\n Error in main loop: {e}", "red")
                self._send_telegram(f"<b> Error</b>\n\n{str(e)}")
                time.sleep(60)  # Wait a minute before retrying


def main():
    """Entry point"""
    agent = TelegramTradingAgent()
    agent.run()


if __name__ == "__main__":
    main()
