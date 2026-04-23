-- Schema for investment analysis entities
-- Compatible with SQLite and easy to adapt to PostgreSQL/MySQL.

CREATE TABLE IF NOT EXISTS analyzed_tickers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, market, timeframe),
    CHECK (asset_type IN ('stock', 'cedear', 'bond', 'etf', 'on')),
    CHECK (timeframe IN ('1D', '1W', '1M')),
    CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS indicator_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id INTEGER NOT NULL UNIQUE,
    ema_periods TEXT NOT NULL,
    enable_rsi INTEGER NOT NULL DEFAULT 1,
    enable_macd INTEGER NOT NULL DEFAULT 1,
    CHECK (enable_rsi IN (0, 1)),
    CHECK (enable_macd IN (0, 1)),
    FOREIGN KEY (ticker_id) REFERENCES analyzed_tickers(id) ON DELETE CASCADE
);

-- Example insertion
INSERT INTO analyzed_tickers (symbol, market, asset_type, timeframe, is_active)
VALUES ('AAPL', 'NYSE', 'stock', '1D', 1);

INSERT INTO indicator_configs (ticker_id, ema_periods, enable_rsi, enable_macd)
VALUES (
    1,
    '[10, 20, 100]',
    1,
    1
);
