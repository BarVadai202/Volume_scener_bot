import os
import threading
import datetime
import pytz
from flask import Flask
import yfinance as yf
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# שרת רשת לשמירה על שירות ער בענן (Render)
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Volume Scanner Bot is active and running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# הטוקן הקבוע של בוט סורק הווליום
TOKEN = "8762564504:AAFY4xJVdXOxD08U6rZ9nQuqE2S0Rl3SQAQ"
USER_CHAT_ID = None
ISRAEL_TZ = pytz.timezone('Asia/Jerusalem')

# 11 סקטורי ה-SPDR המובילים בארה"ב
SECTORS_MAP = {
    "XLK": "טכנולוגיה",
    "XLF": "פיננסים",
    "XLE": "אנרגיה",
    "XLV": "בריאות",
    "XLY": "צרכנות מחזורית",
    "XLI": "תעשייה",
    "XLC": "תקשורת",
    "XLU": "תשתיות",
    "XLB": "חומרים",
    "XLP": "צרכנות בסיסית",
    "VNQ": "נדל\"ן"
}

# סל המניות המובילות בכל סקטור לסריקה ממוקדת
SECTOR_STOCKS = {
    "XLK": ["NVDA", "AAPL", "MSFT", "AVGO", "AMD", "QCOM", "ADBE", "CRM", "TXN", "INTC", "AMAT", "MU"],
    "XLF": ["JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA", "PGR", "SCHW"],
    "XLE": ["XOM", "CVX", "COP", "EOG", "SLB", "OXY", "MPC", "PSX", "VLO", "KMI", "WMB"],
    "XLV": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "PFE", "AMGN", "ISRG", "BMY", "BSX"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "BKNG", "LOW", "TJX", "TGT", "LULU"],
    "XLI": ["GE", "CAT", "UNP", "HON", "BA", "RTX", "LMT", "DE", "UPS", "ETN", "GD"],
    "XLC": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "TMUS", "VZ", "T", "CHTR"],
    "XLU": ["NEE", "SO", "DUK", "CEG", "AEP", "SRE", "VST", "EXC", "XEL"],
    "XLB": ["LIN", "APD", "SHW", "FCX", "ECL", "NEM", "CTVA", "DOW"],
    "XLP": ["PG", "COST", "PEP", "KO", "WMT", "PM", "MDLZ", "CL", "MO"],
    "VNQ": ["PLD", "AMT", "EQIX", "SPG", "O", "WELL", "PSA", "DLR", "CCI"]
}

notified_today = {}
last_reset_date = None

def reset_daily_cache_if_needed():
    global notified_today, last_reset_date
    today = datetime.datetime.now(ISRAEL_TZ).date()
    if last_reset_date != today:
        notified_today = {}
        last_reset_date = today

def calculate_relative_volume(ticker_symbol: str):
    """
    מחשב את היחס בין המחזור הנוכחי היום לבין ממוצע המחזורים ב-20 הימים האחרונים
    """
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="1mo")
        if hist.empty or len(hist) < 3:
            return None

        curr_vol = float(hist['Volume'].iloc[-1])
        curr_close = float(hist['Close'].iloc[-1])

        if len(hist) >= 2:
            prev_close = float(hist['Close'].iloc[-2])
            change_pct = ((curr_close - prev_close) / prev_close) * 100
        else:
            change_pct = 0.0

        past_volumes = hist['Volume'].iloc[:-1].tail(20)
        if past_volumes.empty:
            return None

        avg_vol = float(past_volumes.mean())
        if avg_vol == 0:
            return None

        rvol = curr_vol / avg_vol
        return {
            "rvol": round(rvol, 2),
            "curr_vol": curr_vol,
            "avg_vol": avg_vol,
            "price": round(curr_close, 2),
            "change_pct": round(change_pct, 2)
        }
    except Exception as e:
        print(f"Error calculating volume for {ticker_symbol}: {e}")
        return None

def format_vol(v: float):
    if v >= 1e6:
        return f"{v/1e6:.1f}M"
    elif v >= 1e3:
        return f"{v/1e3:.0f}K"
    return str(int(v))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text(
        "📡 <b>סורק הווליום והסקטורים מוכן לפעולה!</b>\n\n"
        "הבוט סורק באופן אוטומטי כל 15 דקות בשעות המסחר (16:30 עד 23:00 שעון ישראל):\n"
        "• <b>רמה 1 (+15%):</b> זיהוי סקטור חם וצלילה מיידית לסריקת המניות שלו\n"
        "• <b>רמה 2 (+30%):</b> 🔔 התראה על כניסת מחזורים מוגברת\n"
        "• <b>רמה 3 (+50%):</b> 🚨 התראה חריגה על ווליום מוסדי כבד\n\n"
        "פקודות:\n"
        "/scan - הרצת סריקת שוק מקיפה ומיידית כעת\n"
        "/status - בדיקת מצב הסורק",
        parse_mode="HTML"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(ISRAEL_TZ)
    await update.message.reply_text(
        f"📊 <b>סטטוס סורק שוק:</b>\n"
        f"• שעה בישראל: <code>{now.strftime('%H:%M:%S')}</code>\n"
        f"• תדירות סריקה: כל 15 דקות\n"
        f"• התראות שנשלחו בסבב היומי: <b>{len(notified_today)}</b>",
        parse_mode="HTML"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text("🔍 <b>מתחיל סריקה של כל 11 הסקטורים ומניותיהם...</b>", parse_mode="HTML")
    await run_market_scan(context, is_manual=True)
    await update.message.reply_text("🏁 <b>סריקת השוק הושלמה.</b>", parse_mode="HTML")

async def run_market_scan(context: ContextTypes.DEFAULT_TYPE, is_manual: bool = False):
    """סורק סקטורים, וברגע שמזהה ווליום חם בסקטור – צולל ישירות למניות שלו ומדווח עליהן"""
    if not USER_CHAT_ID:
        return

    reset_daily_cache_if_needed()
    hot_sectors_found = 0

    for sec_etf, sec_name in SECTORS_MAP.items():
        data = calculate_relative_volume(sec_etf)
        if not data:
            continue

        rvol = data["rvol"]

        # סקטור נחשב פעיל אם הווליום שלו מעל 15%+ מהממוצע (RVol >= 1.15)
        if rvol >= 1.15:
            hot_sectors_found += 1
            sec_pct_above = int((rvol - 1) * 100)

            if rvol >= 1.50:
                sec_header = f"🚨🚨 <b>סקטור חריג מאוד (+50% ומעלה): {sec_name} ({sec_etf})</b>"
            elif rvol >= 1.30:
                sec_header = f"🔔 <b>סקטור בווליום גבוה (+30% ומעלה): {sec_name} ({sec_etf})</b>"
            else:
                sec_header = f"👀 <b>סקטור בהתעוררות (+15% ומעלה): {sec_name} ({sec_etf})</b>"

            sec_msg = (
                f"{sec_header}\n"
                f"• יחס ווליום (RVol): <b>{rvol:.2f}x</b> ({sec_pct_above:+d}% מהממוצע)\n"
                f"• מחזור שנכנס: {format_vol(data['curr_vol'])} (ממוצע יומי: {format_vol(data['avg_vol'])})\n"
                f"• שינוי שער: ${data['price']} ({data['change_pct']:+.2f}%)\n\n"
                f"⚡ <i>סורק כעת את המניות המובילות ב-{sec_name}...</i>"
            )
            await context.bot.send_message(chat_id=USER_CHAT_ID, text=sec_msg, parse_mode="HTML")

            # --- צלילה מיידית לסריקת כל מניות הסקטור ---
            stocks = SECTOR_STOCKS.get(sec_etf, [])
            stocks_results = []

            for sym in stocks:
                stk = calculate_relative_volume(sym)
                if stk:
                    stocks_results.append((sym, stk))

            # מיון המניות לפי יחס הווליום מהגבוה ביותר לנמוך
            stocks_results.sort(key=lambda x: x[1]["rvol"], reverse=True)

            # סינון מניות שעברו את רף ה-15%+ (RVol >= 1.15)
            hot_stocks = [item for item in stocks_results if item[1]["rvol"] >= 1.15]

            if hot_stocks:
                stk_msg = f"🎯 <b><u>מניות עם כניסת ווליום בסקטור {sec_name} ({sec_etf}):</u></b>\n\n"
                for sym, s_data in hot_stocks:
                    s_rvol = s_data["rvol"]
                    pct_above = int((s_rvol - 1) * 100)

                    if s_rvol >= 1.50:
                        badge = "🚨 <b>מוסדי כבד (+50%)</b>"
                    elif s_rvol >= 1.30:
                        badge = "🔔 <b>ווליום גבוה (+30%)</b>"
                    else:
                        badge = "👀 <b>התעוררות (+15%)</b>"

                    stk_msg += (
                        f"• <b>{sym}</b>: {badge}\n"
                        f"  ↳ יחס מחזור: <b>{s_rvol:.2f}x</b> ({pct_above:+d}%)\n"
                        f"  ↳ מחזור: {format_vol(s_data['curr_vol'])} | שער: ${s_data['price']} ({s_data['change_pct']:+.2f}%)\n\n"
                    )
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=stk_msg, parse_mode="HTML")
            else:
                # אם אף מניה בודדת לא עברה 15%, מציגים את 3 המובילות
                top_3 = stocks_results[:3]
                fallback_msg = (
                    f"ℹ️ בסקטור <b>{sec_name}</b> הווליום מרוכז בעיקרו במדד.\n"
                    f"<b>3 המניות המובילות בווליום יחסי כרגע:</b>\n"
                )
                for sym, s_data in top_3:
                    fallback_msg += f"• <b>{sym}</b>: RVol {s_data['rvol']:.2f}x | שער ${s_data['price']} ({s_data['change_pct']:+.2f}%)\n"
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=fallback_msg, parse_mode="HTML")

    if hot_sectors_found == 0 and is_manual:
        await context.bot.send_message(
            chat_id=USER_CHAT_ID,
            text="😴 <b>אין כרגע חריגות ווליום בסקטורים</b> (אף סקטור לא עבר 15%+ מעל הממוצע). השוק רגוע יחסית.",
            parse_mode="HTML"
        )

def is_market_hours():
    now = datetime.datetime.now(ISRAEL_TZ)
    if now.weekday() >= 5:  # שבת או ראשון
        return False
    market_open = now.replace(hour=16, minute=25, second=0, microsecond=0)
    market_close = now.replace(hour=23, minute=5, second=0, microsecond=0)
    return market_open <= now <= market_close

async def scheduled_scanner_job(context: ContextTypes.DEFAULT_TYPE):
    if is_market_hours():
        await run_market_scan(context, is_manual=False)

def main():
    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    # סריקה אוטומטית כל 15 דקות (900 שניות)
    app.job_queue.run_repeating(scheduled_scanner_job, interval=900, first=20)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("status", status_command))

    print("Volume Scanner Bot is started and listening...")
    app.run_polling()

if __name__ == "__main__":
    main()
