# Mobile Trading Bot Setup Guide

Control your AI trading bot entirely from your iPhone using Telegram.

## What You Get

- **Autonomous AI Trading**: 6 AI models vote on every trade
- **Push Notifications**: Get alerts for every trade, profit, and loss
- **Mobile Controls**: Pause, resume, or emergency close from your phone
- **Set & Forget**: Bot trades 24/7, you just watch the alerts

## Quick Setup (15 minutes)

### Step 1: Create Your Telegram Bot

1. Open Telegram on your iPhone
2. Search for **@BotFather** and start a chat
3. Send `/newbot`
4. Follow the prompts:
   - Choose a name (e.g., "My Trading Bot")
   - Choose a username (e.g., "my_trading_bot")
5. **Save the bot token** - it looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### Step 2: Get Your Chat ID

1. Message your new bot and send `/start`
2. Open this URL in Safari (replace YOUR_TOKEN):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Look for `"chat":{"id":` - that number is your chat ID
4. **Save your chat ID** - it looks like: `123456789`

### Step 3: Configure the Bot

Add these to your `.env` file:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### Step 4: Deploy & Run

The bot needs to run on a server. Options:

**Option A: Railway (Easiest)**
1. Push code to GitHub
2. Connect to [Railway](https://railway.app)
3. Add environment variables
4. Deploy

**Option B: Render**
1. Push code to GitHub
2. Create new Web Service on [Render](https://render.com)
3. Add environment variables
4. Deploy

**Option C: VPS (Digital Ocean, etc.)**
```bash
# SSH to your server
ssh user@your-server

# Clone the repo
git clone https://github.com/your/repo.git
cd repo

# Install dependencies
pip install -r requirements.txt

# Run with screen (keeps running after disconnect)
screen -S trading
python src/agents/telegram_trading_agent.py
# Press Ctrl+A then D to detach
```

## Telegram Commands

Once running, control your bot with these commands:

| Command | Description |
|---------|-------------|
| `/status` | Check positions, balance, P&L |
| `/pause` | Stop making new trades |
| `/resume` | Resume trading |
| `/closeall` | Emergency close all positions |
| `/settings` | View current configuration |
| `/help` | Show all commands |

## Configuration Options

Edit `telegram_trading_agent.py` to customize:

```python
# Exchange (ASTER, HYPERLIQUID, or SOLANA)
EXCHANGE = "ASTER"

# Position sizing
MAX_POSITION_PERCENTAGE = 50  # % of balance per trade
LEVERAGE = 5                  # 1-125x

# Risk management
STOP_LOSS_PERCENTAGE = 10.0   # Auto-close at -10%
TAKE_PROFIT_PERCENTAGE = 15.0 # Auto-close at +15%

# Safety
MIN_CONFIDENCE_TO_TRADE = 60  # Only trade if AI is 60%+ confident
MAX_DAILY_TRADES = 10         # Max trades per day
COOLDOWN_AFTER_LOSS_MINUTES = 30  # Wait after losing trade

# Tokens
SYMBOLS = ['BTC']  # What to trade
```

## Example Alerts

**Trade Entry:**
```
BUY SIGNAL - BTC

Position Size: $450.00
AI Confidence: 83%
Leverage: 5x

AI Analysis:
Votes: BUY=5, SELL=1, HOLD=0
```

**Take Profit:**
```
TAKE PROFIT - BTC

P&L: +15.23% (+$68.54)
Result: Profit!
```

**Stop Loss:**
```
STOP LOSS - BTC

P&L: -10.12% (-$45.54)
Result: Loss
```

## Recommended Settings for $100

For small accounts, use these conservative settings:

```python
MAX_POSITION_PERCENTAGE = 50   # Risk only half at a time
LEVERAGE = 3                   # Low leverage
STOP_LOSS_PERCENTAGE = 15.0    # Wider stops for volatility
TAKE_PROFIT_PERCENTAGE = 20.0  # Let winners run
MIN_CONFIDENCE_TO_TRADE = 70   # Only high confidence trades
MAX_DAILY_TRADES = 5           # Fewer trades = less fees
```

## Troubleshooting

**Bot not responding?**
- Check the bot token is correct
- Ensure chat ID matches your Telegram account
- Verify the bot is running on your server

**No trades happening?**
- Check if bot is paused (send `/status`)
- AI confidence might be below threshold
- Daily trade limit might be reached

**Position not closing?**
- Use `/closeall` for emergency close
- Check exchange connectivity
- Verify API keys are valid

## Security Notes

- Never share your bot token
- Use a dedicated Telegram account if paranoid
- Keep API keys secure
- Monitor the bot regularly

## Support

- Discord: [Moon Dev Community]
- GitHub Issues: Report bugs and feature requests

---

Built with love by Moon Dev
