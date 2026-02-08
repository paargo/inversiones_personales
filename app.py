import streamlit as st
import pandas as pd
import datetime
import os

import json
import requests

# Configuration
DATA_FILE = "investments.csv"
SETTINGS_FILE = "settings.json"

def load_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    else:
        return pd.DataFrame(columns=[
            "Date", "Ticker", "Platform", "Quantity", "Price", 
            "Currency", "Commission", "Commission_Type", "Total_Cost"
        ])

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    else:
        return {"api_keys": {}, "ticker_config": {}}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)

def get_binance_price(ticker):
    """Fetch current price for Ticker/USDT from Binance Public API"""
    try:
        symbol = f"{ticker}USDT"
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url, timeout=5)
        data = response.json()
        if "price" in data:
            return float(data["price"])
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
    return 0.0

def main():
    st.set_page_config(page_title="Investment Tracker", layout="centered")
    st.title("💰 Investment Tracker")

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

            # Button to update prices
            if st.button("🔄 Update Live Prices (Binance)"):
                with st.spinner("Fetching prices from Binance..."):
                    for index, row in grouped_df.iterrows():
                        ticker = row["Ticker"]
                        source = ticker_config.get(ticker, "Manual")
                        
                        if source == "Binance API":
                            price = get_binance_price(ticker)
                            if price > 0:
                                st.session_state["Current Price (USD)"][ticker] = price
                    st.success("Prices updated!")

            # Apply prices from session state or default to 0
            # We map the session state prices to the dataframe
            grouped_df["Current Price (USD)"] = grouped_df["Ticker"].map(st.session_state["Current Price (USD)"]).fillna(0.0)

            st.markdown("Enter or view current prices below:")
            
            edited_df = st.data_editor(
                grouped_df,
                column_config={
                    "Platform": st.column_config.TextColumn(disabled=True),
                    "Ticker": st.column_config.TextColumn(disabled=True),
                    "Quantity": st.column_config.NumberColumn(disabled=True, format="%.6f"),
                    "Total_Cost": st.column_config.NumberColumn("Total Cost Basis", disabled=True, format="%.2f"),
                    "Avg Buy Price": st.column_config.NumberColumn(disabled=True, format="%.2f"),
                    "Current Price (USD)": st.column_config.NumberColumn(min_value=0.0, format="%.6f", required=True)
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
        with st.form("api_settings"):
            st.markdown("**Crypto (Binance)**")
            binance_key = st.text_input("API Key", value=settings.get("api_keys", {}).get("binance_key", ""), type="password")
            binance_secret = st.text_input("API Secret", value=settings.get("api_keys", {}).get("binance_secret", ""), type="password")
            
            st.markdown("**Stock Market Data**")
            stock_key = st.text_input("API Key (e.g. AlphaVantage/Yahoo)", value=settings.get("api_keys", {}).get("stock_key", ""), type="password")
            
            save_api = st.form_submit_button("Save API Keys")
            if save_api:
                if "api_keys" not in settings:
                    settings["api_keys"] = {}
                settings["api_keys"]["binance_key"] = binance_key
                settings["api_keys"]["binance_secret"] = binance_secret
                settings["api_keys"]["stock_key"] = stock_key
                save_settings(settings)
                st.success("API Keys saved successfully!")

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
                        options=["Manual", "Binance API", "Stock API"],
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
