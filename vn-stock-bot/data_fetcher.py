import logging
from typing import List, Optional
import pandas as pd

from config import WATCHLIST

logger = logging.getLogger(__name__)

class DataFetcher:
    def __init__(self, source: str = "VCI"):
        self._source = source
        self._cache = {}

    def _get_quote(self, symbol: str):
        from vnstock.api.quote import Quote
        return Quote(symbol=symbol, source=self._source)

    def fetch_historical(
        self, symbol: str, start: str = "2024-01-01", end: str | None = None
    ) -> pd.DataFrame:
        cache_key = f"hist_{symbol}_{start}_{end}"
        # if cache_key in self._cache:
        #     return self._cache[cache_key]

        try:
            if end is None:
                end = pd.Timestamp.now().strftime("%Y-%m-%d")

            q = self._get_quote(symbol)
            df = q.history(start=start, end=end)

            if df is None or df.empty:
                logger.warning("No data for %s", symbol)
                return pd.DataFrame()

            col_map = {c.lower(): c for c in df.columns}
            if not {"open", "high", "low", "close", "volume"}.issubset(col_map):
                logger.warning("Missing OHLCV columns for %s, got: %s", symbol, list(col_map))
                return pd.DataFrame()

            df = df.rename(columns=col_map)
            df = df.sort_values("time").reset_index(drop=True)

            # self._cache[cache_key] = df
            return df
        except Exception as e:
            logger.warning("Failed to fetch historical data for %s: %s", symbol, e)
            return pd.DataFrame()

    def fetch_multiple_historical(
        self, symbols: Optional[List[str]] = None, start: str = "2024-01-01"
    ) -> dict:
        if symbols is None:
            symbols = WATCHLIST
        result = {}
        for symbol in symbols:
            df = self.fetch_historical(symbol, start=start)
            if not df.empty:
                result[symbol] = df
        return result

    def fetch_realtime_price(self, symbol: str) -> Optional[float]:
        try:
            q = self._get_quote(symbol)
            df = q.intraday(symbol=symbol, page_size=1)
            if df is not None and not df.empty:
                return float(df.iloc[-1]["price"])
        except Exception as e:
            logger.warning("Failed to fetch realtime price for %s: %s", symbol, e)
        return None

    def clear_cache(self):
        self._cache.clear()
