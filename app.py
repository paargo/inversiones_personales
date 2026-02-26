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
    
    col_mep, col_ccl, col_blue, col_crypto, col_btc = st.columns(5)
    
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

    col_blue.metric("Dólar Blue", f"${dolar_rates['Blue']:,.2f}")
    col_blue.markdown(metric_capsule(dolar_rates.get("variation", 0.0)), unsafe_allow_html=True)
    
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

    menu = ["Dashboard", "Ingresar Compra", "Detalle", "Ingresar Beneficios", "Configuración"]
    
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

    elif choice == "Ingresar Beneficios":
        st.subheader("Cargar Beneficios / Cobros")
        
        # Load tickers for selection
        settings = db.load_settings()
        ticker_config = settings.get("ticker_config", {})
        existing_tickers = sorted(list(ticker_config.keys()))
        
        # Load current data to suggest tickers from investments if settings is empty
        if not existing_tickers:
            df_inv = db.load_data()
            if not df_inv.empty:
                existing_tickers = sorted(df_inv["Ticker"].unique().tolist())
        
        ticker_options = existing_tickers + ["➕ Add New Ticker..."]
        
        selected_ticker_opt = st.selectbox("Ticker o Crypto de referencia", ticker_options)
        
        ticker = ""
        asset_type = "Acción ARG"
        if selected_ticker_opt == "➕ Add New Ticker...":
            ticker = st.text_input("Ingresar Nuevo Ticker/Crypto").upper()
        else:
            ticker = selected_ticker_opt
            ticker_info = ticker_config.get(ticker, {})
            if isinstance(ticker_info, dict):
                asset_type = ticker_info.get("type", "Acción ARG")
        
        # Load platforms where this ticker is held
        df_inv_all = db.load_data()
        ticker_platforms = df_inv_all[df_inv_all["Ticker"] == ticker]["Platform"].unique().tolist() if not df_inv_all.empty else []
        if not ticker_platforms:
             ticker_platforms = ["Manual"]

        with st.form("earnings_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.info(f"Activo: **{ticker if ticker else 'None'}** ({asset_type})")
                
                platform = st.selectbox("Plataforma", ticker_platforms)
                
                # Dynamic defaults based on asset type
                benefit_options = ["Dividendo", "Staking", "Interés ON", "Capital ON", "Interés Bono", "Capital Bono", "Rescate FCI"]
                default_benefit_idx = 0
                if asset_type == "Crypto":
                    default_benefit_idx = 1 # Staking
                elif asset_type == "Obligación Negociable":
                    default_benefit_idx = 2 # Interés ON
                elif asset_type == "Bono":
                    default_benefit_idx = 4 # Interés Bono
                elif asset_type == "Fondo Común de Inversión":
                    default_benefit_idx = 6 # Rescate FCI

                benefit_type = st.selectbox("Tipo de Beneficio", benefit_options, index=default_benefit_idx)
                
                currency_options = ["ARS", "USD MEP", "USD CCL", "Crypto"]
                default_curr_idx = 0
                if asset_type == "Crypto":
                    default_curr_idx = 3 # Crypto
                elif asset_type in ["CEDEAR", "Acción EEUU", "Obligación Negociable", "Fondo Común de Inversión"]:
                    default_curr_idx = 1 # USD MEP (Common for these in ARG, though FCI ARS exists too)

                currency = st.selectbox("Moneda", currency_options, index=default_curr_idx)
                date = st.date_input("Fecha", datetime.date.today())

            with col2:
                amount_input = st.text_input("Monto", value="0.0")
                cap_red_input = st.text_input("Monto que reduce del capital", value="0.0")
                
                amount = utils.safe_float(amount_input)
                cap_red = utils.safe_float(cap_red_input)
            
            submitted = st.form_submit_button("Guardar Beneficio")

            if submitted:
                if not ticker or amount < 0:
                    st.error("Por favor completa Ticker y Monto correctamente.")
                else:
                    new_earning = {
                        "Date": date,
                        "Ticker": ticker,
                        "Platform": platform,
                        "Type": benefit_type,
                        "Currency": currency,
                        "Amount": amount,
                        "Capital_Reduction": cap_red
                    }

                    df_earn = db.load_earnings()
                    df_earn = pd.concat([df_earn, pd.DataFrame([new_earning])], ignore_index=True)
                    db.save_earnings(df_earn)
                    st.success(f"Guardado: {amount} {currency} como {benefit_type} para {ticker} en {platform}")

    elif choice in ["Dashboard", "Detalle"]:
        df = db.load_data()
        df_earn = db.load_earnings()

        if not df.empty or not df_earn.empty:
            mep_rate = dolar_rates.get("MEP", 0.0)
            
            # --- 1. Calculations (Moved up for early metric display) ---
            def to_usd(row):
                if row["Currency"] == "ARS" and mep_rate > 0:
                    return row["Total_Cost"] / mep_rate
                return row["Total_Cost"]
            
            def earn_to_usd(row):
                if row["Currency"] == "ARS" and mep_rate > 0:
                    return row["Amount"] / mep_rate, row["Capital_Reduction"] / mep_rate
                return row["Amount"], row["Capital_Reduction"]

            if not df_earn.empty:
                df_earn[["Amount_USD", "Cap_Red_USD"]] = df_earn.apply(
                    lambda r: pd.Series(earn_to_usd(r)), axis=1
                )
            
            df["Total_Cost_USD"] = df.apply(to_usd, axis=1)
            grouped_inv = df.groupby(["Platform", "Ticker"])[["Quantity", "Total_Cost_USD"]].sum().reset_index()
            ticker_earnings = df_earn.groupby(["Platform", "Ticker"])[["Amount_USD", "Cap_Red_USD"]].sum().reset_index() if not df_earn.empty else pd.DataFrame(columns=["Platform", "Ticker", "Amount_USD", "Cap_Red_USD"])
            
            grouped_df = grouped_inv.copy()
            grouped_df = grouped_df.rename(columns={"Total_Cost_USD": "Total_Cost_Base"})
            grouped_df = pd.merge(grouped_df, ticker_earnings, on=["Platform", "Ticker"], how="left").fillna(0)
            grouped_df["Total_Cost"] = grouped_df["Total_Cost_Base"] - grouped_df["Cap_Red_USD"]

            settings = db.load_settings()
            ticker_config = settings.get("ticker_config", {})
            grouped_df["Avg Buy Price"] = grouped_df["Total_Cost"] / grouped_df["Quantity"]
            
            if "Current Price (USD)" not in st.session_state: st.session_state["Current Price (USD)"] = {}
            if "Native Price" not in st.session_state: st.session_state["Native Price"] = {}
            if "Prev Close Price (USD)" not in st.session_state: st.session_state["Prev Close Price (USD)"] = {}
            if "last_update_time" not in st.session_state: st.session_state["last_update_time"] = None

            # Map storage to DF
            grouped_df["Current Price (USD)"] = grouped_df["Ticker"].map(st.session_state["Current Price (USD)"]).fillna(0.0)
            grouped_df["Updated Value (USD)"] = (grouped_df["Quantity"] * grouped_df["Current Price (USD)"]) + grouped_df["Amount_USD"]
            grouped_df["Result ($)"] = grouped_df["Updated Value (USD)"] - grouped_df["Total_Cost_Base"]
            grouped_df["Result (%)"] = grouped_df.apply(
                lambda row: f"{(row['Updated Value (USD)'] / row['Total_Cost_Base'] - 1):+.2%}" if row["Total_Cost_Base"] > 0 else "0.00%", 
                axis=1
            )
            grouped_df["Prev Close (USD)"] = grouped_df["Ticker"].map(st.session_state.get("Prev Close Price (USD)", {})).fillna(0.0)
            grouped_df["Day Chg ($)"] = grouped_df["Quantity"] * (grouped_df["Current Price (USD)"] - grouped_df["Prev Close (USD)"])
            grouped_df["Day Chg (%)"] = grouped_df.apply(
                lambda row: (row["Day Chg ($)"] / (row["Quantity"] * row["Prev Close (USD)"])) if (row["Quantity"] * row["Prev Close (USD)"]) > 0 else 0.0,
                axis=1
            )

            total_val = grouped_df["Updated Value (USD)"].sum()
            total_res = grouped_df["Result ($)"].sum()
            total_res_pct = (total_val / grouped_df["Total_Cost_Base"].sum() - 1) if grouped_df["Total_Cost_Base"].sum() > 0 else 0
            day_chg_u = grouped_df["Day Chg ($)"].sum()
            total_prev = (grouped_df["Quantity"] * grouped_df["Prev Close (USD)"]).sum()
            day_chg_p = (day_chg_u / total_prev) if total_prev > 0 else 0.0

            # --- 2. Top UI: Metrics and Delta ---
            col_met, col_var = st.columns([3, 1])
            with col_met:
                st.metric("Valor Total de Cartera (USD)", f"${total_val:,.2f}", delta=f"${total_res:,.2f} ({total_res_pct:+.2%})")
            with col_var:
                color_v = "#28a745" if day_chg_u >= 0 else "#dc3545"
                sym_v = "▲" if day_chg_u >= 0 else "▼"
                st.markdown(f"""
                    <div style="background-color: {color_v}; color: white; padding: 10px 15px; border-radius: 20px; text-align: center; margin-top: 15px;">
                        <span style="font-weight: bold; font-size: 0.9em;">ACTUALIZACIÓN DIARIA</span><br>
                        <span style="font-size: 1.2em;">{sym_v} ${abs(day_chg_u):,.2f} ({day_chg_p:+.2%})</span>
                    </div>
                """, unsafe_allow_html=True)
            st.divider()

            # --- 3. Section Title & Update Button Row ---
            title_text = "Panel de Activos" if choice == "Dashboard" else "Detalle de Cartera"
            col_t, col_b = st.columns([3, 1])
            with col_t:
                st.subheader(title_text)
            with col_b:
                should_update = st.button("🔄 Actualizar Precios", use_container_width=True)

            # Auto-update logic
            st_autorefresh(interval=60 * 1000, key="price_update_refresh")
            if st.session_state["last_update_time"]:
                el = (datetime.datetime.now() - st.session_state["last_update_time"]).total_seconds() / 60
                if el >= PRICE_UPDATE_INTERVAL_MINUTES: should_update = True
            if not st.session_state.get("prices_updated", False) and not grouped_df.empty: should_update = True

            if should_update:
                with st.spinner("Obteniendo precios..."):
                    for idx, row in grouped_df.iterrows():
                        tic = row["Ticker"]
                        inf = ticker_config.get(tic, {})
                        src = inf.get("source", "Manual") if isinstance(inf, dict) else inf
                        if src != "Manual":
                            p, cur, prev = md.get_market_price(tic, src)
                            if p > 0:
                                st.session_state["Native Price"][tic] = {"price": p, "currency": cur}
                                p_u = p if cur in ["USD", "USDT"] else (p / mep_rate if mep_rate > 0 else 0)
                                st.session_state["Current Price (USD)"][tic] = p_u
                                prev_u = prev if cur in ["USD", "USDT"] else (prev / mep_rate if mep_rate > 0 else 0)
                                st.session_state["Prev Close Price (USD)"][tic] = prev_u
                    st.session_state["prices_updated"] = True
                    st.session_state["last_update_time"] = datetime.datetime.now()
                    st.rerun()

            # --- 4. Main Content Rendering ---
            if choice == "Dashboard":
                edit_cols = ["Platform", "Ticker", "Quantity", "Total_Cost", "Avg Buy Price", "Current Price (USD)", "Updated Value (USD)", "Day Chg ($)", "Day Chg (%)", "Result ($)", "Result (%)"]
                total_row_ed = pd.DataFrame([{
                    "Platform": "TOTAL", "Ticker": "", "Quantity": "", 
                    "Total_Cost": f"{grouped_df['Total_Cost'].sum():,.2f}", "Avg Buy Price": "",
                    "Current Price (USD)": "", "Updated Value (USD)": f"{total_val:,.2f}",
                    "Day Chg ($)": f"{day_chg_u:+,.2f}", "Day Chg (%)": f"{day_chg_p:+.2%}",
                    "Result ($)": f"{total_res:+,.2f}", "Result (%)": f"{total_res_pct:+.2%}"
                }])
                df_ed = grouped_df[edit_cols].copy()
                for c in ["Quantity", "Total_Cost", "Avg Buy Price", "Updated Value (USD)", "Day Chg ($)", "Result ($)"]:
                    df_ed[c] = df_ed[c].apply(lambda x: f"{x:,.6f}" if "Quantity" in c else f"{x:+,.2f}" if "Chg" in c or "Result" in c else f"{x:,.2f}")
                df_ed["Day Chg (%)"] = df_ed["Day Chg (%)"].apply(lambda x: f"{x:+.2%}")
                df_ed = pd.concat([df_ed, total_row_ed], ignore_index=True)

                edited_df = st.data_editor(df_ed, column_config={
                    "Platform": st.column_config.TextColumn("Plataforma", disabled=True),
                    "Current Price (USD)": st.column_config.TextColumn("Precio Actual (USD)"),
                    "Quantity": st.column_config.TextColumn("Cantidad", disabled=True),
                    "Total_Cost": st.column_config.TextColumn("Costo Base", disabled=True),
                    "Result (%)": st.column_config.TextColumn("Resultado (%)", disabled=True)
                }, hide_index=True, use_container_width=True)

                if not edited_df.empty:
                    sync = False
                    for idx, r in edited_df.iterrows():
                        if r["Platform"] == "TOTAL": continue
                        t = r["Ticker"]
                        np = utils.safe_float(str(r["Current Price (USD)"]))
                        if st.session_state["Current Price (USD)"].get(t) != np:
                            st.session_state["Current Price (USD)"][t] = np
                            sync = True
                    if sync: st.rerun()

            elif choice == "Detalle":
                # Detailed breakdown table
                b_df = df.copy()
                b_df["Type"] = "Compra"
                b_df["Current Price (USD)"] = b_df["Ticker"].map(st.session_state["Current Price (USD)"]).fillna(0.0)
                b_df["Updated Value (USD)"] = b_df["Quantity"] * b_df["Current Price (USD)"]
                b_df["Result ($)"] = b_df["Updated Value (USD)"] - b_df["Total_Cost_USD"]
                b_df["Result (%)"] = b_df.apply(lambda r: (r["Updated Value (USD)"] / r["Total_Cost_USD"] - 1) if r["Total_Cost_USD"] > 0 else 0.0, axis=1)
                
                disp_c = ["Date", "Platform", "Ticker", "Type", "Quantity", "Price", "Currency", "Total_Cost_USD", "Current Price (USD)", "Updated Value (USD)", "Result ($)", "Result (%)"]
                if not df_earn.empty:
                    e_d = df_earn.copy()
                    e_d["Quantity"], e_d["Price"], e_d["Current Price (USD)"], e_d["Result (%)"] = 0.0, 0.0, 0.0, 0.0
                    e_d["Total_Cost_USD"] = -e_d["Cap_Red_USD"]
                    e_d["Updated Value (USD)"] = e_d["Amount_USD"]
                    e_d["Result ($)"] = e_d["Amount_USD"]
                    b_df = pd.concat([b_df, e_d[disp_c]], ignore_index=True)
                
                d_df = b_df[disp_c].copy()
                d_df["Date"] = pd.to_datetime(d_df["Date"]).dt.date
                for c in ["Total_Cost_USD", "Updated Value (USD)", "Result ($)"]:
                    d_df[c] = d_df[c].apply(lambda x: f"{x:+,.2f}" if "Result ($)" in c else f"{x:,.2f}")
                d_df["Result (%)"] = d_df["Result (%)"].apply(lambda x: f"{x:+.2%}")
                
                tr = pd.DataFrame([{"Date": "TOTAL", "Platform": "", "Ticker": "", "Quantity": "", "Price": "", "Currency": "",
                                    "Total_Cost_USD": f"{grouped_df['Total_Cost'].sum():,.2f}", "Current Price (USD)": "",
                                    "Updated Value (USD)": f"{total_val:,.2f}", "Result ($)": f"{total_res:+,.2f}",
                                    "Result (%)": f"{total_res_pct:+.2%}"}])
                st.dataframe(pd.concat([d_df, tr], ignore_index=True), use_container_width=True, hide_index=True)

                # Charts
                st.divider()
                st.subheader("📈 Evolución de Cartera")
                try:
                    df["Date"] = pd.to_datetime(df["Date"])
                    min_d = df["Date"].min()
                    dr = pd.date_range(start=min_d, end=datetime.date.today(), freq="D")
                    hp = md.get_historical_prices({t: ticker_config.get(t, {}).get("source", "Manual") for t in df["Ticker"].unique()}, min_d)
                    cd = []
                    for d in dr:
                        m = df["Date"] <= d
                        cf = df[m]
                        if cf.empty: continue
                        ic = cf["Total_Cost_USD"].sum()
                        re, cr = 0.0, 0.0
                        if not df_earn.empty:
                            me = pd.to_datetime(df_earn["Date"]) <= d
                            re, cr = df_earn[me]["Amount_USD"].sum(), df_earn[me]["Cap_Red_USD"].sum()
                        mv = re
                        for t, q in cf.groupby("Ticker")["Quantity"].sum().items():
                            if t in hp.columns:
                                ph = hp[t].loc[:d]
                                p = ph.iloc[-1] if not ph.empty else 0
                                mv += q * (p if not pd.isna(p) else 0)
                            else: mv += q * st.session_state["Current Price (USD)"].get(t, 0)
                        cd.append({"Date": d, "Invested Capital (USD)": ic - cr, "Market Value (USD)": mv})
                    if cd:
                        st.line_chart(pd.DataFrame(cd).set_index("Date"))
                except Exception as e: st.error(f"Error gráfico: {e}")

                # Summary by Platform
                st.divider()
                st.subheader("📊 Resumen por Plataforma")
                ps = grouped_df.groupby("Platform")["Updated Value (USD)"].sum().reset_index()
                ps.columns = ["Plataforma", "Valor en Dolares"]
                ps = ps.sort_values(by="Valor en Dolares", ascending=False)
                t_ps = pd.DataFrame([{"Plataforma": "TOTAL", "Valor en Dolares": ps["Valor en Dolares"].sum()}])
                ps_f = pd.concat([ps, t_ps], ignore_index=True)
                ps_f["Valor en Dolares"] = ps_f["Valor en Dolares"].apply(lambda x: f"${x:,.2f}")
                st.dataframe(ps_f, use_container_width=True, hide_index=True)

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
            info = current_config.get(t, {})
            if isinstance(info, dict):
                ticker_config_data.append({
                    "Ticker": t,
                    "Data Source": info.get("source", "Manual"),
                    "Type": info.get("type", "Acción ARG")
                })
            else:
                ticker_config_data.append({
                    "Ticker": t,
                    "Data Source": info,
                    "Type": "Acción ARG"
                })
        
        ticker_df = pd.DataFrame(ticker_config_data)
        
        asset_types = ["Crypto", "Acción ARG", "Cedear", "Acción EEUU", "Obligación Negociable", "Bono", "Fondo Común de Inversión"]
        
        edited_ticker_df = st.data_editor(
            ticker_df,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", required=True),
                "Data Source": st.column_config.SelectboxColumn(
                    "Origen de Datos",
                    options=["Manual", "Binance API", "Argentina (BYMA)", "Stock API"],
                    required=True
                ),
                "Type": st.column_config.SelectboxColumn(
                    "Tipo de Activo",
                    options=asset_types,
                    required=True
                )
            },
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="ticker_editor_v4"
        )
        
        if st.button("💾 Guardar Configuración de Tickers"):
            new_config = {}
            for _, row in edited_ticker_df.iterrows():
                ticker_str = str(row["Ticker"]).strip().upper()
                if ticker_str:
                    new_config[ticker_str] = {
                        "source": row["Data Source"],
                        "type": row["Type"]
                    }
            
            settings["ticker_config"] = new_config
            db.save_settings(settings)
            st.success("¡Configuración de tickers guardada!")
            st.rerun()


if __name__ == "__main__":
    main()
