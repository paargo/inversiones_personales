import streamlit as st
import pandas as pd
import datetime
import os

# Custom Modules
import utils
import database as db
import market_data as md

def main():
    st.set_page_config(page_title="Investment Tracker", layout="centered")
    st.title("💰 Investment Tracker")

    # Sidebar: connection status check
    # Check if credentials.json exists OR if we have secrets configured
    gcp_secret = utils.get_secret("gcp_service_account")
    
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
                quantity_input = st.text_input("Quantity", value="0.0")
                price_input = st.text_input("Reference Price (per unit)", value="0.0")
                
                # Parse inputs
                quantity = utils.safe_float(quantity_input)
                price = utils.safe_float(price_input)
                
            st.markdown("---")
            st.markdown("**Commission Details**")
            col3, col4 = st.columns(2)
            with col3:
                commission_type = st.radio("Commission Type", ["Amount", "Percentage"], horizontal=True)
            with col4:
                commission_input = st.text_input("Commission Value", value="0.0")
                commission_value = utils.safe_float(commission_input)

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

                    df = db.load_data()
                    df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
                    db.save_data(df)
                    st.success(f"Saved: {quantity} {ticker} for {total_cost:,.2f} {min_buy}")

    elif choice == "Dashboard":
        st.subheader("Holdings Dashboard")
        
        # 1. Fetch and Display FX Rates
        dolar_rates = md.get_dolar_rates()
        col_mep, col_ccl = st.columns(2)
        col_mep.metric("Dólar MEP", f"${dolar_rates['MEP']:,.2f}")
        col_ccl.metric("Dólar CCL", f"${dolar_rates['CCL']:,.2f}")
        
        df = db.load_data()

        if not df.empty:
            # Group by Platform and Ticker
            grouped_df = df.groupby(["Platform", "Ticker"])[["Quantity", "Total_Cost"]].sum().reset_index()

            # Load settings for ticker source
            settings = db.load_settings()
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
                            price, currency = md.get_market_price(ticker, source)
                            
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
        settings = db.load_settings()
        
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
        
        df = db.load_data()
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
                db.save_settings(settings)
                st.success("Ticker configuration saved!")
        else:
            st.info("Add investments first to configure tickers.")


if __name__ == "__main__":
    main()
