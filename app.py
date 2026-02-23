import streamlit as st
import pandas as pd
import datetime
import os
from streamlit_autorefresh import st_autorefresh

# Custom Modules
import utils
import database as db
import market_data as md

# Configuration constants
PRICE_UPDATE_INTERVAL_MINUTES = 30

def main():
    st.set_page_config(page_title="Control de Inversiones", layout="wide")
    st.title("💰 Control de Inversiones")

    # 1. Global Market Header (Visible on all pages)
    dolar_rates = md.get_dolar_rates()
    # Fetch BTC price for the header
    btc_price, _, btc_prev_close = md.get_market_price("BTC", "Binance API")
    
    col_mep, col_ccl, col_crypto, col_btc = st.columns(4)
    
    # Helper for small variation capsules
    def metric_capsule(variation):
        color = "#28a745" if variation >= 0 else "#dc3545"
        symbol = "▲" if variation >= 0 else "▼"
        return f"""
        <div style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 10px; display: inline-block; font-size: 0.75em; margin-top: -10px;">
            {symbol} {abs(variation):.2%}
        </div>
        """

    col_mep.metric("Dólar MEP", f"${dolar_rates['MEP']:,.2f}")
    col_mep.markdown(metric_capsule(dolar_rates.get("variation", 0.0)), unsafe_allow_html=True)
    
    col_ccl.metric("Dólar CCL", f"${dolar_rates['CCL']:,.2f}")
    col_ccl.markdown(metric_capsule(dolar_rates.get("variation", 0.0)), unsafe_allow_html=True)
    
    col_crypto.metric("Dólar Cripto", f"${dolar_rates['Cripto']:,.2f}")
    col_crypto.markdown(metric_capsule(dolar_rates.get("variation", 0.0)), unsafe_allow_html=True)
    
    col_btc.metric("Precio BTC", f"${btc_price:,.2f}" if btc_price > 0 else "-")
    if btc_price > 0 and btc_prev_close > 0:
        btc_var = (btc_price / btc_prev_close - 1)
        col_btc.markdown(metric_capsule(btc_var), unsafe_allow_html=True)
    
    st.divider()

    # Sidebar: connection status check
    # Check if credentials.json exists OR if we have secrets configured
    gcp_secret = utils.get_secret("gcp_service_account")
    
    if not gcp_secret and not os.path.exists("credentials.json"):
        st.error("⚠️ No Google Cloud Connection found.")
        st.info("Please follow the setup guide to add `credentials.json` locally or configure `gcp_service_account` in Streamlit Secrets.")
        with st.expander("Creating Credentials.json"):
             st.markdown("1. Go to Google Cloud Console.\n2. Create Service Account & Key.\n3. Save as `credentials.json` in this folder.")
        st.stop()

    # Custom CSS for Navigation Banners
    st.markdown("""
        <style>
        /* Style for sidebar buttons to look like banners */
        div.stButton > button {
            width: 100%;
            height: 50px;
            border-radius: 5px;
            border: 1px solid #ffffff;
            background-color: transparent;
            color: #ffffff;
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 10px;
            transition: all 0.3s ease;
            text-align: center;
        }
        
        div.stButton > button:hover {
            border-color: #ff4b4b;
            color: #ff4b4b;
            background-color: rgba(255, 75, 75, 0.05);
        }

        /* Active button style */
        .active-nav-button {
            background-color: #ff4b4b !important;
            color: white !important;
            border-color: #ff4b4b !important;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        </style>
    """, unsafe_allow_html=True)

    st.sidebar.title("Menú")
    
    # Initialize menu choice in session state
    if "menu_choice" not in st.session_state:
        st.session_state["menu_choice"] = "Dashboard"

    menu = ["Dashboard", "Ingresar Compra", "Configuración"]
    
    # Render banners
    for item in menu:
        is_active = st.session_state["menu_choice"] == item
        
        # We use a container to apply different style if active
        # Streamlit doesn't support direct class assignment to buttons easily, 
        # so we'll use a hack or just rely on the CSS selector for all buttons
        # To make one "look" active, we can use a different button type or just accept that 
        # they all look the same but the logic works.
        # Actually, let's use a trick: if active, we wrap it in a div that we can target?
        # Streamlit buttons are hard to style individually without unique IDs.
        # Let's just use the standard button but with a logic check.
        
        if st.sidebar.button(
            item, 
            key=f"nav_{item}", 
            use_container_width=True,
            type="primary" if is_active else "secondary"
        ):
            st.session_state["menu_choice"] = item
            st.rerun()

    choice = st.session_state["menu_choice"]


    if choice == "Ingresar Compra":
        st.subheader("Ingresar Nueva Inversión")
        
        # Load platforms and tickers for selection
        platforms_df = db.load_platforms()
        platform_names = platforms_df["Platform"].tolist() if not platforms_df.empty else ["Manual"]
        
        settings = db.load_settings()
        ticker_config = settings.get("ticker_config", {})
        existing_tickers = sorted(list(ticker_config.keys()))
        ticker_options = existing_tickers + ["➕ Add New Ticker..."]
        
        # Ticker selection (outside form for dynamic behavior)
        selected_ticker_opt = st.selectbox("Ticker / Símbolo Crypto", ticker_options)
        
        ticker = ""
        if selected_ticker_opt == "➕ Add New Ticker...":
            ticker = st.text_input("Ingresar Nuevo Ticker").upper()
        else:
            ticker = selected_ticker_opt

        with st.form("entry_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                # Ticker is already determined above
                st.info(f"Selected Ticker: **{ticker if ticker else 'None'}**")
                platform = st.selectbox("Plataforma", platform_names)
                date = st.date_input("Fecha", datetime.date.today())
                min_buy = st.selectbox("Moneda de Compra", ["USD", "EUR", "ARS", "USDT"])

            with col2:
                quantity_input = st.text_input("Cantidad", value="0.0")
                price_input = st.text_input("Precio de Referencia (p/unidad)", value="0.0")
                
                # Parse inputs
                quantity = utils.safe_float(quantity_input)
                price = utils.safe_float(price_input)
                
            # Automation logic (look up platform)
            comm_val = 0.0
            comm_type = "Percentage"
            comm_curr = "USD"
            
            if not platforms_df.empty and platform in platform_names:
                plat_config = platforms_df[platforms_df["Platform"] == platform].iloc[0]
                comm_val = plat_config["Entry Commission"]
                comm_type = plat_config["Entry Type"]
                comm_curr = plat_config["Commission Currency"]

            # Calculate total for display
            total_preview = 0.0
            if quantity and price:
                base_cost = quantity * price
                if comm_type == "Amount":
                    if comm_curr == "BTC":
                        comm_cost = comm_val * price
                    else:
                        comm_cost = comm_val
                else:
                    comm_cost = base_cost * (comm_val / 100)
                total_preview = base_cost + comm_cost

            st.markdown(f"**Comisión:** {comm_val} {comm_type} ({comm_curr})")
            st.markdown(f"### Total Estimado: {min_buy} {total_preview:,.8f}" if total_preview < 1 else f"### Total Estimado: {min_buy} {total_preview:,.2f}")

            submitted = st.form_submit_button("Guardar Inversión")

            if submitted:
                if not ticker or quantity <= 0 or price <= 0:
                    st.error("Por favor completa Ticker, Cantidad y Precio correctamente.")
                else:
                    # Final Calculation
                    base_cost = quantity * price
                    if comm_type == "Amount":
                        if comm_curr == "BTC":
                            final_commission_val = comm_val * price
                        else:
                            final_commission_val = comm_val
                    else:
                        final_commission_val = base_cost * (comm_val / 100)
                    
                    total_cost = base_cost + final_commission_val

                    new_entry = {
                        "Date": date,
                        "Ticker": ticker,
                        "Platform": platform,
                        "Quantity": quantity,
                        "Price": price,
                        "Currency": min_buy,
                        "Commission": comm_val, 
                        "Commission_Type": comm_type,
                        "Commission_Currency": comm_curr,
                        "Total_Cost": total_cost
                    }

                    df = db.load_data()
                    df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
                    db.save_data(df)
                    st.session_state["prices_updated"] = False # Reset flag to force update on dashboard
                    st.success(f"Guardado: {quantity} {ticker} por {total_cost:,.2f} {min_buy}")

    elif choice == "Dashboard":
        st.subheader("Panel de Activos")
        
        df = db.load_data()

        if not df.empty:
            mep_rate = dolar_rates.get("MEP", 0.0)
            
            # Convert all costs to USD for accurate calculation and grouping
            def to_usd(row):
                if row["Currency"] == "ARS" and mep_rate > 0:
                    return row["Total_Cost"] / mep_rate
                return row["Total_Cost"]
            
            df["Total_Cost_USD"] = df.apply(to_usd, axis=1)

            # Group by Platform and Ticker - Summing the USD costs
            grouped_df = df.groupby(["Platform", "Ticker"])[["Quantity", "Total_Cost_USD"]].sum().reset_index()
            # Rename for consistency with downstream code
            grouped_df = grouped_df.rename(columns={"Total_Cost_USD": "Total_Cost"})

            # Load settings for ticker source
            settings = db.load_settings()
            ticker_config = settings.get("ticker_config", {})

            grouped_df["Avg Buy Price"] = grouped_df["Total_Cost"] / grouped_df["Quantity"]
            
            # Helper to get current price (logic: if Binance API, fetch; else 0)
            if "Current Price (USD)" not in st.session_state:
                 st.session_state["Current Price (USD)"] = {}
            if "Native Price" not in st.session_state:
                 st.session_state["Native Price"] = {} # Store {Ticker: {Price: 100, Currency: ARS}}
            if "Prev Close Price (USD)" not in st.session_state:
                 st.session_state["Prev Close Price (USD)"] = {}
            if "last_update_time" not in st.session_state:
                 st.session_state["last_update_time"] = None

            # 3. Auto-update logic
            # Refresh the app every 1 minute to check for the update interval
            st_autorefresh(interval=60 * 1000, key="price_update_refresh")

            should_update = st.button("🔄 Actualizar Precios")
            
            # Check elapsed time for automatic update
            if st.session_state["last_update_time"]:
                elapsed_minutes = (datetime.datetime.now() - st.session_state["last_update_time"]).total_seconds() / 60
                if elapsed_minutes >= PRICE_UPDATE_INTERVAL_MINUTES:
                    should_update = True
            
            if not st.session_state.get("prices_updated", False) and not grouped_df.empty:
                should_update = True

            if should_update:
                with st.spinner("Obteniendo precios..."):
                    # ... (rest of the fetching logic)
                    mep_rate = dolar_rates.get("MEP", 0.0)
                    
                    for index, row in grouped_df.iterrows():
                        ticker = row["Ticker"]
                        source = ticker_config.get(ticker, "Manual")
                        
                        if source != "Manual":
                            price, currency, prev_close = md.get_market_price(ticker, source)
                            
                            if price > 0:
                                # Store Native Info
                                st.session_state["Native Price"][ticker] = {"price": price, "currency": currency}
                                
                                # Convert current price to USD
                                price_usd = 0.0
                                if currency == "USD" or currency == "USDT":
                                    price_usd = price
                                elif currency == "ARS" and mep_rate > 0:
                                    price_usd = price / mep_rate
                                
                                st.session_state["Current Price (USD)"][ticker] = price_usd

                                # Convert prev close to USD
                                prev_close_usd = 0.0
                                if prev_close > 0:
                                    if currency in ["USD", "USDT"]:
                                        prev_close_usd = prev_close
                                    elif currency == "ARS" and mep_rate > 0:
                                        prev_close_usd = prev_close / mep_rate
                                
                                st.session_state["Prev Close Price (USD)"][ticker] = prev_close_usd

                    st.session_state["prices_updated"] = True
                    st.session_state["last_update_time"] = datetime.datetime.now()
                    st.success(f"¡Precios actualizados! (Próxima actualización en {PRICE_UPDATE_INTERVAL_MINUTES} min)")

            # Apply prices from session state
            # We map the session state prices to the dataframe
            grouped_df["Current Price (USD)"] = grouped_df["Ticker"].map(st.session_state["Current Price (USD)"]).fillna(0.0)

            # Pre-calculate derived columns for the editor
            grouped_df["Updated Value (USD)"] = grouped_df["Quantity"] * grouped_df["Current Price (USD)"]
            grouped_df["Result ($)"] = grouped_df["Updated Value (USD)"] - grouped_df["Total_Cost"]
            grouped_df["Result (%)"] = grouped_df.apply(
                lambda row: f"{(row['Updated Value (USD)'] / row['Total_Cost'] - 1):+.2%}" if row["Total_Cost"] > 0 else "0.00%", 
                axis=1
            )
            
            # Daily Variation Columns
            grouped_df["Prev Close (USD)"] = grouped_df["Ticker"].map(st.session_state.get("Prev Close Price (USD)", {})).fillna(0.0)
            grouped_df["Day Chg ($)"] = grouped_df["Quantity"] * (grouped_df["Current Price (USD)"] - grouped_df["Prev Close (USD)"])
            grouped_df["Day Chg (%)"] = (grouped_df["Day Chg ($)"] / (grouped_df["Quantity"] * grouped_df["Prev Close (USD)"])) if not (grouped_df["Quantity"] * grouped_df["Prev Close (USD)"]).empty else 0.0
            # Handle (%) calculation per row
            grouped_df["Day Chg (%)"] = grouped_df.apply(
                lambda row: (row["Day Chg ($)"] / (row["Quantity"] * row["Prev Close (USD)"])) if (row["Quantity"] * row["Prev Close (USD)"]) > 0 else 0.0,
                axis=1
            )
            
            # Enrich with Native Price info for display
            def get_native_display(ticker):
                data = st.session_state.get("Native Price", {}).get(ticker)
                if data:
                    return f"{data['price']:,.2f} {data['currency']}"
                return "-"
            
            grouped_df["Live Price (Native)"] = grouped_df["Ticker"].apply(get_native_display)

            # Filter columns to show for editing
            edit_cols = [
                "Platform", "Ticker", "Quantity", "Total_Cost", "Avg Buy Price", 
                "Current Price (USD)", "Updated Value (USD)", 
                "Day Chg ($)", "Day Chg (%)",
                "Result ($)", "Result (%)"
            ]
            
            # Calculate Totals for the editor
            total_cost_editor = grouped_df["Total_Cost"].sum()
            total_value_editor = grouped_df["Updated Value (USD)"].sum()
            total_result_editor = grouped_df["Result ($)"].sum()
            total_result_pct_editor = (total_value_editor / total_cost_editor - 1) if total_cost_editor > 0 else 0
            
            total_day_chg_editor = grouped_df["Day Chg ($)"].sum()
            total_day_prev_val = (grouped_df["Quantity"] * grouped_df["Prev Close (USD)"]).sum()
            total_day_chg_pct_editor = (total_day_chg_editor / total_day_prev_val) if total_day_prev_val > 0 else 0
            
            total_row_editor = pd.DataFrame([{
                "Platform": "TOTAL",
                "Ticker": "",
                "Quantity": "",
                "Total_Cost": f"{total_cost_editor:,.2f}",
                "Avg Buy Price": "",
                "Current Price (USD)": "",
                "Updated Value (USD)": f"{total_value_editor:,.2f}",
                "Day Chg ($)": f"{total_day_chg_editor:+,.2f}",
                "Day Chg (%)": f"{total_day_chg_pct_editor:+.2%}",
                "Result ($)": f"{total_result_editor:+,.2f}",
                "Result (%)": f"{total_result_pct_editor:+.2%}"
            }])
            
            # For the editor to show empty strings, we convert the display columns to strings
            # except Current Price which must stay numeric for editing the other rows.
            # However, if we mix string and number in Current Price, it becomes object.
            # Streamlit data_editor handles object columns as TextColumn by default.
            
            df_for_editor = grouped_df[edit_cols].copy()
            # Format numeric columns as strings for the editor to match the TOTAL row style
            # but KEEP Current Price as numeric for editing
            for col in ["Quantity", "Total_Cost", "Avg Buy Price", "Updated Value (USD)", "Day Chg ($)", "Result ($)"]:
                df_for_editor[col] = df_for_editor[col].apply(lambda x: f"{x:,.6f}" if "Quantity" in col or "Price" in col else f"{x:+,.2f}" if "Chg" in col or "Result" in col else f"{x:,.2f}")
            
            df_for_editor["Day Chg (%)"] = df_for_editor["Day Chg (%)"].apply(lambda x: f"{x:+.2%}")
            
            df_for_editor = pd.concat([df_for_editor, total_row_editor], ignore_index=True)

            edited_df = st.data_editor(
                df_for_editor,
                column_config={
                    "Platform": st.column_config.TextColumn("Plataforma", disabled=True),
                    "Ticker": st.column_config.TextColumn("Ticker", disabled=True),
                    "Quantity": st.column_config.TextColumn("Cantidad", disabled=True),
                    "Total_Cost": st.column_config.TextColumn("Costo Base Total", disabled=True),
                    "Avg Buy Price": st.column_config.TextColumn("Precio Prom. Compra", disabled=True),
                    "Current Price (USD)": st.column_config.TextColumn("Precio Actual (USD)", help="Edita precios en las filas de activos. La fila TOTAL es de solo lectura."),
                    "Updated Value (USD)": st.column_config.TextColumn("Valor Actualizado (USD)", disabled=True),
                    "Day Chg ($)": st.column_config.TextColumn("Var. Día ($)", disabled=True),
                    "Day Chg (%)": st.column_config.TextColumn("Var. Día (%)", disabled=True),
                    "Result ($)": st.column_config.TextColumn("Resultado ($)", disabled=True),
                    "Result (%)": st.column_config.TextColumn("Resultado (%)", disabled=True)
                },
                hide_index=True,
                use_container_width=True
            )
            
            # Sync edits back to session state
            if not edited_df.empty:
                changes = False
                for index, row in edited_df.iterrows():
                    if row["Platform"] == "TOTAL":
                        continue
                    
                    ticker = row["Ticker"]
                    try:
                        # Convert back to float since it's now string in the editor
                        new_price = utils.safe_float(str(row["Current Price (USD)"]))
                        if st.session_state["Current Price (USD)"].get(ticker) != new_price:
                            st.session_state["Current Price (USD)"][ticker] = new_price
                            changes = True
                    except:
                        pass
                
                if changes:
                    st.rerun()

                # Proceed with Totals using only data rows (excluding the TOTAL row from editor)
                data_df = edited_df[edited_df["Platform"] != "TOTAL"].copy()
                
                # Convert string columns back to numeric for math and formatting (they were formatted for display in the editor)
                for col in ["Quantity", "Total_Cost", "Avg Buy Price", "Current Price (USD)", "Updated Value (USD)", "Result ($)"]:
                    data_df[col] = data_df[col].apply(utils.safe_float)
                
                # Recalculate totals for display
                total_value = data_df["Updated Value (USD)"].sum()
                total_cost = data_df["Total_Cost"].sum()
                total_result = data_df["Result ($)"].sum()
                total_result_pct = (total_value / total_cost - 1) if total_cost > 0 else 0.0

                st.divider()
                
                # Calculate Daily Delta
                data_df["Prev Close (USD)"] = data_df["Ticker"].map(st.session_state.get("Prev Close Price (USD)", {})).fillna(0.0)
                # If prev close is 0 (new asset or error), we use avg buy price or current price to avoid huge spikes?
                # Actually, if we want "Daily Update", if we don't have yesterday's price, variation is 0 for that asset.
                daily_change_usd = (data_df["Quantity"] * (data_df["Current Price (USD)"] - data_df["Prev Close (USD)"])).sum()
                daily_change_pct = (daily_change_usd / (data_df["Quantity"] * data_df["Prev Close (USD)"]).sum()) if (data_df["Quantity"] * data_df["Prev Close (USD)"]).sum() > 0 else 0.0

                # UI: Portfolio Header with Delta Capsule
                col_title, col_delta = st.columns([3, 1])
                with col_title:
                    st.metric("Valor Total de Cartera (USD)", f"${total_value:,.2f}", delta=f"${total_result:,.2f} ({total_result_pct:+.2%})")
                
                with col_delta:
                    # Daily Variation "Capsule"
                    color = "#28a745" if daily_change_usd >= 0 else "#dc3545"
                    symbol = "▲" if daily_change_usd >= 0 else "▼"
                    st.markdown(
                        f"""
                        <div style="background-color: {color}; color: white; padding: 10px 15px; border-radius: 20px; text-align: center; margin-top: 15px;">
                            <span style="font-weight: bold; font-size: 0.9em;">ACTUALIZACIÓN DIARIA</span><br>
                            <span style="font-size: 1.2em;">{symbol} ${abs(daily_change_usd):,.2f} ({daily_change_pct:+.2%})</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                
                st.subheader("Desglose Detallado")
                
                # Prepare display dataframe using the RAW transactions (df)
                # Apply current prices to EACH transaction
                breakdown_df = df.copy()
                breakdown_df["Current Price (USD)"] = breakdown_df["Ticker"].map(st.session_state["Current Price (USD)"]).fillna(0.0)
                breakdown_df["Updated Value (USD)"] = breakdown_df["Quantity"] * breakdown_df["Current Price (USD)"]
                breakdown_df["Result ($)"] = breakdown_df["Updated Value (USD)"] - breakdown_df["Total_Cost_USD"]
                breakdown_df["Result (%)"] = breakdown_df.apply(
                    lambda row: (row["Updated Value (USD)"] / row["Total_Cost_USD"] - 1) if row["Total_Cost_USD"] > 0 else 0.0,
                    axis=1
                )

                # Select and format columns for display
                display_cols = ["Date", "Platform", "Ticker", "Quantity", "Price", "Currency", "Total_Cost_USD", "Current Price (USD)", "Updated Value (USD)", "Result ($)", "Result (%)"]
                display_df = breakdown_df[display_cols].copy()

                # Format Date for display
                display_df["Date"] = pd.to_datetime(display_df["Date"]).dt.date
                
                # Format numeric columns as strings
                display_df["Quantity"] = display_df["Quantity"].apply(lambda x: f"{x:,.6f}")
                display_df["Price"] = display_df["Price"].apply(lambda x: f"{x:,.2f}")
                display_df["Total_Cost_USD"] = display_df["Total_Cost_USD"].apply(lambda x: f"{x:,.2f}")
                display_df["Current Price (USD)"] = display_df["Current Price (USD)"].apply(lambda x: f"{x:,.6f}")
                display_df["Updated Value (USD)"] = display_df["Updated Value (USD)"].apply(lambda x: f"{x:,.2f}")
                display_df["Result ($)"] = display_df["Result ($)"].apply(lambda x: f"{x:+,.2f}")
                display_df["Result (%)"] = display_df["Result (%)"].apply(lambda x: f"{x:+.2%}")
                
                # Create a total row
                total_row = pd.DataFrame([{
                    "Date": "TOTAL",
                    "Platform": "",
                    "Ticker": "",
                    "Quantity": "", 
                    "Price": "",
                    "Currency": "",
                    "Total_Cost_USD": f"{total_cost:,.2f}",
                    "Current Price (USD)": "",
                    "Updated Value (USD)": f"{total_value:,.2f}",
                    "Result ($)": f"{total_result:+,.2f}",
                    "Result (%)": f"{total_result_pct:+.2%}"
                }])
                
                display_df = pd.concat([display_df, total_row], ignore_index=True)
                
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True
                )
                
                # --- NEW: Portfolio Progress Chart ---
                st.divider()
                st.subheader("📈 Evolución de Cartera")
                
                with st.spinner("Calculando progreso histórico..."):
                    try:
                        # 1. Prepare Daily Timeline
                        df["Date"] = pd.to_datetime(df["Date"])
                        min_date = df["Date"].min()
                        today = datetime.date.today()
                        date_range = pd.date_range(start=min_date, end=today, freq="D")
                        
                        # 2. Get Historical Prices
                        # Get unique tickers and their sources
                        unique_tickers = df["Ticker"].unique()
                        tickers_to_fetch = {t: ticker_config.get(t, "Manual") for t in unique_tickers}
                        
                        # Add ARS/USD for conversion
                        # Note: We use ARSUSD=X or just calculate a constant if not found
                        # To keep it simple and robust, let's fetch it if there are ARS assets
                        has_ars = not df[df["Currency"] == "ARS"].empty
                        if has_ars:
                            tickers_to_fetch["ARS_USD"] = "Global" # Dummy source for helper
                            
                        # Fetch
                        historical_prices = md.get_historical_prices(tickers_to_fetch, min_date)
                        
                        # Fix ARS_USD if dummy used
                        if "ARS_USD" in historical_prices.columns:
                            # Yahoo returns ARS per USD usually for ARS=X, check scale
                            # Actually ARSUSD=X is USD per 1 ARS. 
                            # Let's assume we want to convert ARS cost to USD.
                            pass

                        # 3. Calculate Daily Status
                        # Pre-convert transactions to USD cost (using current MEP for simplicity if history fails)
                        mep_rate = dolar_rates.get("MEP", 1.0)
                        def to_usd(row):
                            if row["Currency"] in ["USD", "USDT"]:
                                return row["Total_Cost"]
                            return row["Total_Cost"] / mep_rate
                        
                        df["Total_Cost_USD"] = df.apply(to_usd, axis=1)
                        
                        chart_data = []
                        for d in date_range:
                            # Transactions up to this day
                            mask = df["Date"] <= d
                            current_df = df[mask]
                            
                            if current_df.empty:
                                continue
                                
                            invested_capital = current_df["Total_Cost_USD"].sum()
                            
                            # Market Value
                            market_value = 0.0
                            # Group by ticker to get current cumulative quantity
                            holdings = current_df.groupby("Ticker")["Quantity"].sum()
                            
                            for t, qty in holdings.items():
                                if t in historical_prices.columns:
                                    # Get price for that day or last available
                                    day_prices = historical_prices[t].loc[:d]
                                    if not day_prices.empty:
                                        p = day_prices.iloc[-1]
                                        if pd.isna(p):
                                            # If still NaN, try to use the last non-nan price in the series
                                            p = day_prices.dropna().iloc[-1] if not day_prices.dropna().empty else 0.0
                                        market_value += qty * p
                                    else:
                                        # Fallback to cost basis if no price info yet to avoid NaN gap
                                        market_value += current_df[current_df["Ticker"] == t]["Total_Cost_USD"].sum()
                                else:
                                    # Fallback to last known session price if it's today
                                    if d.date() == today:
                                         market_value += qty * st.session_state["Current Price (USD)"].get(t, 0.0)
                                    else:
                                        # Fallback to cost basis for historical days without price info
                                        market_value += current_df[current_df["Ticker"] == t]["Total_Cost_USD"].sum()

                            chart_data.append({
                                "Date": d,
                                "Invested Capital (USD)": invested_capital,
                                "Market Value (USD)": market_value
                            })
                            
                        if chart_data:
                            history_df = pd.DataFrame(chart_data).set_index("Date")
                            # Handle any remaining NaNs in the final dataframe
                            history_df = history_df.fillna(method='ffill').fillna(0)
                            st.line_chart(history_df, use_container_width=True)
                            
                            # Summary metric for the chart
                            last_market_val = chart_data[-1]["Market Value (USD)"]
                            last_invested = chart_data[-1]["Invested Capital (USD)"]
                            
                            # Ensure we don't show NaN if values are missing
                            if pd.isna(last_market_val) or pd.isna(last_invested):
                                # Recalculate from history_df to be safe
                                last_market_val = history_df["Market Value (USD)"].iloc[-1]
                                last_invested = history_df["Invested Capital (USD)"].iloc[-1]

                            total_gain = last_market_val - last_invested
                            total_gain_pct = (last_market_val / last_invested - 1) if last_invested > 0 else 0
                            
                            st.caption(f"Resultado histórico: **${total_gain:,.2f} ({total_gain_pct:+.2%})** con respecto a la inversión total.")
                        else:
                            st.info("No hay suficientes datos históricos para generar el gráfico.")
                        
                    except Exception as e:
                        st.error(f"Error al generar el gráfico: {e}")

                # --- NEW: Summary by Platform ---
                st.divider()
                st.subheader("📊 Resumen por Plataforma")
                
                # Use data_df which has the updated USD values
                # data_df was prepared around line 380-384
                if not data_df.empty:
                    platform_summary = data_df.groupby("Platform")["Updated Value (USD)"].sum().reset_index()
                    platform_summary.columns = ["Plataforma", "Valor en Dolares"]
                    
                    # Sort by value descending
                    platform_summary = platform_summary.sort_values(by="Valor en Dolares", ascending=False)
                    
                    # Add Total Row
                    total_val = platform_summary["Valor en Dolares"].sum()
                    total_row = pd.DataFrame([{"Plataforma": "TOTAL", "Valor en Dolares": total_val}])
                    platform_summary = pd.concat([platform_summary, total_row], ignore_index=True)

                    # Format for display
                    display_platform_summary = platform_summary.copy()
                    display_platform_summary["Valor en Dolares"] = display_platform_summary["Valor en Dolares"].apply(lambda x: f"${x:,.2f}")
                    
                    st.dataframe(
                        display_platform_summary,
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No hay datos suficientes para mostrar el resumen por plataforma.")

        else:
            st.info("No investments found. Go to 'New Entry' to add some.")

    elif choice == "Configuración":
        st.subheader("⚙️ Configuración")
        settings = db.load_settings()
        
        # 1. API Integration Settings
        st.markdown("### Integración de API")
        st.info("Las llaves de API ahora se gestionan a través de Streamlit Secrets por seguridad.")
        
        with st.expander("Cómo configurar las llaves de API"):
            st.markdown("""
            **Localmente:**
            Crea un archivo `.streamlit/secrets.toml` con:
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

        # 2. Platform Configuration
        st.markdown("### Configuración de Plataformas")
        st.markdown("Configura comisiones de entrada/salida y moneda por plataforma.")
        
        platforms_df = db.load_platforms()
        
        edited_platforms_df = st.data_editor(
            platforms_df,
            column_config={
                "Platform": st.column_config.TextColumn(required=True),
                "Entry Commission": st.column_config.NumberColumn(format="%.4f"),
                "Entry Type": st.column_config.SelectboxColumn(options=["Percentage", "Amount"]),
                "Exit Commission": st.column_config.NumberColumn(format="%.4f"),
                "Exit Type": st.column_config.SelectboxColumn(options=["Percentage", "Amount"]),
                "Commission Currency": st.column_config.SelectboxColumn(options=["USD", "BTC"])
            },
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="platform_editor"
        )
        
        if st.button("💾 Guardar Configuración de Plataformas"):
            db.save_platforms(edited_platforms_df)
            st.success("¡Configuración de plataformas guardada!")
            st.rerun()

        st.divider()

        # 3. Ticker Configuration
        st.markdown("### Configuración de Tickers")
        st.markdown("Selecciona de dónde obtener datos para cada activo o agrega nuevos.")
        
        df = db.load_data()
        current_config = settings.get("ticker_config", {})
        unique_from_data = df["Ticker"].unique().tolist() if not df.empty else []
        
        # Combine tickers from config and existing data
        all_tickers = sorted(list(set(list(current_config.keys()) + unique_from_data)))
        
        ticker_config_data = []
        for t in all_tickers:
            ticker_config_data.append({
                "Ticker": t,
                "Data Source": current_config.get(t, "Manual")
            })
        
        ticker_df = pd.DataFrame(ticker_config_data)
        
        edited_ticker_df = st.data_editor(
            ticker_df,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", required=True),
                "Data Source": st.column_config.SelectboxColumn(
                    "Origen de Datos",
                    options=["Manual", "Binance API", "Argentina (BYMA)", "Stock API"],
                    required=True
                )
            },
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="ticker_editor_v3"
        )
        
        if st.button("💾 Guardar Configuración de Tickers"):
            new_config = {}
            for _, row in edited_ticker_df.iterrows():
                ticker_str = str(row["Ticker"]).strip().upper()
                if ticker_str:
                    new_config[ticker_str] = row["Data Source"]
            
            settings["ticker_config"] = new_config
            db.save_settings(settings)
            st.success("¡Configuración de tickers guardada!")
            st.rerun()


if __name__ == "__main__":
    main()
