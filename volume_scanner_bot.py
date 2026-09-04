import os
import threading
import datetime
import pytz
from flask import Flask
import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
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

# שים כאן את הטוקן של הבוט החדש שיצרת ב-BotFather
TOKEN = os.environ.get("VOLUME_BOT_TOKEN", "8762564504:AAFY4xJVdXOxD08U6rZ9nQuqE2S0Rl3SQAQ")
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

# מעקב יומי למניעת שליחת אותה התראה שוב ושוב באותו יום
# מבנה: { "XLK": 1.35, "NVDA": 1.52 }
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
    מחשב את היחס בין המחזור הנוכחי היום לבין ממוצע המחזורים ב-20 ימי המסחר האחרונים.
    מחזיר: (rvol, current_vol, avg_vol, price, change_pct)
    """
    try:
        t = yf.Ticker(ticker_symbol)
        # משיכת 30 ימי היסטוריה יומיים
        hist = t.history(period="1mo")
        if hist.empty or len(hist) < 5:
            return None

        # מחזור של היום (הנר האחרון שמתעדכן בחי)
        curr_vol = float(hist['Volume'].iloc[-1])
        curr_close = float(hist['Close'].iloc[-1])

        # חישוב שינוי יומי
        if len(hist) >= 2:
            prev_close = float(hist['Close'].iloc[-2])
            change_pct = ((curr_close - prev_close) / prev_close) * 100
        else:
            change_pct = 0.0

        # ממוצע מחזור ב-20 הימים שקדמו להיום
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
    """עיצוב מספרים במיליונים או באלפים לתצוגה נקייה"""
    if v >= 1e6:
        return f"{v/1e6:.1f}M"
    elif v >= 1e3:
        return f"{v/1e3:.0f}K"
    return str(int(v))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text(
        " radar <b>ברוך הבא לבוט סורק הווליום והסקטורים!</b>\n\n"
        "הבוט סורק כל 15 דקות בשעות המסחר (16:30 עד 23:00):\n"
        "• <b>רמה 1 (+15%):</b> מעקב והיערכות בסקטור\n"
        "• <b>רמה 2 (+30%):</b> 🔔 התראה ראשונית על כניסת כסף\n"
        "• <b>רמה 3 (+50%):</b> 🚨 התראה חריגה על ווליום מוסדי כבד\n\n"
        "פקודות זמינות:\n"
        "/scan - הרצת סריקה מיידית ידנית עכשיו\n"
        "/status - בדיקת מצב סורק הווליום",
        parse_mode="HTML"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text("🔍 <b>מבצע סריקת שוק מלאה לסקטורים ומניות...</b>", parse_mode="HTML")
    await run_market_scan(context)
    await update.message.reply_text("✅ <b>הסריקה הסתיימה בהצלחה.</b>", parse_mode="HTML")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(ISRAEL_TZ)
    await update.message.reply_text(
        f"📊 <b>סטטוס סורק שוק:</b>\n"
        f"• שעה נוכחית בישראל: <code>{now.strftime('%H:%M:%S')}</code>\n"
        f"• תדירות סריקה: כל 15 דקות\n"
        f"• התראות שנשלחו היום: <b>{len(notified_today)}</b> נכסים",
        parse_mode="HTML"
    )

async def run_market_scan(context: ContextTypes.DEFAULT_TYPE):
    """פונקציית הסריקה הראשית שרצה כל 15 דקות"""
    if not USER_CHAT_ID:
        return

    reset_daily_cache_if_needed()
    active_hot_sectors = []

    # --- שלב 1: סריקת 11 הסקטורים ---
    for sec_etf, sec_name in SECTORS_MAP.items():
        data = calculate_relative_volume(sec_etf)
        if not data:
            continue

        rvol = data["rvol"]

        # רמה 1: ווליום גבוה מ-15% (RVol >= 1.15) - נכנס לפוקוס
        if rvol >= 1.15:
            active_hot_sectors.append((sec_etf, sec_name, data))

            # האם הגענו לרמת התראה ראשונית (30%+) או רצינית (50%+)?
            prev_level = notified_today.get(sec_etf, 0)

            if rvol >= 1.50 and prev_level < 1.50:
                notified_today[sec_etf] = 1.50
                msg = (
                    f"🚨🚨 <b><u>התראת ווליום חריגה בסקטור: {sec_name} ({sec_etf})</u></b>\n\n"
                    f"📊 <b>מחזור נוכחי:</b> גבוה ב-<b>{int((rvol - 1)*100)}%+</b> מהממוצע!\n"
                    f"• יחס ווליום (RVol): <b>{rvol:.2f}x</b>\n"
                    f"• מחזור שנכנס: {format_vol(data['curr_vol'])} (ממוצע: {format_vol(data['avg_vol'])})\n"
                    f"• מחיר סקטור: ${data['price']} ({data['change_pct']:+.2f}%)\n\n"
                    "⚡ <i>הבוט מתחיל כעת סריקת עומק של כל מניות הסקטור...</i>"
                )
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=msg, parse_mode="HTML")

            elif rvol >= 1.30 and prev_level < 1.30:
                notified_today[sec_etf] = 1.30
                msg = (
                    f"🔔 <b><u>התראת ווליום ראשונית בסקטור: {sec_name} ({sec_etf})</u></b>\n\n"
                    f"📊 <b>מחזור נוכחי:</b> גבוה ב-<b>{int((rvol - 1)*100)}%+</b> מהממוצע.\n"
                    f"• יחס ווליום (RVol): <b>{rvol:.2f}x</b>\n"
                    f"• מחיר סקטור: ${data['price']} ({data['change_pct']:+.2f}%)\n"
                    "👀 <i>מופעל מעקב על מניות הסקטור.</i>"
                )
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=msg, parse_mode="HTML")

    # --- שלב 2: סריקת מניות בסקטורים שנדלקו (+15% ומעלה) ---
    for sec_etf, sec_name, sec_data in active_hot_sectors:
        stocks = SECTOR_STOCKS.get(sec_etf, [])
        for sym in stocks:
            stk_data = calculate_relative_volume(sym)
            if not stk_data:
                continue

            stk_rvol = stk_data["rvol"]
            prev_stk_level = notified_today.get(sym, 0)

            # בדיקת רמה 3 למניה (מעל 50% מהממוצע)
            if stk_rvol >= 1.50 and prev_stk_level < 1.50:
                notified_today[sym] = 1.50
                msg = (
                    f"🚨🚨 <b><u>ווליום מוסדי כבד במניה: {sym}</u></b>\n\n"
                    f"📂 סקטור: <b>{sec_name} ({sec_etf})</b>\n"
                    f"🔥 <b>חריגת מחזור:</b> <b>{int((stk_rvol - 1)*100)}%+</b> מעל הממוצע!\n"
                    f"• יחס מחזור (RVol): <b>{stk_rvol:.2f}x</b>\n"
                    f"• ווליום נוכחי: <b>{format_vol(stk_data['curr_vol'])}</b> (ממוצע יומי: {format_vol(stk_data['avg_vol'])})\n"
                    f"• שער שוק: <b>${stk_data['price']}</b> ({stk_data['change_pct']:+.2f}%)"
                )
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=msg, parse_mode="HTML")

            # בדיקת רמה 2 למניה (מעל 30% מהממוצע)
            elif stk_rvol >= 1.30 and prev_stk_level < 1.30:
                notified_today[sym] = 1.30
                msg = (
                    f"🔔 <b><u>התראת ווליום עולה במניה: {sym}</u></b>\n\n"
                    f"📂 סקטור: <b>{sec_name} ({sec_etf})</b>\n"
                    f"📈 <b>חריגת מחזור:</b> <b>{int((stk_rvol - 1)*100)}%+</b> מעל הממוצע.\n"
                    f"• יחס מחזור (RVol): <b>{stk_rvol:.2f}x</b>\n"
                    f"• שער שוק: <b>${stk_data['price']}</b> ({stk_data['change_pct']:+.2f}%)"
                )
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=msg, parse_mode="HTML")

def is_market_hours():
    """בודק האם השוק האמריקאי פתוח כעת (שני עד שישי, 16:30 עד 23:00 שעון ישראל)"""
    now = datetime.datetime.now(ISRAEL_TZ)
    if now.weekday() >= 5:  # שבת או ראשון - אין מסחר
        return False
    market_open = now.replace(hour=16, minute=25, second=0, microsecond=0)
    market_close = now.replace(hour=23, minute=5, second=0, microsecond=0)
    return market_open <= now <= market_close

async def scheduled_scanner_job(context: ContextTypes.DEFAULT_TYPE):
    """רץ כל 15 דקות, מבצע סריקה רק אם שעות המסחר פועלות"""
    if is_market_hours():
        await run_market_scan(context)

def main():
    # הפעלת שרת ה-Web ברקע
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
