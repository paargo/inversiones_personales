import requests
import yfinance as yf
import pandas as pd

def get_dolar_rates():
    """Fetch MEP and CCL rates from dolarapi.com"""
    rates = {"MEP": 0.0, "CCL": 0.0}
    try:
        # Fetch MEP
        resp_mep = requests.get("https://dolarapi.com/v1/dolares/bolsa", timeout=5)
        if resp_mep.status_code == 200:
            rates["MEP"] = resp_mep.json().get("venta", 0.0)
            
        # Fetch CCL
        resp_ccl = requests.get("https://dolarapi.com/v1/dolares/contadoconliqui", timeout=5)
        if resp_ccl.status_code == 200:
            rates["CCL"] = resp_ccl.json().get("venta", 0.0)
            
    except Exception as e:
        print(f"Error fetching FX rates: {e}")
    return rates

def get_market_price(ticker, source):
    """
    Fetch current price from specified source.
    Returns: (price, currency)
    """
    price = 0.0
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
                response.raise_for_status() # Raise error for non-200 codes
                data = response.json()
                if "price" in data:
                    price = float(data["price"])
                    currency = "USD"
            except Exception as e:
                print(f"Binance API error for {ticker}: {e}. Falling back to Yahoo Finance.")
                try:
                    # Fallback to Yahoo Finance (Crypto usually ends in -USD)
                    yf_symbol = f"{ticker}-USD"
                    stock = yf.Ticker(yf_symbol)
                    hist = stock.history(period="1d")
                    if not hist.empty:
                        price = hist["Close"].iloc[-1]
                        currency = "USD"
                except Exception as yf_e:
                    print(f"Yahoo Finance fallback error for {ticker}: {yf_e}")

        elif source == "Argentina (BYMA)":
            # Append .BA if not present
            symbol = ticker if ticker.endswith(".BA") else f"{ticker}.BA"
            try:
                stock = yf.Ticker(symbol)
                # Fast fetch using history
                hist = stock.history(period="1d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
                    
                    # Try to detect currency using fast_info
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
        
    return price, currency

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
