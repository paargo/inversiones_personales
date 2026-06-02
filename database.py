import json
import time
import os
from typing import Any

import pandas as pd
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except ModuleNotFoundError:
    gspread = None
    ServiceAccountCredentials = None

import utils

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
DEFAULT_SHEET_NAME = "Investment Tracker Data"
SETTINGS_FILE = "settings.json"
CREDENTIALS_FILE = "credentials.json"

INVESTMENTS_COLUMNS = [
    "Date",
    "Ticker",
    "Platform",
    "Quantity",
    "Price",
    "Currency",
    "Commission",
    "Commission_Type",
    "Commission_Currency",
    "Total_Cost",
]
PLATFORMS_COLUMNS = [
    "Platform",
    "Entry Commission",
    "Entry Type",
    "Exit Commission",
    "Exit Type",
    "Commission Currency",
]
EARNINGS_COLUMNS = ["Date", "Ticker", "Platform", "Type", "Currency", "Amount", "Capital_Reduction"]
SETTINGS_COLUMNS = ["Ticker", "Data Source", "Type"]
DEFAULT_PLATFORM_ROWS = [
    ["Binance", 0.1, "Percentage", 0.1, "Percentage", "BTC"],
    ["Interactive Brokers", 1.0, "Amount", 1.0, "Amount", "USD"],
    ["Coinbase", 0.5, "Percentage", 0.5, "Percentage", "USD"],
]


class DatabaseError(Exception):
    """Base exception for Google Sheets and local settings operations."""


def _ensure_google_dependencies() -> None:
    if gspread is None or ServiceAccountCredentials is None:
        raise DatabaseError(
            "Faltan dependencias de Google Sheets. Instala 'gspread' y 'oauth2client' para usar la base remota."
        )


def _empty_dataframe(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _clean_json_dict(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    return {}


def _load_local_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            return _clean_json_dict(json.load(handle))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatabaseError(f"No se pudo leer {SETTINGS_FILE}: {exc}") from exc


def _save_local_settings(payload: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4, ensure_ascii=False)
    except OSError as exc:
        raise DatabaseError(f"No se pudo guardar {SETTINGS_FILE}: {exc}") from exc


def _get_file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def has_google_credentials() -> bool:
    return bool(utils.get_secret("gcp_service_account")) or os.path.exists(CREDENTIALS_FILE)


def _build_credentials():
    _ensure_google_dependencies()
    creds_dict = utils.get_secret("gcp_service_account")
    if creds_dict:
        return ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    if os.path.exists(CREDENTIALS_FILE):
        return ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
    raise DatabaseError("No se encontraron credenciales de Google Sheets.")


_SETTINGS_CACHE = None
_SETTINGS_CACHE_TIME = 0
_SETTINGS_CACHE_TTL = 60  # seconds for sheet object
_WORKSHEETS_CACHE = None
_WORKSHEETS_CACHE_TIME = 0
_WORKSHEETS_CACHE_TTL = 300
_SETTINGS_DATA_CACHE = None
_SETTINGS_DATA_CACHE_TIME = 0
_SETTINGS_FILE_MTIME = 0.0
_DATA_CACHE = {}
_DATA_CACHE_TIME = {}


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc) if exc is not None else ""
    return "429" in msg or "Too Many Requests" in msg or "quota" in msg.lower()


def _call_with_retries(func, *args, **kwargs):
    for attempt in range(5):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if attempt < 4 and _is_quota_error(exc):
                time.sleep(2 ** attempt)
                continue
            raise


def _cache_is_valid(cache_time: float, ttl: int) -> bool:
    return cache_time > 0 and (time.time() - cache_time) < ttl


def _get_cached_value(cache_key: str, ttl: int):
    cache_time = _DATA_CACHE_TIME.get(cache_key, 0)
    if _cache_is_valid(cache_time, ttl):
        return _DATA_CACHE.get(cache_key)
    return None


def _set_cached_value(cache_key: str, value) -> None:
    _DATA_CACHE[cache_key] = value
    _DATA_CACHE_TIME[cache_key] = time.time()


def _invalidate_cache(*cache_keys: str) -> None:
    global _WORKSHEETS_CACHE, _WORKSHEETS_CACHE_TIME, _SETTINGS_DATA_CACHE, _SETTINGS_DATA_CACHE_TIME
    for cache_key in cache_keys:
        _DATA_CACHE.pop(cache_key, None)
        _DATA_CACHE_TIME.pop(cache_key, None)
    if "worksheets" in cache_keys:
        _WORKSHEETS_CACHE = None
        _WORKSHEETS_CACHE_TIME = 0
    if "settings" in cache_keys:
        _SETTINGS_DATA_CACHE = None
        _SETTINGS_DATA_CACHE_TIME = 0

def get_db_connection():
    """Connect to Google Sheets using Streamlit secrets or a local credentials file.

    Added a small retry/backoff on transient rate-limit errors (HTTP 429) and a
    cache for settings to reduce the number of reads to Sheets.
    """
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TIME
    _ensure_google_dependencies()
    if _SETTINGS_CACHE is not None and _cache_is_valid(_SETTINGS_CACHE_TIME, _SETTINGS_CACHE_TTL):
        return _SETTINGS_CACHE  # type: ignore
    try:
        creds = _build_credentials()
        client = gspread.authorize(creds)
        sheet_name = utils.get_secret("sheet_name") or DEFAULT_SHEET_NAME
        sh = _call_with_retries(client.open, sheet_name)
        _SETTINGS_CACHE = sh
        _SETTINGS_CACHE_TIME = time.time()
        return sh
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError(f"Error de conexión a Google Sheets: {exc}") from exc


def init_worksheets(sh):
    """Ensure required worksheets exist and basic schema is upgraded."""
    global _WORKSHEETS_CACHE, _WORKSHEETS_CACHE_TIME
    if _WORKSHEETS_CACHE is not None and _cache_is_valid(_WORKSHEETS_CACHE_TIME, _WORKSHEETS_CACHE_TTL):
        return _WORKSHEETS_CACHE
    try:
        worksheet_map = {ws.title: ws for ws in _call_with_retries(sh.worksheets)}

        ws_inv = worksheet_map.get("Investments")
        if ws_inv is None:
            ws_inv = sh.add_worksheet(title="Investments", rows=1000, cols=20)
            ws_inv.append_row(INVESTMENTS_COLUMNS)
            worksheet_map["Investments"] = ws_inv

        ws_platforms = worksheet_map.get("Platforms")
        if ws_platforms is None:
            ws_platforms = sh.add_worksheet(title="Platforms", rows=100, cols=10)
            ws_platforms.append_row(PLATFORMS_COLUMNS)
            ws_platforms.append_rows(DEFAULT_PLATFORM_ROWS)
            worksheet_map["Platforms"] = ws_platforms

        ws_settings = worksheet_map.get("Settings")
        if ws_settings is not None:
            headers = _call_with_retries(ws_settings.row_values, 1)
            if "Type" not in headers:
                ws_settings.update_cell(1, 3, "Type")
        else:
            ws_settings = sh.add_worksheet(title="Settings", rows=100, cols=5)
            ws_settings.append_row(SETTINGS_COLUMNS)
            worksheet_map["Settings"] = ws_settings

        ws_earn = worksheet_map.get("Earnings")
        if ws_earn is not None:
            headers_earn = _call_with_retries(ws_earn.row_values, 1)
            if "Platform" not in headers_earn:
                ws_earn.insert_cols([["Platform"]], col=3)
        else:
            ws_earn = sh.add_worksheet(title="Earnings", rows=1000, cols=10)
            ws_earn.append_row(EARNINGS_COLUMNS)
            worksheet_map["Earnings"] = ws_earn

        _WORKSHEETS_CACHE = {
            "investments": ws_inv,
            "platforms": ws_platforms,
            "settings": ws_settings,
            "earnings": ws_earn,
        }
        _WORKSHEETS_CACHE_TIME = time.time()
        return _WORKSHEETS_CACHE
    except Exception as exc:
        raise DatabaseError(f"Error de inicialización de hojas: {exc}") from exc


def _read_records(worksheet, columns: list[str], *, value_render_option=None) -> pd.DataFrame:
    kwargs = {}
    if value_render_option is not None:
        kwargs["value_render_option"] = value_render_option
    records = _call_with_retries(worksheet.get_all_records, **kwargs)
    if not records:
        return _empty_dataframe(columns)

    df = pd.DataFrame(records)
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df[columns]


def load_data() -> pd.DataFrame:
    cached = _get_cached_value("investments", ttl=30)
    if cached is not None:
        return cached.copy()
    worksheets = init_worksheets(get_db_connection())
    df = _read_records(
        worksheets["investments"],
        INVESTMENTS_COLUMNS,
        value_render_option="UNFORMATTED_VALUE",
    )
    for col in ["Quantity", "Price", "Commission", "Total_Cost"]:
        df[col] = df[col].apply(utils.safe_float)
    _set_cached_value("investments", df.copy())
    return df


def save_data(df: pd.DataFrame) -> None:
    worksheets = init_worksheets(get_db_connection())
    ws_inv = worksheets["investments"]
    df_tosave = df.copy()
    if "Date" in df_tosave.columns:
        df_tosave["Date"] = df_tosave["Date"].astype(str)
    df_tosave = df_tosave.fillna("")

    ws_inv.clear()
    ws_inv.append_row(df_tosave.columns.tolist())
    if not df_tosave.empty:
        ws_inv.append_rows(df_tosave.values.tolist())
    _invalidate_cache("investments")


def load_settings() -> dict:
    global _SETTINGS_DATA_CACHE, _SETTINGS_DATA_CACHE_TIME, _SETTINGS_FILE_MTIME
    current_settings_mtime = _get_file_mtime(SETTINGS_FILE)
    # Fast-path: return cached settings if recently loaded
    if (
        _SETTINGS_DATA_CACHE is not None
        and (time.time() - _SETTINGS_DATA_CACHE_TIME) < _SETTINGS_CACHE_TTL
        and current_settings_mtime == _SETTINGS_FILE_MTIME
    ):
        return _SETTINGS_DATA_CACHE
    settings = {"api_keys": {}, "ticker_config": {}}

    api_keys = utils.get_secret("api_keys")
    if api_keys:
        settings["api_keys"] = api_keys

    worksheets = init_worksheets(get_db_connection())
    records = _get_cached_value("settings_records", ttl=30)
    if records is None:
        records = _call_with_retries(worksheets["settings"].get_all_records)
        _set_cached_value("settings_records", records)

    config = {}
    for row in records:
        ticker = row.get("Ticker")
        if ticker:
            config[ticker] = {
                "source": row.get("Data Source", "Manual"),
                "type": row.get("Type", "Acción ARG"),
            }
    settings["ticker_config"] = config

    local_settings = _load_local_settings()
    for key in (
        "fred_api_key",
        "auto_update_enabled",
        "ohlc_auto_update_enabled",
        "ohlc_last_update",
        "ohlc_last_status",
        "manual_price_overrides",
        "split_events",
    ):
        if key in local_settings:
            settings[key] = local_settings[key]

    # Persist cache
    _SETTINGS_DATA_CACHE = settings
    _SETTINGS_DATA_CACHE_TIME = time.time()
    _SETTINGS_FILE_MTIME = current_settings_mtime
    return settings


def save_settings(settings: dict) -> None:
    global _SETTINGS_FILE_MTIME
    worksheets = init_worksheets(get_db_connection())
    ws_settings = worksheets["settings"]

    config_data = []
    for ticker, info in settings.get("ticker_config", {}).items():
        if isinstance(info, dict):
            config_data.append(
                {
                    "Ticker": ticker,
                    "Data Source": info.get("source", "Manual"),
                    "Type": info.get("type", "Acción ARG"),
                }
            )
        else:
            config_data.append({"Ticker": ticker, "Data Source": info, "Type": "Acción ARG"})

    df_config = pd.DataFrame(config_data)
    ws_settings.clear()
    ws_settings.append_row(SETTINGS_COLUMNS)
    if not df_config.empty:
        ws_settings.append_rows(df_config.values.tolist())

    local_settings = {}
    try:
        local_settings = _load_local_settings()
    except DatabaseError:
        local_settings = {}

    for key in (
        "fred_api_key",
        "auto_update_enabled",
        "ohlc_auto_update_enabled",
        "ohlc_last_update",
        "ohlc_last_status",
        "manual_price_overrides",
        "split_events",
    ):
        if key in settings:
            local_settings[key] = settings[key]

    _save_local_settings(local_settings)
    _SETTINGS_FILE_MTIME = _get_file_mtime(SETTINGS_FILE)
    _invalidate_cache("settings", "settings_records")


def load_platforms() -> pd.DataFrame:
    cached = _get_cached_value("platforms", ttl=30)
    if cached is not None:
        return cached.copy()
    worksheets = init_worksheets(get_db_connection())
    try:
        ws = worksheets["platforms"]
    except KeyError as exc:
        raise DatabaseError("No se encontró la hoja Platforms.") from exc

    df = _read_records(ws, PLATFORMS_COLUMNS)
    for col in ["Entry Commission", "Exit Commission"]:
        df[col] = df[col].apply(utils.safe_float)
    _set_cached_value("platforms", df.copy())
    return df


def save_platforms(df: pd.DataFrame) -> None:
    worksheets = init_worksheets(get_db_connection())
    ws = worksheets["platforms"]
    ws.clear()
    ws.append_row(df.columns.tolist())
    if not df.empty:
        ws.append_rows(df.values.tolist())
    _invalidate_cache("platforms")


def load_earnings() -> pd.DataFrame:
    cached = _get_cached_value("earnings", ttl=30)
    if cached is not None:
        return cached.copy()
    worksheets = init_worksheets(get_db_connection())
    df = _read_records(
        worksheets["earnings"],
        EARNINGS_COLUMNS,
        value_render_option="UNFORMATTED_VALUE",
    )
    for col in ["Amount", "Capital_Reduction"]:
        df[col] = df[col].apply(utils.safe_float)
    _set_cached_value("earnings", df.copy())
    return df


def save_earnings(df: pd.DataFrame) -> None:
    worksheets = init_worksheets(get_db_connection())
    ws = worksheets["earnings"]

    df_tosave = df.copy()
    if "Date" in df_tosave.columns:
        df_tosave["Date"] = df_tosave["Date"].astype(str)
    df_tosave = df_tosave.fillna("")

    ws.clear()
    ws.append_row(df_tosave.columns.tolist())
    if not df_tosave.empty:
        ws.append_rows(df_tosave.values.tolist())
    _invalidate_cache("earnings")
