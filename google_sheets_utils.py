import time
import random
import threading
import json
import os
from typing import List, Dict, Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account


def _default_scopes() -> List[str]:
    return ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _backoff_sleep(attempt: int, base: float = 1.0, max_sleep: float = 60.0) -> None:
    # Exponential backoff with jitter
    delay = min(max_sleep, base * (2 ** attempt))
    jitter = delay * (0.5 + random.random() * 0.5)
    time.sleep(jitter)


class GoogleSheetsClient:
    """Wrapper around Google Sheets API with retry/backoff and simple local caching.

    Uses a service account by default. Credentials can be provided via a file path
    (GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE) or via environment variable with JSON content
    in GOOGLE_SHEETS_CREDENTIALS_JSON. The client is kept simple intentionally to be
    easy to integrate from Streamlit apps.
    """

    def __init__(self, creds_path: str = None, scopes: List[str] = None, cache_ttl: int = 60, batch_size: int = 100):
        self._scopes = scopes or _default_scopes()
        self._cache_ttl = cache_ttl
        self._batch_size = batch_size
        self._cache: Dict[str, Any] = {}
        self._cache_expiry: Dict[str, float] = {}
        self._lock = threading.Lock()

        # Load credentials
        creds = None
        if creds_path and os.path.exists(creds_path):
            creds = service_account.Credentials.from_service_account_file(creds_path, scopes=self._scopes)
        elif os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON"):
            info = json.loads(os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"])
            creds = service_account.Credentials.from_service_account_info(info, scopes=self._scopes)
        else:
            # Fallback: try environment variable with a path to credentials
            path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE")
            if path and os.path.exists(path):
                creds = service_account.Credentials.from_service_account_file(path, scopes=self._scopes)
        if creds is None:
            raise RuntimeError("Google Sheets credentials not configured. Set GOOGLE_SHEETS_CREDENTIALS_JSON or GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE.")

        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _cache_key(self, spreadsheet_id: str, range_: str) -> str:
        return f"{spreadsheet_id}|{range_}"

    def _get_cached(self, key: str):
        if key in self._cache and self._cache_expiry.get(key, 0) > time.time():
            return self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache_expiry[key] = time.time() + self._cache_ttl

    def read_values(self, spreadsheet_id: str, ranges: List[str]) -> Dict[str, List[List[Any]]]:
        """Read values for given ranges from a spreadsheet.

        This method batches requests when possible and applies a simple exponential backoff
        on 429/5xx errors. Results are cached per-range for a TTL to minimize API usage.
        Returns a mapping from range string to list of rows (values).
        """
        if not ranges:
            return {}

        results: Dict[str, List[List[Any]]] = {}
        to_fetch: List[str] = []

        with self._lock:
            for r in ranges:
                key = self._cache_key(spreadsheet_id, r)
                cached = self._get_cached(key)
                if cached is not None:
                    results[r] = cached
                else:
                    to_fetch.append(r)

        if not to_fetch:
            return results

        max_retries = 6
        for attempt in range(max_retries):
            try:
                if len(to_fetch) == 1:
                    r = to_fetch[0]
                    resp = self._service.spreadsheets().values().get(
                        spreadsheetId=spreadsheet_id,
                        range=r,
                        majorDimension="ROWS",
                    ).execute()
                    values = resp.get("values", [])
                    key = self._cache_key(spreadsheet_id, r)
                    self._set_cache(key, values)
                    results[r] = values
                    break
                else:
                    resp = self._service.spreadsheets().values().batchGet(
                        spreadsheetId=spreadsheet_id,
                        ranges=to_fetch,
                        majorDimension="ROWS",
                    ).execute()
                    value_ranges = resp.get("valueRanges", [])
                    for entry in value_ranges:
                        range_ = entry.get("range")
                        vals = entry.get("values", [])
                        key = self._cache_key(spreadsheet_id, range_)
                        self._set_cache(key, vals)
                        results[range_] = vals
                    break
            except HttpError as e:
                code = getattr(e, 'status', None) or getattr(e, 'resp', {}).get('status')
                if code in {429, 500, 502, 503, 504}:
                    _backoff_sleep(attempt, base=1.0, max_sleep=60.0)
                    continue
                raise
            except Exception:
                # Non-HTTP errors: propagate
                raise

        return results
