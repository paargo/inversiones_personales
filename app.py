import streamlit as st
import pandas as pd
import datetime
import os

import json
import requests

import json
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import yfinance as yf

# Configuration
# DATA_FILE = "investments.csv" # Deprecated
# SETTINGS_FILE = "settings.json" # Deprecated

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def get_db_connection():
    """Connect to Google Sheets using st.secrets or local credentials.json"""
    try:
        # Check if running on Streamlit Cloud (or if secrets are set locally in .streamlit/secrets.toml)
        creds_dict = get_secret("gcp_service_account")
        if creds_dict:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        else:
            # Fallback to local file for development
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
        
        client = gspread.authorize(creds)
        
        # Open the spreadsheet (assumes user named it "Investment Tracker Data")
        # You can also config the sheet name in secrets
        sheet_name = get_secret("sheet_name") or "Investment Tracker Data"
            
        sh = client.open(sheet_name)
        return sh
    except Exception as e:
        st.error(f"Database Connection Error: {e}")
        st.stop()

def init_worksheets(sh):
    """Ensure required worksheets exist"""
    try:
        # Investments Sheet
        try:
            ws_inv = sh.worksheet("Investments")
        except gspread.WorksheetNotFound:
            ws_inv = sh.add_worksheet(title="Investments", rows=1000, cols=20)
            ws_inv.append_row([
                "Date", "Ticker", "Platform", "Quantity", "Price", 
                "Currency", "Commission", "Commission_Type", "Total_Cost"
            ])

        # Settings Sheet (Ticker Config)
        try:
            ws_settings = sh.worksheet("Settings")
        except gspread.WorksheetNotFound:
            ws_settings = sh.add_worksheet(title="Settings", rows=100, cols=5)
            ws_settings.append_row(["Ticker", "Data Source"])

        return ws_inv, ws_settings
    except Exception as e:
        st.error(f"Sheet Initialization Error: {e}")
        st.stop()

def load_data():
    sh = get_db_connection()
    ws_inv, _ = init_worksheets(sh)
    data = ws_inv.get_all_records()
    if data:
        return pd.DataFrame(data)
    else:
        return pd.DataFrame(columns=[
            "Date", "Ticker", "Platform", "Quantity", "Price", 
            "Currency", "Commission", "Commission_Type", "Total_Cost"
        ])

def save_data(df):
    sh = get_db_connection()
    ws_inv, _ = init_worksheets(sh)
    
    # Prepare data for saving
    df_tosave = df.copy()
    
    # Convert Date objects to string (JSON serializable)
    if "Date" in df_tosave.columns:
        df_tosave["Date"] = df_tosave["Date"].astype(str)
        
    # Handle NaN/None (replace with empty string or 0)
    df_tosave = df_tosave.fillna("")

    # Clear and rewrite (simple but inefficient for huge data, fine for personal app)
    ws_inv.clear()
    ws_inv.append_row(df_tosave.columns.tolist())
    ws_inv.append_rows(df_tosave.values.tolist())

def load_settings():
    # 1. API Keys -> Load from st.secrets (Read-only security)
    # 2. Ticker Config -> Load from GSheet "Settings" tab
    
    settings = {"api_keys": {}, "ticker_config": {}}
    
    # Load API Keys from Secrets
    api_keys = get_secret("api_keys")
    if api_keys:
        settings["api_keys"] = api_keys
    
    # Load Ticker Config from Sheet
    sh = get_db_connection()
    _, ws_settings = init_worksheets(sh)
    records = ws_settings.get_all_records()
    
    config = {}
    for r in records:
        if r["Ticker"]:
            config[r["Ticker"]] = r["Data Source"]
    settings["ticker_config"] = config
    
    return settings

def save_settings(settings):
    # Only saves Ticker Config to Sheet. API keys must be managed in secrets.toml/cloud dashboard.
    sh = get_db_connection()
    _, ws_settings = init_worksheets(sh)
    
    # Prepare dataframe
    config_data = []
    for ticker, source in settings.get("ticker_config", {}).items():
        config_data.append({"Ticker": ticker, "Data Source": source})
    
    df_config = pd.DataFrame(config_data)
    
    ws_settings.clear()
    ws_settings.append_row(["Ticker", "Data Source"])
    if not df_config.empty:
        ws_settings.append_rows(df_config.values.tolist())

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
            response = requests.get(url, timeout=5)
            data = response.json()
            if "price" in data:
                price = float(data["price"])
                currency = "USD"
                
        elif source == "Argentina (BYMA)":
            # Append .BA if not present
            symbol = ticker if ticker.endswith(".BA") else f"{ticker}.BA"
            try:
                stock = yf.Ticker(symbol)
                # Fast fetch using history
                hist = stock.history(period="1d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
                    # Try to detect currency from metadata, default to ARS for BYMA
                    # yfinance info is sometimes slow, so we can infer or fetch sparingly.
                    # For .BA, it's usually ARS unless it's a D ticker (e.g. AL30D.BA)
                    # We can check the suffix for 'D.BA' or 'C.BA' but reliable way is `stock.info['currency']`
                    # Optimization: assume ARS unless confirmed USD, or check suffix.
                    
                    # Heuristic: if ticker ends in D.BA or C.BA it might be USD, but let's try to get info if possible
                    # or just default to ARS for standard logic and rely on MEP conversion.
                    # User mentioned "SPYD", likely they map Ticker "SPYD" to source BYMA -> "SPYD.BA".
                    
                    # Using fast_info if available (newer yfinance)
                    try:
                        curr = stock.fast_info.currency
                        if curr:
                            currency = curr
                        else:
                            currency = "ARS" 
                    except:
                        # Fallback
                        currency = "ARS"
                        
            except Exception as e:
                print(f"YFinance error for {symbol}: {e}")
                
    except Exception as e:
        print(f"Error fetching {ticker} from {source}: {e}")
        
    return price, currency

def get_secret(key):
    """Safely get a secret from st.secrets to avoid StreamlitSecretNotFoundError"""
    try:
        return st.secrets.get(key)
    except Exception:
        return None

def main():
    st.set_page_config(page_title="Investment Tracker", layout="centered")
    st.title("💰 Investment Tracker")

    # Sidebar: connection status check
    # Check if credentials.json exists OR if we have secrets configured
    gcp_secret = get_secret("gcp_service_account")
    
    if not gcp_secret and not os.path.exists("credentials.json"):
        st.error("⚠️ No Google Cloud Connection found.")
        st.info("Please follow the setup guide to add `credentials.json` locally or configure `gcp_service_account` in Streamlit Secrets.")
        with st.expander("Creating Credentials.json"):
             st.markdown("1. Go to Google Cloud Console.\n2. Create Service Account & Key.\n3. Save as `credentials.json` in this folder.")
        st.stop()

    st.sidebar.title("Navigation")
    menu = ["New Entry", "Dashboard", "Settings"]
    choice = st.sidebar.radio("Go to", menu)


    if choice == "New Entry":
        st.subheader("Add New Investment")

        with st.form("entry_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                ticker = st.text_input("Ticker / Crypto Symbol").upper()
                platform = st.selectbox("Platform", ["Binance", "Interactive Brokers", "Coinbase", "Kraken", "Other"])
                date = st.date_input("Date", datetime.date.today())
                min_buy = st.selectbox("Purchase Currency", ["USD", "EUR", "ARS", "USDT"])

            with col2:
                quantity = st.number_input("Quantity", min_value=0.0, format="%.6f")
                price = st.number_input("Reference Price (per unit)", min_value=0.0, format="%.2f")
                
            st.markdown("---")
            st.markdown("**Commission Details**")
            col3, col4 = st.columns(2)
            with col3:
                commission_type = st.radio("Commission Type", ["Amount", "Percentage"], horizontal=True)
            with col4:
                commission_value = st.number_input("Commission Value", min_value=0.0, format="%.2f")

            # Calculate total for display (approximate, real calc on submit)
            total_preview = 0.0
            if quantity and price:
                base_cost = quantity * price
                if commission_type == "Amount":
                    comm_cost = commission_value
                else:
                    comm_cost = base_cost * (commission_value / 100)
                total_preview = base_cost + comm_cost

            st.markdown(f"### Estimated Total: {min_buy} {total_preview:,.2f}")

            submitted = st.form_submit_button("Save Investment")

            if submitted:
                if not ticker or quantity <= 0 or price <= 0:
                    st.error("Please fill in Ticker, Quantity and Price correctly.")
                else:
                    # Final Calculation
                    base_cost = quantity * price
                    if commission_type == "Amount":
                        final_commission = commission_value
                    else:
                        final_commission = base_cost * (commission_value / 100)
                    
                    total_cost = base_cost + final_commission

                    new_entry = {
                        "Date": date,
                        "Ticker": ticker,
                        "Platform": platform,
                        "Quantity": quantity,
                        "Price": price,
                        "Currency": min_buy,
                        "Commission": final_commission,
                        "Commission_Type": commission_type,
                        "Total_Cost": total_cost
                    }

                    df = load_data()
                    df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
                    save_data(df)
                    st.success(f"Saved: {quantity} {ticker} for {total_cost:,.2f} {min_buy}")

    elif choice == "Dashboard":
        st.subheader("Holdings Dashboard")
        
        # 1. Fetch and Display FX Rates
        dolar_rates = get_dolar_rates()
        col_mep, col_ccl = st.columns(2)
        col_mep.metric("Dólar MEP", f"${dolar_rates['MEP']:,.2f}")
        col_ccl.metric("Dólar CCL", f"${dolar_rates['CCL']:,.2f}")
        
        df = load_data()

        if not df.empty:
            # Group by Platform and Ticker
            grouped_df = df.groupby(["Platform", "Ticker"])[["Quantity", "Total_Cost"]].sum().reset_index()

            # Load settings for ticker source
            settings = load_settings()
            ticker_config = settings.get("ticker_config", {})

            grouped_df["Avg Buy Price"] = grouped_df["Total_Cost"] / grouped_df["Quantity"]
            
            # Helper to get current price (logic: if Binance API, fetch; else 0)
            if "Current Price (USD)" not in st.session_state:
                 st.session_state["Current Price (USD)"] = {}
            if "Native Price" not in st.session_state:
                 st.session_state["Native Price"] = {} # Store {Ticker: {Price: 100, Currency: ARS}}

            # Button to update prices
            if st.button("🔄 Update Live Prices"):
                with st.spinner("Fetching prices..."):
                    mep_rate = dolar_rates.get("MEP", 0.0)
                    
                    for index, row in grouped_df.iterrows():
                        ticker = row["Ticker"]
                        source = ticker_config.get(ticker, "Manual")
                        
                        if source != "Manual":
                            price, currency = get_market_price(ticker, source)
                            
                            if price > 0:
                                # Store Native Info
                                st.session_state["Native Price"][ticker] = {"price": price, "currency": currency}
                                
                                # Convert to USD for Total
                                price_usd = 0.0
                                if currency == "USD" or currency == "USDT":
                                    price_usd = price
                                elif currency == "ARS" and mep_rate > 0:
                                    price_usd = price / mep_rate
                                else:
                                    price_usd = 0.0 # Unknown conversion
                                
                                st.session_state["Current Price (USD)"][ticker] = price_usd

                    st.success("Prices updated!")

            # Apply prices from session state
            # We map the session state prices to the dataframe
            grouped_df["Current Price (USD)"] = grouped_df["Ticker"].map(st.session_state["Current Price (USD)"]).fillna(0.0)
            
            # Enrich with Native Price info for display
            def get_native_display(ticker):
                data = st.session_state.get("Native Price", {}).get(ticker)
                if data:
                    return f"{data['price']:,.2f} {data['currency']}"
                return "-"
            
            grouped_df["Live Price (Native)"] = grouped_df["Ticker"].apply(get_native_display)

            st.markdown("Enter or view current prices below:")
            
            edited_df = st.data_editor(
                grouped_df,
                column_config={
                    "Platform": st.column_config.TextColumn(disabled=True),
                    "Ticker": st.column_config.TextColumn(disabled=True),
                    "Quantity": st.column_config.NumberColumn(disabled=True, format="%.6f"),
                    "Total_Cost": st.column_config.NumberColumn("Total Cost Basis", disabled=True, format="%.2f"),
                    "Avg Buy Price": st.column_config.NumberColumn(disabled=True, format="%.2f"),
                    "Live Price (Native)": st.column_config.TextColumn("Live Price (Source)", disabled=True),
                    "Current Price (USD)": st.column_config.NumberColumn(min_value=0.0, format="%.6f", required=True, help="Used for Portfolio Total. Calculated from Native Price / MEP if ARS.")
                },
                hide_index=True,
                use_container_width=True
            )
            
            # If user edits manually, update session state to persist across reruns
            # Note: data_editor returns the state AFTER edit. We can sync it back if needed, 
            # but for simple calc, we just use edited_df.
            
            if not edited_df.empty:
                edited_df["Updated Value (USD)"] = edited_df["Quantity"] * edited_df["Current Price (USD)"]
                total_value = edited_df["Updated Value (USD)"].sum()
                
                st.divider()
                st.metric("Total Portfolio Value (USD)", f"${total_value:,.2f}")
                
                st.subheader("Detailed Breakdown")
                st.dataframe(
                    edited_df[["Platform", "Ticker", "Quantity", "Current Price (USD)", "Updated Value (USD)"]],
                    use_container_width=True
                )
        else:
            st.info("No investments found. Go to 'New Entry' to add some.")

    elif choice == "Settings":
        st.subheader("⚙️ Configuration")
        settings = load_settings()
        
        # 1. API Integration Settings
        st.markdown("### API Integration")
        st.info("API Keys are now managed via Streamlit Secrets for security.")
        
        with st.expander("How to configure API Keys"):
            st.markdown("""
            **Locally:**
            Create a file `.streamlit/secrets.toml` with:
            ```toml
            [api_keys]
            binance_key = "YOUR_KEY"
            binance_secret = "YOUR_SECRET"
            stock_key = "YOUR_KEY"
            ```
            
            **Streamlit Cloud:**
            Go to App Settings -> Secrets and paste the same content.
            """)

        # Display current status (masked)
        api_keys = settings.get("api_keys", {})
        st.text_input("Binance Key", value="********" if api_keys.get("binance_key") else "", disabled=True)
        st.text_input("Binance Secret", value="********" if api_keys.get("binance_secret") else "", disabled=True)


        st.divider()

        # 2. Ticker Configuration
        st.markdown("### Ticker Configuration")
        st.markdown("Select where to fetch data for each asset.")
        
        df = load_data()
        if not df.empty:
            unique_tickers = df["Ticker"].unique()
            
            # Prepare data for editor
            ticker_config_data = []
            current_config = settings.get("ticker_config", {})
            
            for t in unique_tickers:
                ticker_config_data.append({
                    "Ticker": t,
                    "Data Source": current_config.get(t, "Manual")
                })
            
            ticker_df = pd.DataFrame(ticker_config_data)
            
            edited_ticker_df = st.data_editor(
                ticker_df,
                column_config={
                    "Ticker": st.column_config.TextColumn(disabled=True),
                    "Data Source": st.column_config.SelectboxColumn(
                        options=["Manual", "Binance API", "Argentina (BYMA)", "Stock API"],
                        required=True
                    )
                },
                hide_index=True,
                use_container_width=True,
                key="ticker_editor"
            )
            
            if st.button("Save Ticker Configuration"):
                new_config = {}
                for index, row in edited_ticker_df.iterrows():
                    new_config[row["Ticker"]] = row["Data Source"]
                
                settings["ticker_config"] = new_config
                save_settings(settings)
                st.success("Ticker configuration saved!")
        else:
            st.info("Add investments first to configure tickers.")


if __name__ == "__main__":
    main()
