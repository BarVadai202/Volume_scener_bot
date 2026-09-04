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

def analyze_volume_trends(ticker_symbol: str):
    """
    מנתח גם ווליום יומי וגם ווליום חודשי מצטבר (30 יום אחרונים מול 30 יום שקדמו להם)
    """
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="3mo")
        if hist.empty or len(hist) < 40:
            return None

        # 1. חישוב ווליום יומי
        curr_vol = float(hist['Volume'].iloc[-1])
        curr_close = float(hist['Close'].iloc[-1])
        prev_close = float(hist['Close'].iloc[-2])
        day_change_pct = ((curr_close - prev_close) / prev_close) * 100

        past_20_vol = hist['Volume'].iloc[-21:-1]
        avg_20_vol = float(past_20_vol.mean()) if not past_20_vol.empty else 1.0
        daily_rvol = curr_vol / avg_20_vol if avg_20_vol > 0 else 1.0

        # 2. חישוב ווליום חודשי מצטבר (Month over Month)
        last_month = hist.iloc[-21:]
        prev_month = hist.iloc[-42:-21]

        vol_last_month = float(last_month['Volume'].sum())
        vol_prev_month = float(prev_month['Volume'].sum())

        mom_vol_change_pct = ((vol_last_month - vol_prev_month) / vol_prev_month) * 100 if vol_prev_month > 0 else 0.0

        # מדד התמדה: כמה ימים בחודש האחרון הווליום היה מעל הממוצע של 20 יום
        days_above_avg = int((last_month['Volume'] > avg_20_vol).sum())
        total_days = len(last_month)

        return {
            "price": round(curr_close, 2),
            "day_change_pct": round(day_change_pct, 2),
            "daily_rvol": round(daily_rvol, 2),
            "curr_vol": curr_vol,
            "avg_20_vol": avg_20_vol,
            "mom_vol_change_pct": round(mom_vol_change_pct, 1),
            "vol_last_month": vol_last_month,
            "vol_prev_month": vol_prev_month,
            "days_above_avg": days_above_avg,
            "total_days": total_days
        }
    except Exception as e:
        print(f"Error analyzing trend for {ticker_symbol}: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text(
        "📡 <b>סורק ווליום חכם (יומי + מגמות חודשיות) מחובר!</b>\n\n"
        "הבוט מזהה לא רק קפיצות יומיות, אלא <b>תקופות של ווליום חריג (30%+ מחודש לחודש)</b> המעידות על כניסת כסף מוסדי מסיבי.\n\n"
        "פקודות:\n"
        "/scan - הרצת סריקת שוק מקיפה כעת\n"
        "/monthly - הצגת סקטורים ומניות שנמצאים ברצף ווליום חודשי עולה",
        parse_mode="HTML"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text("🔍 <b>מתחיל סריקה של שוק המניות והסקטורים...</b>", parse_mode="HTML")
    await run_market_scan(context)
    await update.message.reply_text("🏁 <b>הסריקה הושלמה.</b>", parse_mode="HTML")

async def monthly_trend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.message.chat_id
    await update.message.reply_text("⏳ <b>מנתח סקטורים שנמצאים בגל ווליום חודשי עולה (+30% ומעלה)...</b>", parse_mode="HTML")

    found_any = False
    for sec_etf, sec_name in SECTORS_MAP.items():
        data = analyze_volume_trends(sec_etf)
        if not data:
            continue

        if data["mom_vol_change_pct"] >= 30.0:
            found_any = True
            msg = (
                f"📈 <b><u>גל ווליום חודשי חריג בסקטור {sec_name} ({sec_etf})</u></b>\n\n"
                f"• <b>עלייה חודשית במחזור:</b> <b>+{data['mom_vol_change_pct']}%</b> בהשוואה לחודש הקודם!\n"
                f"• <b>מחזור 30 יום:</b> {format_vol(data['vol_last_month'])} (חודש קודם: {format_vol(data['vol_prev_month'])})\n"
                f"• <b>ימי פעילות מוסדית:</b> ב-{data['days_above_avg']} מתוך {data['total_days']} ימי מסחר הווליום היה מעל הממוצע.\n"
                f"• <b>הסבר תנועה:</b> כסף מוסדי מזרים ביקושים עקביים לסקטור זה לאורך זמן.\n"
                f"• שער נוכחי: ${data['price']} ({data['day_change_pct']:+.2f}% היום)"
            )
            await update.message.reply_text(msg, parse_mode="HTML")

    if not found_any:
        await update.message.reply_text("ℹ️ לא נמצאו כרגע סקטורים עם עליית ווליום חודשית של 30%+.", parse_mode="HTML")

async def run_market_scan(context: ContextTypes.DEFAULT_TYPE):
    if not USER_CHAT_ID:
        return

    hot_sectors = []
    for sec_etf, sec_name in SECTORS_MAP.items():
        data = analyze_volume_trends(sec_etf)
        if not data:
            continue

        # בדיקה האם הסקטור חווה קפיצה יומית של 15%+ או עלייה חודשית של 30%+
        is_daily_hot = data["daily_rvol"] >= 1.15
        is_monthly_surge = data["mom_vol_change_pct"] >= 30.0

        if is_daily_hot or is_monthly_surge:
            hot_sectors.append((sec_etf, sec_name, data))

            trend_reason = ""
            if is_monthly_surge and is_daily_hot:
                trend_reason = f"🚨 <b>שילוב נדיר:</b> גם קפיצה יומית ({data['daily_rvol']:.2f}x) וגם גל חודשי עולה (+{data['mom_vol_change_pct']}%)!"
            elif is_monthly_surge:
                trend_reason = f"🌊 <b>גל כניסת כספים חודשי:</b> הווליום בחודש האחרון עלה ב-<b>{data['mom_vol_change_pct']}%</b> (איסוף סחורה ממושך)."
            else:
                trend_reason = f"⚡ <b>התעוררות יומית:</b> מחזור גבוה ב-<b>{int((data['daily_rvol']-1)*100)}%+</b> מהממוצע."

            sec_msg = (
                f"🏢 <b>סקטור בפוקוס ווליום: {sec_name} ({sec_etf})</b>\n\n"
                f"{trend_reason}\n"
                f"• יחס יומי (RVol): <b>{data['daily_rvol']:.2f}x</b>\n"
                f"• עקביות: {data['days_above_avg']}/{data['total_days']} ימים מעל הממוצע החודש\n"
                f"• שער: ${data['price']} ({data['day_change_pct']:+.2f}%)\n\n"
                f"🔎 <i>סורק מניות מובילות בתוך הסקטור...</i>"
            )
            await context.bot.send_message(chat_id=USER_CHAT_ID, text=sec_msg, parse_mode="HTML")

            # סריקת מניות הסקטור
            stocks = SECTOR_STOCKS.get(sec_etf, [])
            stocks_data = []
            for sym in stocks:
                s_res = analyze_volume_trends(sym)
                if s_res:
                    stocks_data.append((sym, s_res))

            # סינון מניות עם ווליום חריג יומי או חודשי
            active_stocks = [
                item for item in stocks_data 
                if item[1]["daily_rvol"] >= 1.15 or item[1]["mom_vol_change_pct"] >= 30.0
            ]
            active_stocks.sort(key=lambda x: x[1]["daily_rvol"], reverse=True)

            if active_stocks:
                stk_msg = f"🎯 <b><u>מניות עם פעילות ווליום חריגה ב-{sec_name}:</u></b>\n\n"
                for sym, s in active_stocks:
                    badges = []
                    if s["daily_rvol"] >= 1.50:
                        badges.append("🚨 יומי כבד (+50%)")
                    elif s["daily_rvol"] >= 1.30:
                        badges.append("🔔 יומי עולה (+30%)")

                    if s["mom_vol_change_pct"] >= 30.0:
                        badges.append(f"🌊 גל חודשי (+{s['mom_vol_change_pct']}%)")

                    badge_txt = " | ".join(badges) if badges else "👀 מעקב ראשוני"

                    stk_msg += (
                        f"• <b>{sym}</b>: {badge_txt}\n"
                        f"  ↳ יומי: <b>{s['daily_rvol']:.2f}x</b> ({format_vol(s['curr_vol'])})\n"
                        f"  ↳ חודשי MoM: <b>{s['mom_vol_change_pct']:+.1f}%</b> ({s['days_above_avg']}/{s['total_days']} ימים חזקים)\n"
                        f"  ↳ שער: ${s['price']} ({s['day_change_pct']:+.2f}%)\n\n"
                    )
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=stk_msg, parse_mode="HTML")
            else:
                top_3 = sorted(stocks_data, key=lambda x: x[1]["daily_rvol"], reverse=True)[:3]
                fallback = f"ℹ️ הווליום ב-<b>{sec_name}</b> מרוכז בעיקר בתעודת הסל. 3 המניות המובילות כעת:\n"
                for sym, s in top_3:
                    fallback += f"• <b>{sym}</b>: RVol {s['daily_rvol']:.2f}x | MoM: {s['mom_vol_change_pct']:+.1f}%\n"
                await context.bot.send_message(chat_id=USER_CHAT_ID, text=fallback, parse_mode="HTML")

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
    app.add_handler(CommandHandler("monthly", monthly_trend_command))

    print("Volume Scanner Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
