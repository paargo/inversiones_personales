import requests
import yfinance as yf

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
            try:
                response = requests.get(url, timeout=5)
                data = response.json()
                if "price" in data:
                    price = float(data["price"])
                    currency = "USD"
            except Exception as e:
                 print(f"Binance API error: {e}")

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
