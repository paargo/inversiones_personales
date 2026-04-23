"""Standalone daily OHLC synchronization job."""

from __future__ import annotations

import datetime

import database as db
from market_history_service import HistoricalMarketDataService, YFinanceMarketDataProvider, SqliteMarketHistoryRepository


def main() -> int:
    settings = db.load_settings()
    if not settings.get("ohlc_auto_update_enabled", False):
        print("OHLC auto update is disabled.")
        return 0

    repository = SqliteMarketHistoryRepository("market_history.sqlite")
    provider = YFinanceMarketDataProvider()
    service = HistoricalMarketDataService(provider=provider, repository=repository)
    result = service.sync_all_missing(end_date=datetime.date.today())
    settings["ohlc_last_update"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    settings["ohlc_last_status"] = (
        f"updated_tickers={result['updated_tickers']}; saved_bars={result['saved_bars']}; failed_tickers={result['failed_tickers']}"
    )
    db.save_settings(settings)
    print(f"Done: {result['updated_tickers']} tickers, {result['saved_bars']} bars.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
