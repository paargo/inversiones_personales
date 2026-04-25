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

CREATE TABLE IF NOT EXISTS semaphore_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id INTEGER NOT NULL UNIQUE,
    enable_price_vs_ema10 INTEGER NOT NULL DEFAULT 1,
    enable_price_vs_ema20 INTEGER NOT NULL DEFAULT 1,
    enable_price_vs_ema100 INTEGER NOT NULL DEFAULT 1,
    enable_ema10_vs_ema20 INTEGER NOT NULL DEFAULT 1,
    enable_price_vs_high INTEGER NOT NULL DEFAULT 1,
    last_calculated_at TEXT,
    last_result_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (enable_price_vs_ema10 IN (0, 1)),
    CHECK (enable_price_vs_ema20 IN (0, 1)),
    CHECK (enable_price_vs_ema100 IN (0, 1)),
    CHECK (enable_ema10_vs_ema20 IN (0, 1)),
    CHECK (enable_price_vs_high IN (0, 1)),
    FOREIGN KEY (ticker_id) REFERENCES analyzed_tickers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS market_ohlc_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'mock',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker_id, timestamp),
    FOREIGN KEY (ticker_id) REFERENCES analyzed_tickers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS semaphore_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id INTEGER NOT NULL,
    calculated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticker_id) REFERENCES analyzed_tickers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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

INSERT INTO semaphore_configs (
    ticker_id,
    enable_price_vs_ema10,
    enable_price_vs_ema20,
    enable_price_vs_ema100,
    enable_ema10_vs_ema20,
    enable_price_vs_high
)
VALUES (
    1,
    1,
    1,
    1,
    1,
    1
);

INSERT INTO market_ohlc_history (
    ticker_id, timestamp, open, high, low, close, volume, source
)
VALUES (
    1,
    '2026-04-21T00:00:00Z',
    180.50,
    185.20,
    179.80,
    184.10,
    52345000,
    'mock'
);

INSERT INTO semaphore_snapshots (
    ticker_id, calculated_at, payload_json
)
VALUES (
    1,
    '2026-04-22T00:00:00Z',
    '{"ticker":"AAPL","market":"NYSE","timeframe":"1D","calculated_at":"2026-04-22T00:00:00Z","indicators":{"price_vs_ema10":{"state":"green"},"price_vs_ema20":{"state":"green"},"price_vs_ema100":{"state":"green"},"ema10_vs_ema20":{"state":"green"},"price_vs_high":{"state":"green"}}}'
);
