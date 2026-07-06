"""Entry point & scheduler cho bot chứng khoán.

Dùng AsyncIOScheduler (APScheduler) với 4 job:
- pre_market (8:30)
- scan_session (9:00-14:45, mỗi 15 phút)
- pre_close (14:30)
- post_market (15:15)
"""

import asyncio
import logging
import pandas as pd
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import WATCHLIST, TIMEZONE, NOTIFY_INTERVAL_MINUTES
from data_fetcher import DataFetcher
from indicators import compute_indicators_batch
from signals import scan_all, detect_potential, detect_downtrend
from telegram_notify import (
    send_message,
    format_pre_market_report,
    format_post_market_report,
    format_stock_analysis,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

fetcher = DataFetcher()


async def scan_pre_market():
    """Job 8:30 AM: quét watchlist, gửi báo cáo tiềm năng + downtrend."""
    logger.info("=== Pre-market scan started ===")
    data = fetcher.fetch_multiple_historical()
    if not data:
        logger.warning("No data fetched")
        return
    data = compute_indicators_batch(data)

    potential_signals = []
    downtrend_signals = []
    for symbol, df in data.items():
        potential_signals.extend(detect_potential(df, symbol))
        downtrend_signals.extend(detect_downtrend(df, symbol))

    msg = format_pre_market_report(potential_signals, downtrend_signals)
    await send_message(msg)
    logger.info("=== Pre-market scan done ===")


async def scan_session():
    """Job giữa phiên: phân tích top 5 mã biến động + gửi tín hiệu mới."""
    logger.info("=== Session scan started ===")
    data = fetcher.fetch_multiple_historical()
    if not data:
        return
    data = compute_indicators_batch(data)
    signals = scan_all(data)

    sorted_items = []
    for symbol, df in data.items():
        if df.empty or len(df) < 2:
            continue
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        change_pct = ((curr["close"] - prev["close"]) / prev["close"]) * 100
        sorted_items.append((symbol, df, change_pct))

    sorted_items.sort(key=lambda x: abs(x[2]), reverse=True)

    for symbol, df, _ in sorted_items[:5]:
        msg = format_stock_analysis(symbol, df)
        await send_message(msg)
        await asyncio.sleep(0.5)

    for sig in signals:
        t = sig.get("type", "?")
        icon = {"entry": "🟢", "stop_loss": "🔴", "take_profit": "💰", "potential": "📈", "downtrend": "📉"}.get(t, "•")
        lines = [f"{icon} *{sig.get('symbol','?')}* — {t}: {sig.get('price','?')}"]
        if sig.get("reason"):
            lines.append(f"    └ {sig.get('reason')}")
        await send_message("\n".join(lines))
        await asyncio.sleep(0.3)

    logger.info("=== Session scan done ===")


async def scan_pre_close():
    """Job 14:30: cảnh báo mã có biến động giá > 3% trước giờ ATC."""
    logger.info("=== Pre-close scan started ===")
    warning_signals = []
    data = fetcher.fetch_multiple_historical()
    if not data:
        return
    data = compute_indicators_batch(data)

    for symbol, df in data.items():
        if df.empty or len(df) < 2:
            continue
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        change_pct = ((curr["close"] - prev["close"]) / prev["close"]) * 100
        if abs(change_pct) > 3:
            warning_signals.append(f"• {symbol}: {change_pct:+.2f}%")

    if warning_signals:
        msg = "*[TRƯỚC ATC]* Cảnh báo biến động bất thường:\n" + "\n".join(warning_signals)
        await send_message(msg)
    else:
        await send_message("*[TRƯỚC ATC]* Không có biến động bất thường.")
    logger.info("=== Pre-close scan done ===")


async def scan_post_market():
    """Job 15:15: tổng kết phiên — top biến động + xu hướng + volume."""
    logger.info("=== Post-market scan started ===")
    data = fetcher.fetch_multiple_historical()
    if not data:
        return
    data = compute_indicators_batch(data)

    summary = []
    for symbol, df in data.items():
        if df.empty or len(df) < 2:
            continue
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        change_pct = ((curr["close"] - prev["close"]) / prev["close"]) * 100
        sma50 = curr.get("sma_50")
        sma200 = curr.get("sma_200")
        vol = curr.get("volume", 0)
        vol_ma = curr.get("volume_ma", 0)
        vol_ratio = ""
        if vol_ma and vol_ma > 0:
            r = vol / vol_ma
            vol_ratio = f"x{r:.1f}"
        trend = ""
        if not pd.isna(sma50) and not pd.isna(sma200):
            if curr["close"] > sma50 and curr["close"] > sma200:
                trend = "lên"
            elif curr["close"] < sma50 and curr["close"] < sma200:
                trend = "xuống"
        summary.append({"symbol": symbol, "change": round(change_pct, 2), "vol_ratio": vol_ratio, "trend": trend})

    summary.sort(key=lambda x: abs(x["change"]), reverse=True)
    msg = format_post_market_report(summary[:20])
    await send_message(msg)
    logger.info("=== Post-market scan done ===")


async def _run_forever():
    """Khởi tạo scheduler, đăng ký 4 job, chạy và giữ event loop."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    scheduler.add_job(
        scan_pre_market,
        CronTrigger(hour=8, minute=30, timezone=TIMEZONE),
        id="pre_market",
    )

    scheduler.add_job(
        scan_session,
        CronTrigger(
            hour="9-14",
            minute=f"*/{NOTIFY_INTERVAL_MINUTES}",
            timezone=TIMEZONE,
            day_of_week="mon-fri"
        ),
        id="scan_session",
    )

    scheduler.add_job(
        scan_pre_close,
        CronTrigger(hour=14, minute=30, timezone=TIMEZONE),
        id="pre_close",
    )

    scheduler.add_job(
        scan_post_market,
        CronTrigger(hour=15, minute=15, timezone=TIMEZONE),
        id="post_market",
    )

    now_vn = pd.Timestamp.now(tz=TIMEZONE)
    logger.info(f"Bot Trader khởi động - Giờ VN: {now_vn.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Theo dõi: {', '.join(WATCHLIST)}")
    logger.info(f"Quét mỗi {NOTIFY_INTERVAL_MINUTES} phút trong giờ giao dịch")

    scheduler.start()
    logger.info("Bot started. Press Ctrl+C to exit.")

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()
        logger.info("Bot stopped.")


def main():
    """Hàm entry point chính. Gọi asyncio.run() để chạy scheduler."""
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
