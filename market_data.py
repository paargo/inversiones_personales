import requests
import yfinance as yf
import pandas as pd
import streamlit as st

@st.cache_data(ttl=1800) # Cache for 30 minutes
def get_dolar_rates():
    """Fetch MEP, CCL and Cripto rates from dolarapi.com + Variation proxy"""
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
            
    except Exception as e:
        print(f"Error fetching FX rates: {e}")
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
