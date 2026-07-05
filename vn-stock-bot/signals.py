import logging
import pandas as pd
from typing import List, Dict
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    ATR_STOP_LOSS_FACTOR, MIN_RR_RATIO,
    VOLUME_SPIKE_RATIO, EMA_SHORT, EMA_LONG,
)

logger = logging.getLogger(__name__)

def _ema_cross_up(row: pd.Series) -> bool:
    return (
        not pd.isna(row.get("ema_short"))
        and not pd.isna(row.get("ema_long"))
        and row["ema_short"] > row["ema_long"]
    )

def _volume_spike(row: pd.Series) -> bool:
    vol_ma = row.get("volume_ma")
    return not pd.isna(vol_ma) and vol_ma > 0 and row["volume"] > vol_ma * VOLUME_SPIKE_RATIO

def _is_uptrend(row: pd.Series) -> bool:
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    return not pd.isna(sma50) and not pd.isna(sma200) and row["close"] > sma50 and row["close"] > sma200

def _is_downtrend(row: pd.Series) -> bool:
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    return not pd.isna(sma50) and not pd.isna(sma200) and row["close"] < sma50 and row["close"] < sma200

def _macd_bearish(df: pd.DataFrame) -> bool:
    if "macd_hist" not in df.columns:
        return False
    recent = df.tail(5)
    return (recent["macd_hist"] < 0).all()

def detect_entry(df: pd.DataFrame, symbol: str) -> List[Dict]:
    signals = []
    if len(df) < 3:
        return signals

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    prev_ema_cross = (
        not pd.isna(prev.get("ema_short"))
        and not pd.isna(prev.get("ema_long"))
        and prev["ema_short"] <= prev["ema_long"]
    )
    curr_ema_cross = _ema_cross_up(curr)

    if prev_ema_cross and curr_ema_cross and _volume_spike(curr):
        atr = curr.get("atr", 0)
        stop_loss = curr["close"] - atr * ATR_STOP_LOSS_FACTOR
        risk = curr["close"] - stop_loss
        take_profit = curr["close"] + risk * MIN_RR_RATIO
        signals.append({
            "symbol": symbol,
            "type": "entry",
            "price": round(curr["close"], 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "reason": "EMA20 cắt lên EMA50 + volume tăng",
        })

    if (
        prev.get("rsi", 100) < RSI_OVERSOLD
        and curr.get("rsi", 100) >= RSI_OVERSOLD
        and _volume_spike(curr)
    ):
        atr = curr.get("atr", 0)
        stop_loss = curr["close"] - atr * ATR_STOP_LOSS_FACTOR
        risk = curr["close"] - stop_loss
        take_profit = curr["close"] + risk * MIN_RR_RATIO
        signals.append({
            "symbol": symbol,
            "type": "entry",
            "price": round(curr["close"], 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "reason": "RSI hồi từ oversold + volume tăng",
        })

    return signals

def detect_stop_loss(df: pd.DataFrame, symbol: str) -> List[Dict]:
    signals = []
    if len(df) < 2:
        return signals

    curr = df.iloc[-1]
    atr = curr.get("atr")
    if pd.isna(atr) or atr == 0:
        return signals

    stop_price = curr["close"] - atr * ATR_STOP_LOSS_FACTOR
    signals.append({
        "symbol": symbol,
        "type": "stop_loss",
        "price": round(curr["close"], 2),
        "stop_loss": round(stop_price, 2),
        "reason": f"Stop-loss động: ATR x {ATR_STOP_LOSS_FACTOR}",
    })
    return signals

def detect_take_profit(df: pd.DataFrame, symbol: str) -> List[Dict]:
    signals = []
    if len(df) < 2:
        return signals

    curr = df.iloc[-1]
    if _ema_cross_up(curr) and curr["close"] > df.iloc[-3]["close"] * 1.05:
        signals.append({
            "symbol": symbol,
            "type": "take_profit",
            "price": round(curr["close"], 2),
            "reason": "Giá đã chạy có lời, trail theo EMA20",
        })
    return signals

def detect_potential(df: pd.DataFrame, symbol: str) -> List[Dict]:
    signals = []
    if df.empty:
        return signals

    curr = df.iloc[-1]
    score = 0
    reasons = []

    if _is_uptrend(curr):
        score += 1
        reasons.append("Giá > MA50 & MA200")

    rsi = curr.get("rsi", 50)
    if not pd.isna(rsi) and rsi < 40:
        score += 1
        reasons.append(f"RSI thấp ({rsi:.1f})")

    if _volume_spike(curr):
        score += 1
        reasons.append("Volume đột biến")

    if score >= 2:
        signals.append({
            "symbol": symbol,
            "type": "potential",
            "price": round(curr["close"], 2),
            "rsi": round(rsi, 1) if not pd.isna(rsi) else "N/A",
            "reason": " + ".join(reasons),
        })
    return signals

def detect_downtrend(df: pd.DataFrame, symbol: str) -> List[Dict]:
    signals = []
    if df.empty:
        return signals

    curr = df.iloc[-1]
    reasons = []

    if _is_downtrend(curr):
        reasons.append("Giá < MA50 & MA200")

    if _macd_bearish(df):
        reasons.append("MACD âm 5 phiên liên tiếp")

    rsi = curr.get("rsi", 50)
    if not pd.isna(rsi) and rsi < 40 and _volume_spike(curr):
        reasons.append(f"RSI < 40 ({rsi:.1f}) + volume bán tăng")

    if reasons:
        signals.append({
            "symbol": symbol,
            "type": "downtrend",
            "price": round(curr["close"], 2),
            "rsi": round(rsi, 1) if not pd.isna(rsi) else "N/A",
            "reason": " + ".join(reasons),
        })
    return signals

def scan_all(data: dict) -> List[Dict]:
    all_signals = []
    for symbol, df in data.items():
        all_signals.extend(detect_entry(df, symbol))
        all_signals.extend(detect_take_profit(df, symbol))
        all_signals.extend(detect_potential(df, symbol))
        all_signals.extend(detect_downtrend(df, symbol))
    return all_signals
