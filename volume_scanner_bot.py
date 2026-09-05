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

web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Market Scanner Bot is active and running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# הטוקן הקבוע שלך
TOKEN = "8762564504:AAFY4xJVdXOxD08U6rZ9nQuqE2S0Rl3SQAQ"
USER_CHAT_ID = None
ISRAEL_TZ = pytz.timezone('Asia/Jerusalem')

SECTORS_MAP = {
    "XLK": "טכנולוגיה", "XLF": "פיננסים", "XLE": "אנרגיה",
    "XLV": "בריאות", "XLY": "צרכנות מחזורית", "XLI": "תעשייה",
    "XLC": "תקשורת", "XLU": "תשתיות", "XLB": "חומרים",
    "XLP": "צרכנות בסיסית", "VNQ": "נדל\"ן"
}

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

# סל מניות רחב לסריקת גאפים ומומנטום
SCAN_UNIVERSE = sorted(list(set([stock for sublist in SECTOR_STOCKS.values() for stock in sublist] + [
    "PLTR", "COIN", "SMCI", "ARM", "PANW", "CRWD", "MARA", "RIOT", "BABA", "BIDU", 
    "UBER", "ABNB", "SNOW", "SHOP", "NET", "MDB", "DDOG", "ROKU", "AFRM", "HOOD"
])))

def format_vol(v: float):
    if v >= 1e9:
        return f"{v/1e9:.2f}B"
    elif v >= 1e6:
        return f"{v/1e6:.2f}M"
    elif v >= 1e3:
        return f"{v/1e3:.0f}K"
    return str(int(v))

def build_menu():
    keyboard = [
        [InlineKeyboardButton("🔍 1. סריקת שוק וסקטורים מלאה", callback_data="btn_scan_market")],
        [InlineKeyboardButton("⚡ 2. סורק גאפים בפתיחה (Gap > 7% | Vol > 1M | > $10)", callback_data="btn_scan_gaps")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- לוגיקת אופציה 1: סריקת שוק וסקטורים ---

def detect_sustained_volume_period(ticker_symbol: str):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="3mo")
        if hist.empty or len(hist) < 35:
            return None

        curr_close = float(hist['Close'].iloc[-1])
        prev_close = float(hist['Close'].iloc[-2])
        day_chg = ((curr_close - prev_close) / prev_close) * 100
        curr_vol = float(hist['Volume'].iloc[-1])

        last_5_days_vol = hist['Volume'].iloc[-5:]
        avg_5d = float(last_5_days_vol.mean())

        baseline_30d = hist['Volume'].iloc[-35:-5]
        avg_baseline = float(baseline_30d.mean()) if not baseline_30d.empty else 1.0

        period_ratio = avg_5d / avg_baseline if avg_baseline > 0 else 1.0
        period_surge_pct = int((period_ratio - 1.0) * 100)

        last_month = hist.iloc[-21:]
        prev_month = hist.iloc[-42:-21]
        vol_last_m = float(last_month['Volume'].sum())
        vol_prev_m = float(prev_month['Volume'].sum())
        mom_change = ((vol_last_m - vol_prev_m) / vol_prev_m) * 100 if vol_prev_m > 0 else 0.0

        avg_20d = float(hist['Volume'].iloc[-21:-1].mean())
        daily_rvol = curr_vol / avg_20d if avg_20d > 0 else 1.0

        is_hot_period = (period_surge_pct >= 15 or mom_change >= 15 or daily_rvol >= 1.30)

        return {
            "price": round(curr_close, 2),
            "day_chg": round(day_chg, 2),
            "curr_vol": curr_vol,
            "period_ratio": round(period_ratio, 2),
            "period_surge_pct": period_surge_pct,
            "mom_change": round(mom_change, 1),
            "daily_rvol": round(daily_rvol, 2),
            "is_hot_period": is_hot_period
        }
    except Exception as e:
        print(f"Error checking {ticker_symbol}: {e}")
        return None

async def execute_market_scan(bot, chat_id: int):
    await bot.send_message(chat_id=chat_id, text="🔍 <b>מתחיל סריקת שוק וסקטורים...</b>", parse_mode="HTML")
    hot_sectors_found = 0

    for sec_etf, sec_name in SECTORS_MAP.items():
        sec_data = detect_sustained_volume_period(sec_etf)
        if not sec_data or not sec_data["is_hot_period"]:
            continue

        hot_sectors_found += 1
        sec_msg = (
            f"🏢 <b><u>תקופת ווליום עולה: {sec_name} ({sec_etf})</u></b>\n\n"
            f"• יחס שבועי מול חודש קודם: <b>{sec_data['period_ratio']:.2f}x</b> ({sec_data['period_surge_pct']:+d}%)\n"
            f"• שינוי ווליום MoM: <b>{sec_data['mom_change']:+.1f}%</b>\n"
            f"• יחס מחזור יומי: <b>{sec_data['daily_rvol']:.2f}x</b>\n"
            f"• שער נוכחי: ${sec_data['price']} ({sec_data['day_chg']:+.2f}%)\n\n"
            f"🔎 <i>סורק מניות מובילות בתוך הסקטור...</i>"
        )
        await bot.send_message(chat_id=chat_id, text=sec_msg, parse_mode="HTML")

        stocks = SECTOR_STOCKS.get(sec_etf, [])
        hot_stocks = []
        for sym in stocks:
            s_res = detect_sustained_volume_period(sym)
            if s_res and s_res["is_hot_period"]:
                hot_stocks.append((sym, s_res))

        if hot_stocks:
            hot_stocks.sort(key=lambda x: x[1]["daily_rvol"], reverse=True)
            stk_msg = f"🔥 <b>מניות עם ווליום עולה ב-{sec_name}:</b>\n\n"
            for sym, s in hot_stocks:
                stk_msg += (
                    f"• <b>{sym}</b>: יומי <b>{s['daily_rvol']:.2f}x</b> | שבועי <b>{s['period_surge_pct']:+d}%</b>\n"
                    f"  ↳ מחזור: {format_vol(s['curr_vol'])} | שער: ${s['price']} ({s['day_chg']:+.2f}%)\n\n"
                )
            await bot.send_message(chat_id=chat_id, text=stk_msg, parse_mode="HTML")

    if hot_sectors_found == 0:
        await bot.send_message(chat_id=chat_id, text="😴 <b>אין כרגע חריגות ווליום בסקטורים.</b> הפעילות שגרתית.", parse_mode="HTML")

    await bot.send_message(chat_id=chat_id, text="🏁 <b>סריקת השוק הסתיימה.</b>", reply_markup=build_menu(), parse_mode="HTML")

# --- לוגיקת אופציה 2: סורק גאפים בפתיחה ---

def check_gap_and_volume(ticker_symbol: str):
    """
    בודק:
    1. ווליום נוכחי > 1,000,000 מניות
    2. מחיר נוכחי > $10
    3. פתיחה בגאפ של מעל 7%+ או ירידה מעל 7%- ביחס לסגירה הקודמת
    """
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="2d")
        if len(hist) < 2:
            return None

        prev_close = float(hist['Close'].iloc[-2])
        curr_open = float(hist['Open'].iloc[-1])
        curr_price = float(hist['Close'].iloc[-1])
        curr_volume = float(hist['Volume'].iloc[-1])

        # תנאי 1: מחיר מעל $10
        if curr_price < 10.0:
            return None

        # תנאי 2: ווליום מעל 1M מניות
        if curr_volume < 1_000_000:
            return None

        # תנאי 3: גאפ פתיחה מעל 7% (למעלה או למטה)
        gap_pct = ((curr_open - prev_close) / prev_close) * 100
        current_chg_pct = ((curr_price - prev_close) / prev_close) * 100

        if abs(gap_pct) >= 7.0 or abs(current_chg_pct) >= 7.0:
            return {
                "symbol": ticker_symbol,
                "price": round(curr_price, 2),
                "open": round(curr_open, 2),
                "prev_close": round(prev_close, 2),
                "gap_pct": round(gap_pct, 2),
                "current_chg_pct": round(current_chg_pct, 2),
                "volume": curr_volume
            }
    except Exception:
        pass
    return None

async def execute_gap_scan(bot, chat_id: int):
    await bot.send_message(
        chat_id=chat_id,
        text="⚡ <b>מבצע סריקת גאפים ומומנטום...</b>\nתנאים: ווליום > 1M | מחיר > $10 | גאפ > 7%",
        parse_mode="HTML"
    )

    matches = []
    for sym in SCAN_UNIVERSE:
        res = check_gap_and_volume(sym)
        if res:
            matches.append(res)

    if matches:
        matches.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
        msg = f"🎯 <b><u>נמצאו {len(matches)} מניות העונות להגדרות הגאפ והווליום:</u></b>\n\n"
        for m in matches:
            direction_icon = "🟢 זינוק (Gap Up)" if m["gap_pct"] > 0 else "🔴 נפילה (Gap Down)"
            msg += (
                f"• <b>{m['symbol']}</b> | {direction_icon}\n"
                f"  ↳ גאפ פתיחה: <b>{m['gap_pct']:+.2f}%</b> (פתיחה: ${m['open']} | סגירה קודמת: ${m['prev_close']})\n"
                f"  ↳ שער נוכחי: <b>${m['price']}</b> ({m['current_chg_pct']:+.2f}%)\n"
                f"  ↳ מחזור מסחר: <b>{format_vol(m['volume'])}</b> מניות\n\n"
            )
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
    else:
        await bot.send_message(
            chat_id=chat_id,
            text="ℹ️ לא נמצאו כרגע מניות העונות במדויק לשלושת התנאים (מחיר מעל $10, ווליום מעל 1M וגאפ מעל 7%).",
            parse_mode="HTML"
        )

    await bot.send_message(chat_id=chat_id, text="בחר פעולה:", reply_markup=build_menu(), parse_mode="HTML")

# --- תפריט ואירועים ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    text = (
        "👋 <b>ברוך הבא למערכת הסריקה המתקדמת!</b>\n\n"
        "בחר אפשרות לביצוע מיידי בלחיצה:\n"
        "1️⃣ <b>סריקת שוק וסקטורים:</b> בודק זרימת כספים וסקטורים חמים (מתוזמן אוטומטית ל-16:45 ו-22:30).\n"
        "2️⃣ <b>סורק גאפים ומומנטום בפתיחה:</b> מאתר מניות עם ווליום מעל 1M, מחיר מעל $10 וגאפ מעל 7% (מתוזמן אוטומטית ל-16:40)."
    )
    await update.message.reply_text(text, reply_markup=build_menu(), parse_mode="HTML")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "btn_scan_market":
        await execute_market_scan(context.bot, chat_id)
    elif data == "btn_scan_gaps":
        await execute_gap_scan(context.bot, chat_id)

# --- תזמונים אוטומטיים קבועים ---

async def job_morning_gaps(context: ContextTypes.DEFAULT_TYPE):
    """סריקת גאפים ומומנטום ב-16:40 (10 דקות אחרי הפתיחה)"""
    if USER_CHAT_ID:
        await context.bot.send_message(chat_id=USER_CHAT_ID, text="⏰ <b>התחלת יום המסחר: מפעיל סורק גאפים ומומנטום...</b>", parse_mode="HTML")
        await execute_gap_scan(context.bot, USER_CHAT_ID)

async def job_market_open_scan(context: ContextTypes.DEFAULT_TYPE):
    """סריקת שוק וסקטורים ראשונה ב-16:45 (רבע שעה אחרי הפתיחה)"""
    if USER_CHAT_ID:
        await context.bot.send_message(chat_id=USER_CHAT_ID, text="⏰ <b>סריקת שוק וסקטורים יומית (תחילת המסחר):</b>", parse_mode="HTML")
        await execute_market_scan(context.bot, USER_CHAT_ID)

async def job_market_close_scan(context: ContextTypes.DEFAULT_TYPE):
    """סריקת שוק וסקטורים שנייה ב-22:30 (חצי שעה לפני הנעילה)"""
    if USER_CHAT_ID:
        await context.bot.send_message(chat_id=USER_CHAT_ID, text="⏰ <b>סריקת שוק וסקטורים (חצי שעה לנעילת המסחר):</b>", parse_mode="HTML")
        await execute_market_scan(context.bot, USER_CHAT_ID)

def main():
    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    job_queue = app.job_queue
    trading_days = (0, 1, 2, 3, 4)  # שני עד שישי

    # 1. סורק גאפים ומומנטום ב-16:40
    job_queue.run_daily(job_morning_gaps, time=datetime.time(hour=16, minute=40, tzinfo=ISRAEL_TZ), days=trading_days)

    # 2. סריקת שוק בתחילת המסחר ב-16:45
    job_queue.run_daily(job_market_open_scan, time=datetime.time(hour=16, minute=45, tzinfo=ISRAEL_TZ), days=trading_days)

    # 3. סריקת שוק חצי שעה לפני הנעילה ב-22:30
    job_queue.run_daily(job_market_close_scan, time=datetime.time(hour=22, minute=30, tzinfo=ISRAEL_TZ), days=trading_days)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("Market & Gap Scanner Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
