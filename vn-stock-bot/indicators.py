import logging
import pandas as pd

from config import (
    EMA_SHORT, EMA_LONG, RSI_PERIOD, ATR_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, VOLUME_MA_PERIOD,
)

logger = logging.getLogger(__name__)

MIN_ROWS = 50

def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()

def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()

def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def _bollinger_bands(close: pd.Series, length: int = 20, std_dev: int = 2):
    mid = _sma(close, length)
    std = close.rolling(window=length).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) < MIN_ROWS:
        logger.warning("Not enough data to compute indicators (need >= %d rows)", MIN_ROWS)
        return df

    df = df.copy()

    df["ema_short"] = _ema(df["close"], EMA_SHORT)
    df["ema_long"] = _ema(df["close"], EMA_LONG)
    df["sma_50"] = _sma(df["close"], 50)
    df["sma_200"] = _sma(df["close"], 200)

    df["rsi"] = _rsi(df["close"], RSI_PERIOD)

    macd_line, signal_line, histogram = _macd(
        df["close"], MACD_FAST, MACD_SLOW, MACD_SIGNAL
    )
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = histogram

    df["atr"] = _atr(df["high"], df["low"], df["close"], ATR_PERIOD)

    bb_upper, bb_mid, bb_lower = _bollinger_bands(df["close"], BB_PERIOD, BB_STD)
    df["bb_upper"] = bb_upper
    df["bb_middle"] = bb_mid
    df["bb_lower"] = bb_lower

    df["volume_ma"] = _sma(df["volume"], VOLUME_MA_PERIOD)

    return df

def compute_indicators_batch(data: dict) -> dict:
    result = {}
    for symbol, df in data.items():
        result[symbol] = compute_indicators(df)
    return result
