"""
╔══════════════════════════════════════════════════════════════╗
║   XAUUSD ProBot — Telegram Alerts + News Sentiment          ║
║   Receives TradingView webhooks → analyses news → Telegram  ║
╚══════════════════════════════════════════════════════════════╝

SETUP (5 minutes):
  1. pip install flask requests python-telegram-bot newsapi-python vaderSentiment

  2. Create Telegram bot:
       → Open Telegram → search @BotFather → /newbot
       → Copy the TOKEN it gives you → paste in TELEGRAM_TOKEN below

  3. Get your Telegram Chat ID:
       → Start your new bot (send it /start)
       → Visit: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
       → Copy the "id" number inside "chat" → paste in CHAT_ID below

  4. Get free NewsAPI key:
       → Register at newsapi.org (free, 100 req/day)
       → Paste key in NEWS_API_KEY below

  5. Deploy free on Railway or Render:
       → railway.app or render.com → "New Web Service" → paste this file
       → Copy your public URL → use as TradingView Webhook URL

  6. In TradingView Alert → Webhook URL:
       https://YOUR-APP-URL.railway.app/webhook
"""

import os, json, time, threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import requests

# ─── CONFIGURATION ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID        = os.environ.get("CHAT_ID",         "YOUR_CHAT_ID_HERE")
NEWS_API_KEY   = os.environ.get("NEWS_API_KEY",     "YOUR_NEWSAPI_KEY_HERE")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET",   "xauusd_probot_2024")

# News keywords that affect gold
GOLD_KEYWORDS = [
    "gold", "XAU", "XAUUSD", "federal reserve", "fed rate", "inflation",
    "CPI", "interest rate", "US dollar", "DXY", "geopolitical", "war",
    "Middle East", "China economy", "recession", "safe haven", "treasury",
    "jobs report", "NFP", "FOMC", "Powell", "ECB", "central bank"
]

# Sentiment keywords → scores
BULLISH_WORDS = [
    "surge", "rally", "rise", "gain", "jump", "spike", "soar", "climb",
    "breakout", "bullish", "safe haven", "war", "conflict", "crisis",
    "inflation rises", "weak dollar", "rate cut", "dovish", "uncertainty",
    "geopolitical tension", "fear", "recession risk", "gold demand"
]
BEARISH_WORDS = [
    "fall", "drop", "decline", "plunge", "crash", "sell off", "bearish",
    "rate hike", "hawkish", "strong dollar", "recovery", "optimism",
    "risk on", "profit taking", "overbought", "resistance", "gold drops"
]

app = Flask(__name__)
signal_log = []
news_cache = {"articles": [], "sentiment": 0, "last_fetch": 0}

# ─── TELEGRAM ──────────────────────────────────────────────────
def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ─── NEWS SENTIMENT ────────────────────────────────────────────
def fetch_news() -> dict:
    """Fetch gold-related news and compute sentiment score -100 to +100"""
    now = time.time()
    if now - news_cache["last_fetch"] < 900:  # cache 15 min
        return news_cache

    articles = []
    sentiment_score = 0

    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": "gold OR XAUUSD OR \"gold price\" OR \"federal reserve\" OR inflation",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 15,
            "apiKey": NEWS_API_KEY
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            raw_articles = data.get("articles", [])

            scores = []
            for art in raw_articles[:10]:
                title = (art.get("title") or "").lower()
                desc  = (art.get("description") or "").lower()
                text  = title + " " + desc

                # Check if gold-relevant
                if not any(k.lower() in text for k in GOLD_KEYWORDS[:8]):
                    continue

                # Score the article
                bull = sum(1 for w in BULLISH_WORDS if w.lower() in text)
                bear = sum(1 for w in BEARISH_WORDS if w.lower() in text)
                art_score = (bull - bear) * 10
                art_score = max(-50, min(50, art_score))
                scores.append(art_score)

                articles.append({
                    "title":     art.get("title", "")[:90],
                    "source":    art.get("source", {}).get("name", ""),
                    "url":       art.get("url", ""),
                    "published": art.get("publishedAt", "")[:16].replace("T", " "),
                    "score":     art_score,
                    "sentiment": "🟢 Bullish" if art_score > 5 else "🔴 Bearish" if art_score < -5 else "⚪ Neutral"
                })

            sentiment_score = round(sum(scores) / len(scores)) if scores else 0

    except Exception as e:
        print(f"News fetch error: {e}")

    news_cache.update({
        "articles":     articles[:6],
        "sentiment":    sentiment_score,
        "last_fetch":   now,
        "label":        "🟢 BULLISH" if sentiment_score > 10 else
                        "🔴 BEARISH" if sentiment_score < -10 else
                        "⚪ NEUTRAL",
        "emoji":        "🟢" if sentiment_score > 10 else
                        "🔴" if sentiment_score < -10 else "⚪"
    })
    return news_cache

def news_aligns_with_signal(signal_action: str, sentiment: int) -> tuple:
    """Returns (aligns: bool, strength: str, note: str)"""
    if signal_action == "BUY":
        if sentiment > 15:
            return True,  "STRONG", "News strongly supports gold rally"
        elif sentiment > 5:
            return True,  "MODERATE", "News mildly supports this trade"
        elif sentiment < -15:
            return False, "WEAK", "⚠️ News sentiment contradicts BUY — caution"
        else:
            return True,  "NEUTRAL", "News sentiment is neutral"
    else:  # SELL
        if sentiment < -15:
            return True,  "STRONG", "News strongly supports gold decline"
        elif sentiment < -5:
            return True,  "MODERATE", "News mildly supports this trade"
        elif sentiment > 15:
            return False, "WEAK", "⚠️ News sentiment contradicts SELL — caution"
        else:
            return True,  "NEUTRAL", "News sentiment is neutral"

# ─── FORMAT ALERT MESSAGE ──────────────────────────────────────
def build_alert_message(signal: dict, news: dict) -> str:
    action   = signal.get("action", "?")
    price    = signal.get("price",  0)
    conf     = signal.get("confluence", 0)
    sl       = signal.get("sl",   0)
    tp1      = signal.get("tp1",  0)
    tp2      = signal.get("tp2",  0)
    tp3      = signal.get("tp3",  0)
    atr      = signal.get("atr",  0)
    rsi      = signal.get("rsi",  0)
    adx      = signal.get("adx",  0)
    tf       = signal.get("timeframe", "5")
    sym      = signal.get("symbol", "XAUUSD")
    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sentiment   = news.get("sentiment", 0)
    news_label  = news.get("label", "⚪ NEUTRAL")
    articles    = news.get("articles", [])
    aligns, strength, note = news_aligns_with_signal(action, sentiment)

    action_emoji = "🟢" if action == "BUY" else "🔴"
    signal_emoji = "📈" if action == "BUY" else "📉"
    conf_bar_len = round(conf / 10)
    conf_bar = "█" * conf_bar_len + "░" * (10 - conf_bar_len)

    align_emoji = "✅" if aligns else "⚠️"
    strength_emoji = {"STRONG": "💪", "MODERATE": "👍", "NEUTRAL": "➖", "WEAK": "⚠️"}.get(strength, "➖")

    # Build news section
    news_lines = ""
    for i, art in enumerate(articles[:3], 1):
        news_lines += f"\n  {art['sentiment']} <b>{art['title'][:70]}…</b>\n  <i>{art['source']} · {art['published']}</i>\n"

    rr1 = round(abs(tp1 - price) / max(abs(sl - price), 0.001), 1)
    rr2 = round(abs(tp2 - price) / max(abs(sl - price), 0.001), 1)
    rr3 = round(abs(tp3 - price) / max(abs(sl - price), 0.001), 1)

    msg = f"""{signal_emoji} <b>{action_emoji} {action} SIGNAL — {sym} {tf}M</b>
━━━━━━━━━━━━━━━━━━━━

<b>📊 SIGNAL DETAILS</b>
Entry Price:   <b>${price:,.3f}</b>
Confluence:    <b>{conf}%</b>  [{conf_bar}]
RSI:           {rsi}  |  ADX: {adx}
Time:          {now_str}

<b>💰 TRADE LEVELS</b>
🛑 Stop Loss:  <b>${sl:,.3f}</b>  (−{abs(price-sl):.2f})
🎯 TP 1:       <b>${tp1:,.3f}</b>  (+{abs(tp1-price):.2f})  R:R 1:{rr1}
🎯 TP 2:       <b>${tp2:,.3f}</b>  (+{abs(tp2-price):.2f})  R:R 1:{rr2}
🎯 TP 3:       <b>${tp3:,.3f}</b>  (+{abs(tp3-price):.2f})  R:R 1:{rr3}
ATR (14):      ${atr:,.3f}

<b>📰 NEWS SENTIMENT ANALYSIS</b>
Overall:       <b>{news_label}</b>  (score: {sentiment:+d}/100)
Alignment:     {align_emoji} {strength} — {note}
{news_lines}
<b>⚡ CONFLUENCE BREAKDOWN</b>
Signal passes 80% threshold ✅
12 indicators → net score qualifies
{"✅ News confirms this trade" if aligns and strength in ["STRONG","MODERATE"] else "⚠️ Trade against news — size down" if not aligns else "ℹ️ Neutral news environment"}

━━━━━━━━━━━━━━━━━━━━
<i>🤖 ProBot80 · Always use risk management</i>"""

    return msg

# ─── WEBHOOK ENDPOINT ──────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive TradingView alert and send Telegram message"""
    try:
        # Parse incoming payload
        raw = request.get_data(as_text=True)
        try:
            signal = json.loads(raw)
        except json.JSONDecodeError:
            # Try to parse URL-encoded or plain text
            signal = {"action": "UNKNOWN", "price": 0, "confluence": 0}

        action = signal.get("action", "").upper()
        if action not in ("BUY", "SELL"):
            return jsonify({"status": "ignored", "reason": "not BUY/SELL"}), 200

        conf = signal.get("confluence", 0)
        if conf < 80:
            return jsonify({"status": "ignored", "reason": f"confluence {conf}% < 80%"}), 200

        # Fetch news (cached 15 min)
        news = fetch_news()

        # Build and send message
        msg = build_alert_message(signal, news)
        sent = send_telegram(msg)

        # Log
        log_entry = {
            "time":        datetime.now(timezone.utc).isoformat(),
            "action":      action,
            "price":       signal.get("price"),
            "confluence":  conf,
            "news_sent":   news.get("label"),
            "telegram_ok": sent
        }
        signal_log.append(log_entry)
        if len(signal_log) > 100:
            signal_log.pop(0)

        print(f"[{log_entry['time']}] {action} @ {signal.get('price')} | conf={conf}% | telegram={'OK' if sent else 'FAILED'}")
        return jsonify({"status": "ok", "telegram": sent}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ─── NEWS DIGEST ENDPOINT ──────────────────────────────────────
@app.route("/news", methods=["GET"])
def news_digest():
    """Manually trigger a news digest to Telegram"""
    news = fetch_news()
    articles = news.get("articles", [])
    sentiment = news.get("sentiment", 0)
    label = news.get("label", "⚪ NEUTRAL")

    lines = ""
    for i, a in enumerate(articles[:5], 1):
        lines += f"\n{i}. {a['sentiment']} <b>{a['title'][:75]}</b>\n   <i>{a['source']} · {a['published']}</i>\n"

    msg = f"""📰 <b>GOLD NEWS DIGEST</b>
━━━━━━━━━━━━━━━━━
Overall Sentiment: <b>{label}</b>  ({sentiment:+d}/100)
Updated: {datetime.now(timezone.utc).strftime('%H:%M UTC')}

{lines}
━━━━━━━━━━━━━━━━━
<i>🤖 ProBot80 News Engine</i>"""

    send_telegram(msg)
    return jsonify({"status": "sent", "articles": len(articles), "sentiment": sentiment})

# ─── STATUS ENDPOINT ───────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "status":      "running",
        "signals_fired": len(signal_log),
        "last_signal": signal_log[-1] if signal_log else None,
        "news_sentiment": news_cache.get("sentiment", "not fetched"),
        "news_label":  news_cache.get("label", "not fetched"),
        "uptime":      "ok"
    })

# ─── STARTUP TEST ──────────────────────────────────────────────
@app.route("/test", methods=["GET"])
def test_alert():
    """Send a test alert to verify Telegram connection"""
    test_signal = {
        "symbol": "XAUUSD", "timeframe": "5", "action": "BUY",
        "price": 4762.935, "confluence": 84, "sl": 4754.72,
        "tp1": 4776.84, "tp2": 4786.32, "tp3": 4800.23,
        "atr": 4.563, "adx": 31.4, "rsi": 28.7
    }
    news = fetch_news()
    msg = build_alert_message(test_signal, news)
    sent = send_telegram(msg)
    return jsonify({"status": "test sent" if sent else "FAILED — check TELEGRAM_TOKEN and CHAT_ID", "ok": sent})

@app.route("/", methods=["GET"])
def index():
    return """<html><body style="font-family:monospace;padding:2rem;background:#0d1117;color:#e6edf3">
    <h2>🤖 XAUUSD ProBot80</h2>
    <p>Webhook receiver + News sentiment + Telegram alerts</p>
    <ul>
      <li><a href="/test" style="color:#58a6ff">GET /test</a> — send test alert to Telegram</li>
      <li><a href="/news" style="color:#58a6ff">GET /news</a> — send gold news digest</li>
      <li><a href="/status" style="color:#58a6ff">GET /status</a> — check bot status</li>
      <li>POST /webhook — TradingView alert endpoint</li>
    </ul>
    </body></html>"""

# ─── SCHEDULED NEWS DIGEST (every 4 hours) ─────────────────────
def scheduled_news_loop():
    time.sleep(30)  # wait for startup
    while True:
        try:
            news = fetch_news()
            articles = news.get("articles", [])
            if articles:
                lines = ""
                for i, a in enumerate(articles[:4], 1):
                    lines += f"\n{i}. {a['sentiment']} <b>{a['title'][:75]}</b>\n   <i>{a['source']}</i>\n"
                msg = f"""🕐 <b>SCHEDULED GOLD NEWS UPDATE</b>
━━━━━━━━━━━━━━━━━
Sentiment: <b>{news.get('label')}</b>  ({news.get('sentiment',0):+d}/100)
{lines}
<i>Next update in 4 hours · ProBot80</i>"""
                send_telegram(msg)
        except Exception as e:
            print(f"Scheduled news error: {e}")
        time.sleep(4 * 3600)  # every 4 hours

if __name__ == "__main__":
    # Send startup message to Telegram
    startup_msg = """🤖 <b>ProBot80 is ONLINE</b>

✅ Webhook receiver: active
✅ News engine: ready
✅ 80% confluence filter: on
✅ Telegram alerts: connected

Send /test to your bot or visit /test endpoint to verify.
Waiting for TradingView signals…"""
    threading.Thread(target=lambda: (time.sleep(3), send_telegram(startup_msg)), daemon=True).start()
    threading.Thread(target=scheduled_news_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 5000))
    print(f"ProBot80 running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
