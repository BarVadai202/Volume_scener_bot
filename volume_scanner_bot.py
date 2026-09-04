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

web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Volume Scanner Bot is active and running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# הטוקן הקבוע שלך
TOKEN = "8762564504:AAFY4xJVdXOxD08U6rZ9nQuqE2S0Rl3SQAQ"
USER_CHAT_ID = None
ISRAEL_TZ = pytz.timezone('Asia/Jerusalem')

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

def format_vol(v: float):
    if v >= 1e9:
        return f"{v/1e9:.1f}B"
    elif v >= 1e6:
        return f"{v/1e6:.1f}M"
    elif v >= 1e3:
        return f"{v/1e3:.0f}K"
    return str(int(v))

def detect_sustained_volume_period(ticker_symbol: str):
    """
    מנתח האם הנכס נמצא ב*תקופה* של ווליום חריג ועולה, ולא רק ביום בודד.
    בודק:
    1. יחס שבועי (5 ימי מסחר אחרונים) מול ממוצע חודשי/רב-חודשי (30 יום).
    2. שינוי מצטבר מחודש לחודש (MoM Volume).
    3. יחס יומי נוכחי.
    """
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="3mo")
        if hist.empty or len(hist) < 35:
            return None

        # נתונים נוכחיים
        curr_close = float(hist['Close'].iloc[-1])
        prev_close = float(hist['Close'].iloc[-2])
        day_chg = ((curr_close - prev_close) / prev_close) * 100
        curr_vol = float(hist['Volume'].iloc[-1])

        # 1. ניתוח תקופתי: 5 ימים אחרונים מול 30 ימי מסחר קודמים
        last_5_days_vol = hist['Volume'].iloc[-5:]
        avg_5d = float(last_5_days_vol.mean())

        baseline_30d = hist['Volume'].iloc[-35:-5]
        avg_baseline = float(baseline_30d.mean()) if not baseline_30d.empty else 1.0

        # יחס תקופתי (פי כמה השבוע האחרון גבוה מהחודש שקדם לו)
        period_ratio = avg_5d / avg_baseline if avg_baseline > 0 else 1.0
        period_surge_pct = int((period_ratio - 1.0) * 100)

        # 2. ניתוח חודש מול חודש קודם (MoM)
        last_month = hist.iloc[-21:]
        prev_month = hist.iloc[-42:-21]
        vol_last_m = float(last_month['Volume'].sum())
        vol_prev_m = float(prev_month['Volume'].sum())
        mom_change = ((vol_last_m - vol_prev_m) / vol_prev_m) * 100 if vol_prev_m > 0 else 0.0

        # 3. יחס יומי בודד
        avg_20d = float(hist['Volume'].iloc[-21:-1].mean())
        daily_rvol = curr_vol / avg_20d if avg_20d > 0 else 1.0

        # ניסוח הסבר מילולי חכם על התקופה
        if period_surge_pct >= 50 or mom_change >= 50:
            status_desc = "🚨 <b>גל ווליום מוסדי כבד:</b> כל התקופה האחרונה חווה זרימת כספים אגרסיבית מעל 50% מהרגיל."
            is_hot_period = True
        elif period_surge_pct >= 30 or mom_change >= 30:
            status_desc = "🌊 <b>תקופת איסוף עקבית:</b> הממוצע של ימי המסחר האחרונים גבוה ב-30%+ מחודש הבסיס."
            is_hot_period = True
        elif period_surge_pct >= 15 or mom_change >= 15:
            status_desc = "📈 <b>מגמת התעוררות תקופתית:</b> עלייה מצטברת של 15%+ ברמת הווליום הממוצעת."
            is_hot_period = True
        elif daily_rvol >= 1.30 and mom_change < 0:
            status_desc = "⚠️ <b>נר בודד בלבד (אין גל תקופתי):</b> יש קפיצה יומית נקודתית, אך ברמה החודשית הווליום בירידה."
            is_hot_period = False
        else:
            status_desc = "💤 <b>תקופה רגילה/נמוכה:</b> אין חריגה תקופתית משמעותית."
            is_hot_period = False

        return {
            "price": round(curr_close, 2),
            "day_chg": round(day_chg, 2),
            "curr_vol": curr_vol,
            "period_ratio": round(period_ratio, 2),
            "period_surge_pct": period_surge_pct,
            "mom_change": round(mom_change, 1),
            "daily_rvol": round(daily_rvol, 2),
            "status_desc": status_desc,
            "is_hot_period": is_hot_period,
            "avg_5d": avg_5d,
            "avg_baseline": avg_baseline
        }
    except Exception as e:
        print(f"Error checking period for {ticker_symbol}: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text(
        "📡 <b>סורק תקופות ווליום ומגמות שוק מחובר!</b>\n\n"
        "הבוט מתמקד ב<b>תקופות של ווליום עולה</b> (השוואת שבועות וחודשים) ולא בנר בודד ומטעה.\n\n"
        "פקודות:\n"
        "/scan - סריקת תקופות ווליום בכל הסקטורים והמניות עכשיו\n"
        "/status - בדיקת מצב מערכת",
        parse_mode="HTML"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text("🔍 <b>בודק תקופות של ווליום עולה בסקטורים ובמניות...</b>", parse_mode="HTML")
    await run_market_scan(context)
    await update.message.reply_text("🏁 <b>הסריקה הושלמה.</b>", parse_mode="HTML")

async def run_market_scan(context: ContextTypes.DEFAULT_TYPE):
    if not USER_CHAT_ID:
        return

    hot_sectors_found = 0

    for sec_etf, sec_name in SECTORS_MAP.items():
        sec_data = detect_sustained_volume_period(sec_etf)
        if not sec_data:
            continue

        # מסננים: מתריעים רק אם יש תקופה של ווליום עולה (מעל 15%+ בתקופה)
        if sec_data["is_hot_period"]:
            hot_sectors_found += 1

            sec_msg = (
                f"🏢 <b><u>תקופת ווליום עולה בסקטור {sec_name} ({sec_etf})</u></b>\n\n"
                f"{sec_data['status_desc']}\n\n"
                f"📊 <b>נתוני התקופה:</b>\n"
                f"• יחס שבועי מול חודש קודם: <b>{sec_data['period_ratio']:.2f}x</b> ({sec_data['period_surge_pct']:+d}%)\n"
                f"• שינוי ווליום חודש מול חודש (MoM): <b>{sec_data['mom_change']:+.1f}%</b>\n"
                f"• יחס בנר היומי הנוכחי: {sec_data['daily_rvol']:.2f}x\n"
                f"• שער: ${sec_data['price']} ({sec_data['day_chg']:+.2f}%)\n\n"
                f"🔎 <i>סורק מניות בתוך {sec_name} שנמצאות גם הן בגל ווליום תקופתי...</i>"
            )
            await context.bot.send_message(chat_id=USER_CHAT_ID, text=sec_msg, parse_mode="HTML")

            # סריקת מניות הסקטור
            stocks = SECTOR_STOCKS.get(sec_etf, [])
            hot_stocks_list = []
            regular_stocks_list = []

            for sym in stocks:
                s_res = detect_sustained_volume_period(sym)
                if not s_res:
                    continue
                # אם המניה בעצמה בתקופת ווליום עולה
                if s_res["is_hot_period"]:
                    hot_stocks_list.append((sym, s_res))
                else:
                    regular_stocks_list.append((sym, s_res))

            if hot_stocks_list:
                # מיון מהתקופה החמה ביותר
                hot_stocks_list.sort(key=lambda x: x[1]["period_surge_pct"], reverse=True)
                stk_msg = f"🔥 <b><u>מניות שנמצאות בתקופת ווליום עולה ב-{sec_name}:</u></b>\n\n"

                for sym, s in hot_stocks_list:
                    stk_msg += (
                        f"• <b>{sym}</b>: שבועי <b>{s['period_surge_pct']:+d}%</b> | חודשי <b>{s['mom_change']:+.1f}%</b>\n"
                        f"  ↳ {s['status_desc']}\n"
                        f"  ↳ שער: ${s['price']} ({s['day_chg']:+.2f}%) | יחס יומי: {s['daily_rvol']:.2f}x\n\n"
                    )
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=stk_msg, parse_mode="HTML")
            else:
                # אם הסקטור בתקופה עולה אך המניות ספציפית לא עברו את הרף
                top_3 = sorted(regular_stocks_list, key=lambda x: x[1]["period_surge_pct"], reverse=True)[:3]
                fallback = (
                    f"ℹ️ בסקטור <b>{sec_name}</b> גל הווליום מתרכז בעיקר בתעודת הסל ({sec_etf}).\n"
                    f"<b>מצב המניות עם יציבות הווליום היחסית הגבוהה ביותר:</b>\n"
                )
                for sym, s in top_3:
                    fallback += f"• <b>{sym}</b>: תקופתי {s['period_surge_pct']:+d}% | חודשי {s['mom_change']:+.1f}% (שער ${s['price']})\n"
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=fallback, parse_mode="HTML")

    if hot_sectors_found == 0:
        await context.bot.send_message(
            chat_id=USER_CHAT_ID,
            text="😴 <b>אין כרגע תקופת ווליום עולה באף סקטור.</b>\nכל הסקטורים נמצאים ברמת פעילות שגרתית או נמוכה מהממוצע.",
            parse_mode="HTML"
        )

def is_market_hours():
    now = datetime.datetime.now(ISRAEL_TZ)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=16, minute=25, second=0, microsecond=0)
    market_close = now.replace(hour=23, minute=5, second=0, microsecond=0)
    return market_open <= now <= market_close

async def scheduled_scanner_job(context: ContextTypes.DEFAULT_TYPE):
    if is_market_hours():
        await run_market_scan(context)

def main():
    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    app.job_queue.run_repeating(scheduled_scanner_job, interval=900, first=20)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan_command))

    print("Volume Scanner Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
