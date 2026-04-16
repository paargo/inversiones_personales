import requests
import yfinance as yf
import pandas as pd
import streamlit as st
import datetime
import json
import os

MARKET_CACHE_FILE = "market_cache.json"

def is_market_hours():
    """Check if current time is Mon-Fri, 9:00 - 18:00 Argentina time (UTC-3)"""
    # Metadata confirms current time is already Argentina time (-03:00)
    now = datetime.datetime.now()
    # weekday() is 0 for Monday, 6 for Sunday
    is_weekday = 0 <= now.weekday() <= 4
    is_working_hour = 9 <= now.hour < 18
    return is_weekday and is_working_hour

def save_market_cache(data):
    try:
        with open(MARKET_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except:
        pass

def load_market_cache():
    if os.path.exists(MARKET_CACHE_FILE):
        try:
            with open(MARKET_CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            return None
    return None

@st.cache_data(ttl=1800) # Cache for 30 minutes
def get_dolar_rates():
    """Fetch MEP, CCL and Cripto rates from dolarapi.com + Variation proxy"""
    
    # Check if we should update
    in_hours = is_market_hours()
    cached_data = load_market_cache()
    
    # If not in hours and we have cached data, return it to save performance/limit API calls
    if not in_hours and cached_data:
        return cached_data

    rates = {"MEP": 0.0, "CCL": 0.0, "Cripto": 0.0, "Blue": 0.0, "variation": 0.0}
    try:
        # Fetch MEP
        resp_mep = requests.get("https://dolarapi.com/v1/dolares/bolsa", timeout=5)
        if resp_mep.status_code == 200:
            rates["MEP"] = resp_mep.json().get("venta", 0.0)
            
        # Fetch CCL
        resp_ccl = requests.get("https://dolarapi.com/v1/dolares/contadoconliqui", timeout=5)
        if resp_ccl.status_code == 200:
            rates["CCL"] = resp_ccl.json().get("venta", 0.0)
            
        # Fetch Cripto
        resp_crypto = requests.get("https://dolarapi.com/v1/dolares/cripto", timeout=5)
        if resp_crypto.status_code == 200:
            rates["Cripto"] = resp_crypto.json().get("venta", 0.0)

        # Fetch Blue
        resp_blue = requests.get("https://dolarapi.com/v1/dolares/blue", timeout=5)
        if resp_blue.status_code == 200:
            rates["Blue"] = resp_blue.json().get("venta", 0.0)

        # Proxy for dollar variation (ARS=X which is USD/ARS exchange rate)
        try:
            stock = yf.Ticker("ARS=X")
            hist = stock.history(period="2d")
            if len(hist) >= 2:
                prev = hist["Close"].iloc[-2]
                curr = hist["Close"].iloc[-1]
                rates["variation"] = (curr / prev - 1)
            elif not hist.empty:
                rates["variation"] = 0.0
        except:
            pass
            
        # Save successful fetch to local cache for off-hours
        if rates["MEP"] > 0:
            save_market_cache(rates)
            
    except Exception as e:
        print(f"Error fetching FX rates: {e}")
        # If error but we have cache, use it
        if cached_data:
            return cached_data
            
    return rates

def get_market_price(ticker, source):
    """
    Fetch current price and previous close from specified source.
    Returns: (price, currency, prev_close)
    """
    price = 0.0
    prev_close = 0.0
    currency = "USD" # Default
    
    try:
        if source == "Binance API":
            symbol = f"{ticker}USDT"
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            try:
                response = requests.get(url, headers=headers, timeout=5)
                response.raise_for_status()
                data = response.json()
                if "price" in data:
                    price = float(data["price"])
                    
                # For prev_close, we fallback to Yahoo since Binance ticker 24h is another call
                yf_symbol = f"{ticker}-USD"
                stock = yf.Ticker(yf_symbol)
                hist = stock.history(period="2d")
                if len(hist) >= 2:
                    prev_close = hist["Close"].iloc[-2]
                elif not hist.empty:
                    prev_close = hist["Close"].iloc[0]
                    
            except Exception as e:
                print(f"Binance API error for {ticker}: {e}. Falling back to Yahoo Finance.")
                try:
                    yf_symbol = f"{ticker}-USD"
                    stock = yf.Ticker(yf_symbol)
                    hist = stock.history(period="2d")
                    if not hist.empty:
                        price = hist["Close"].iloc[-1]
                        if len(hist) >= 2:
                            prev_close = hist["Close"].iloc[-2]
                        else:
                            prev_close = price
                        currency = "USD"
                except Exception as yf_e:
                    print(f"Yahoo Finance fallback error for {ticker}: {yf_e}")

        elif source == "Argentina (BYMA)":
            symbol = ticker if ticker.endswith(".BA") else f"{ticker}.BA"
            try:
                stock = yf.Ticker(symbol)
                hist = stock.history(period="2d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
                    if len(hist) >= 2:
                        prev_close = hist["Close"].iloc[-2]
                    else:
                        prev_close = price
                    
                    try:
                        curr = stock.fast_info.currency
                        if curr:
                            currency = curr
                        else:
                            currency = "ARS" 
                    except:
                        currency = "ARS"
            except Exception as e:
                print(f"YFinance error for {symbol}: {e}")
                
    except Exception as e:
        print(f"Error fetching {ticker} from {source}: {e}")
        
    return price, currency, prev_close

@st.cache_data(ttl=3600) # Cache for 1 hour
def get_historical_prices(tickers_with_sources, start_date):
    """
    Fetch historical prices for a list of tickers from yfinance.
    """
    all_data = pd.DataFrame()
    
    for ticker, source in tickers_with_sources.items():
        try:
            if source == "Binance API" or source == "Manual" or source == "Stock API":
                yf_ticker = f"{ticker}-USD"
            elif source == "Argentina (BYMA)":
                yf_ticker = ticker if ticker.endswith(".BA") else f"{ticker}.BA"
            elif ticker == "ARS_USD":
                yf_ticker = "ARS=X" # Correct Yahoo ticker for ARS/USD
            else:
                yf_ticker = ticker
                
            data = yf.download(yf_ticker, start=start_date, progress=False)
            if not data.empty:
                # Forward fill and then back fill to handle any gaps
                all_data[ticker] = data["Close"].ffill().bfill()
        except Exception as e:
            print(f"Error fetching historical for {ticker}: {e}")
            
    return all_data

@st.cache_data(ttl=86400) # Cache for 24 hours
def get_us_cpi(api_key):
    """
    Fetch US Consumer Price Index (CPIAUCSL) from FRED API.
    Requires an API key from https://fred.stlouisfed.org/docs/api/api_key.html
    Returns a dictionary of date strings (YYYY-MM-DD) to float values.
    """
    if not api_key:
        return {}
        
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={api_key}&file_type=json"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            observations = data.get("observations", [])
            
            cpi_data = {}
            for obs in observations:
                date = obs.get("date")
                val = obs.get("value")
                if val != "." and date:
                    cpi_data[date] = float(val)
            return cpi_data
        else:
            print(f"Error fetching CPI from FRED. Status code: {resp.status_code}")
            return {}
    except Exception as e:
        print(f"Exception fetching CPI: {e}")
        return {}
