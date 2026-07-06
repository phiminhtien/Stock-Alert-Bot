"""Lấy dữ liệu giá chứng khoán từ vnstock API (VCI source)."""

import logging
from typing import List, Optional
import pandas as pd

from config import WATCHLIST

logger = logging.getLogger(__name__)


class DataFetcher:
    """Lớp trung gian lấy dữ liệu giá từ vnstock, hỗ trợ cache trong memory."""

    def __init__(self, source: str = "VCI"):
        """Khởi tạo DataFetcher.

        Args:
            source: Nguồn dữ liệu vnstock (mặc định "VCI").
        """
        self._source = source
        self._cache = {}

    def _get_quote(self, symbol: str):
        """Tạo đối tượng Quote cho một mã chứng khoán.

        Args:
            symbol: Mã chứng khoán (VD: "FPT", "VCB").

        Returns:
            Đối tượng Quote từ vnstock.
        """
        from vnstock.api.quote import Quote
        return Quote(symbol=symbol, source=self._source)

    def fetch_historical(
        self, symbol: str, start: str = "2024-01-01", end: str | None = None
    ) -> pd.DataFrame:
        """Lấy dữ liệu giá lịch sử (OHLCV) cho một mã.

        Args:
            symbol: Mã chứng khoán.
            start: Ngày bắt đầu (YYYY-MM-DD).
            end: Ngày kết thúc (YYYY-MM-DD), mặc định hôm nay.

        Returns:
            DataFrame chứa các cột: time, open, high, low, close, volume.
            Trả về DataFrame rỗng nếu có lỗi.
        """
        cache_key = f"hist_{symbol}_{start}_{end}"

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

            return df
        except Exception as e:
            logger.warning("Failed to fetch historical data for %s: %s", symbol, e)
            return pd.DataFrame()

    def fetch_multiple_historical(
        self, symbols: Optional[List[str]] = None, start: str = "2024-01-01"
    ) -> dict:
        """Lấy dữ liệu lịch sử cho nhiều mã cùng lúc.

        Args:
            symbols: Danh sách mã cần lấy. Mặc định dùng WATCHLIST từ config.
            start: Ngày bắt đầu.

        Returns:
            Dict {symbol: DataFrame} chứa dữ liệu của các mã lấy thành công.
        """
        if symbols is None:
            symbols = WATCHLIST
        result = {}
        for symbol in symbols:
            df = self.fetch_historical(symbol, start=start)
            if not df.empty:
                result[symbol] = df
        return result

    def fetch_realtime_price(self, symbol: str) -> Optional[float]:
        """Lấy giá real-time (intraday) hiện tại của một mã.

        Args:
            symbol: Mã chứng khoán.

        Returns:
            Giá hiện tại (float), hoặc None nếu không lấy được.
        """
        try:
            q = self._get_quote(symbol)
            df = q.intraday(symbol=symbol, page_size=1)
            if df is not None and not df.empty:
                return float(df.iloc[-1]["price"])
        except Exception as e:
            logger.warning("Failed to fetch realtime price for %s: %s", symbol, e)
        return None

    def clear_cache(self):
        """Xóa toàn bộ cache dữ liệu trong memory."""
        self._cache.clear()
