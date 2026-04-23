import streamlit as st
import pandas as pd
import datetime
import os
from streamlit_autorefresh import st_autorefresh

# Custom Modules
import utils
import database as db
import market_data as md
from analysis_models import AnalyzedTicker, IndicatorConfig
from indicator_engine import (
    IndicatorEngine,
    IndicatorRepository,
    IndicatorEngineError,
    MissingIndicatorConfigError,
    NoHistoricalDataError,
)
from market_history_service import (
    HistoricalMarketDataService,
    MockMarketDataProvider,
    YFinanceMarketDataProvider,
    SqliteMarketHistoryRepository,
    OHLCBar,
)

# Configuration constants
PRICE_UPDATE_INTERVAL_MINUTES = 30


@st.cache_resource
def get_history_service():
    repository = SqliteMarketHistoryRepository("market_history.sqlite")
    try:
        provider = YFinanceMarketDataProvider()
    except Exception as e:
        st.warning(f"No se pudo inicializar el provider real, usando mock: {e}")
        provider = MockMarketDataProvider()

    return HistoricalMarketDataService(provider=provider, repository=repository)


@st.cache_resource
def get_indicator_engine():
    history_service = get_history_service()
    repository = IndicatorRepository("market_history.sqlite")
    return IndicatorEngine(repository=repository, history_service=history_service)


def bars_to_df(bars):
    if not bars:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    normalized = []
    for bar in bars:
        if hasattr(bar, "to_row"):
            normalized.append(bar.to_row())
        elif isinstance(bar, dict):
            normalized.append(bar)
        else:
            normalized.append({
                "timestamp": getattr(bar, "timestamp", None),
                "open": getattr(bar, "open", None),
                "high": getattr(bar, "high", None),
                "low": getattr(bar, "low", None),
                "close": getattr(bar, "close", None),
                "volume": getattr(bar, "volume", None),
            })

    df = pd.DataFrame(normalized)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def run_history_auto_sync(settings):
    """Run once per day when enabled, catching up any missed OHLC days."""
    if not settings.get("ohlc_auto_update_enabled", False):
        return

    today = datetime.date.today()
    last_check_key = "ohlc_auto_sync_checked_for"
    if st.session_state.get(last_check_key) == str(today):
        return

    st.session_state[last_check_key] = str(today)

    last_update = _parse_iso_datetime(settings.get("ohlc_last_update"))
    if last_update and last_update.date() >= today:
        return

    service = get_history_service()
    with st.spinner("Actualizando historicos OHLC automaticamente..."):
        try:
            result = service.sync_all_missing(end_date=today)
            settings["ohlc_last_update"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            settings["ohlc_last_status"] = (
                f"updated_tickers={result['updated_tickers']}; saved_bars={result['saved_bars']}; failed_tickers={result['failed_tickers']}"
            )
            db.save_settings(settings)
            st.session_state["ohlc_last_auto_sync_result"] = result
            if result["failed_tickers"] > 0:
                st.warning(
                    f"Actualizacion automatica parcial: {result['updated_tickers']} tickers, {result['saved_bars']} velas, {result['failed_tickers']} fallos."
                )
                if result["errors"]:
                    st.caption(" | ".join(result["errors"]))
            else:
                st.success(
                    f"Actualizacion automatica completada: {result['updated_tickers']} tickers, {result['saved_bars']} velas."
                )
        except Exception as e:
            settings["ohlc_last_status"] = f"error={e}"
            db.save_settings(settings)
            st.session_state["ohlc_last_auto_sync_error"] = str(e)
            st.error(f"No se pudo ejecutar la actualizacion automatica: {e}")

def main():
    st.set_page_config(page_title="Control de Inversiones", layout="wide")
    st.title("💰 Control de Inversiones")
    settings = db.load_settings()
    run_history_auto_sync(settings)

    # 1. Global Market Header (Visible on all pages)
    dolar_rates = md.get_dolar_rates()
    # Fetch BTC price for the header
    btc_price, _, btc_prev_close = md.get_market_price("BTC", "Binance API")
    
    col_mep, col_blue, col_crypto, col_btc = st.columns(4)
    
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

    col_blue.metric("Dólar Blue", f"${dolar_rates['Blue']:,.2f}")
    col_blue.markdown(metric_capsule(dolar_rates.get("variation", 0.0)), unsafe_allow_html=True)
    
    col_crypto.metric("Dólar Cripto", f"${dolar_rates['Cripto']:,.2f}")
    col_crypto.markdown(metric_capsule(dolar_rates.get("variation", 0.0)), unsafe_allow_html=True)
    
    col_btc.metric("Precio BTC", f"${btc_price:,.2f}" if btc_price > 0 else "-")
    if btc_price > 0 and btc_prev_close > 0:
        btc_var = (btc_price / btc_prev_close - 1)
        col_btc.markdown(metric_capsule(btc_var), unsafe_allow_html=True)
    
    st.caption("ℹ️ Los valores de Dólar (MEP, Blue) se actualizan automáticamente de Lunes a Viernes entre las 9:00 y 18:00 hs.")
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

    menu = ["Dashboard", "Detalle", "Ingresar Compra", "Ingresar Beneficios", "Consulta OHLC", "Indicadores", "Configuración"]
    
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
                delta_str = f"{'+$' if total_res >= 0 else '-$'}{abs(total_res):,.2f} ({total_res_pct:+.2%})"
                st.metric("Valor Total de Cartera (USD)", f"${total_val:,.2f}", delta=delta_str)
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
            settings = db.load_settings()
            auto_update_enabled = settings.get("auto_update_enabled", True)
            
            if auto_update_enabled:
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
                edit_cols = ["Ticker", "Result ($)", "Result (%)", "Day Chg (%)", "Quantity", "Total_Cost", "Avg Buy Price", "Current Price (USD)", "Updated Value (USD)"]
                total_row_ed = pd.DataFrame([{
                    "Ticker": "TOTAL", "Result ($)": f"{total_res:+,.2f}", "Result (%)": f"{total_res_pct:+.2%}", "Day Chg (%)": f"{day_chg_p:+.2%}",
                    "Quantity": "", "Total_Cost": f"{grouped_df['Total_Cost'].sum():,.2f}", 
                    "Avg Buy Price": "", "Current Price (USD)": "", 
                    "Updated Value (USD)": f"{total_val:,.2f}"
                }])
                df_ed = grouped_df[edit_cols].copy()
                for c in ["Quantity", "Total_Cost", "Avg Buy Price", "Updated Value (USD)", "Result ($)"]:
                    df_ed[c] = df_ed[c].apply(lambda x: f"{x:,.6f}" if "Quantity" in c else f"{x:+,.2f}" if "Chg" in c or "Result" in c else f"{x:,.2f}")
                df_ed["Day Chg (%)"] = df_ed["Day Chg (%)"].apply(lambda x: f"{x:+.2%}")
                df_ed = pd.concat([df_ed, total_row_ed], ignore_index=True)

                edited_df = st.data_editor(df_ed, column_config={
                    "Current Price (USD)": st.column_config.TextColumn("Precio Actual (USD)"),
                    "Quantity": st.column_config.TextColumn("Cantidad", disabled=True),
                    "Total_Cost": st.column_config.TextColumn("Costo Base", disabled=True),
                    "Result (%)": st.column_config.TextColumn("Resultado (%)", disabled=True)
                }, hide_index=True, use_container_width=True)

                if not edited_df.empty:
                    sync = False
                    for idx, r in edited_df.iterrows():
                        if r["Ticker"] == "TOTAL": continue
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
                    
                    cpi_series = None
                    fred_key = settings.get("fred_api_key")
                    if fred_key:
                        cpi_raw = md.get_us_cpi(fred_key)
                        if not cpi_raw:
                            st.warning("⚠️ No se pudieron obtener los datos de la API de FRED (posible API Key inválida o límite de peticiones).")
                        else:
                            cpi_series = pd.Series(cpi_raw)
                            cpi_series.index = pd.to_datetime(cpi_series.index)
                            cpi_series = cpi_series.sort_index()

                    cd = []
                    for d in dr:
                        is_today = d.date() == datetime.date.today()
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
                            # For today, prioritize real-time prices from session_state
                            if is_today and t in st.session_state.get("Current Price (USD)", {}):
                                p = st.session_state["Current Price (USD)"][t]
                                mv += q * p
                            elif t in hp.columns:
                                ph = hp[t].loc[:d]
                                p = ph.iloc[-1] if not ph.empty else 0
                                # Fallback to session_state if historical is NaN for today
                                if pd.isna(p) and is_today:
                                    p = st.session_state.get("Current Price (USD)", {}).get(t, 0)
                                mv += q * (p if not pd.isna(p) else 0)
                            else: 
                                mv += q * st.session_state["Current Price (USD)"].get(t, 0)
                        cd_item = {"Date": d, "Invested Capital (USD)": ic - cr, "Market Value (USD)": mv}
                        
                        if cpi_series is not None and not cpi_series.empty:
                            try:
                                d_cpi_slice = cpi_series.loc[:d]
                                if not d_cpi_slice.empty:
                                    current_cpi = d_cpi_slice.iloc[-1]
                                    adj_ic = 0.0
                                    
                                    for _, row in cf.iterrows():
                                        inv_d = row["Date"]
                                        inv_cpi_slice = cpi_series.loc[:inv_d]
                                        inv_cpi = inv_cpi_slice.iloc[-1] if not inv_cpi_slice.empty else current_cpi
                                        adj_ic += row["Total_Cost_USD"] * (current_cpi / inv_cpi)
                                        
                                    adj_cr = 0.0
                                    if not df_earn.empty:
                                        eff_earn = df_earn[pd.to_datetime(df_earn["Date"]) <= d]
                                        for _, erow in eff_earn.iterrows():
                                            e_d = erow["Date"]
                                            e_cpi_slice = cpi_series.loc[:pd.to_datetime(e_d)]
                                            e_cpi = e_cpi_slice.iloc[-1] if not e_cpi_slice.empty else current_cpi
                                            adj_cr += erow["Cap_Red_USD"] * (current_cpi / e_cpi)

                                    cd_item["Capital Ajustado (Inflación EEUU)"] = adj_ic - adj_cr
                            except Exception as cpi_e:
                                print(f"Error procesando CPI para {d}: {cpi_e}")
                                
                        cd.append(cd_item)
                    
                    if cd:
                        chart_df = pd.DataFrame(cd).set_index("Date")
                        chart_df = chart_df.rename(columns={
                            "Invested Capital (USD)": "Capital Invertido Nominal",
                            "Market Value (USD)": "Valor de Mercado"
                        })
                        st.line_chart(chart_df)
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

    elif choice == "Consulta OHLC":
        st.subheader("Consulta de historicos OHLC")
        st.caption("Investiga datos reales si el provider responde, consulta lo guardado y persiste la informacion en la base local.")

        service = get_history_service()
        provider_name = service.provider.__class__.__name__
        st.info(f"Fuente activa: {provider_name}")
        catalog = service.repository.list_tickers()
        catalog_options = ["Nuevo ticker..."] + [
            f"{row['symbol']} | {row['market']} | {row['timeframe']} ({row['asset_type']})"
            for row in catalog
        ]

        selected_option = st.selectbox("Ticker disponible", catalog_options)

        default_symbol = ""
        default_market = "NYSE"
        default_asset_type = "stock"
        default_timeframe = "1D"
        selected_row = None

        if selected_option != "Nuevo ticker...":
            selected_row = next(
                row for row in catalog
                if f"{row['symbol']} | {row['market']} | {row['timeframe']} ({row['asset_type']})" == selected_option
            )
            default_symbol = selected_row["symbol"]
            default_market = selected_row["market"]
            default_asset_type = selected_row["asset_type"]
            default_timeframe = selected_row["timeframe"]

        col_a, col_b = st.columns(2)
        with col_a:
            symbol = st.text_input("Symbol", value=default_symbol).strip().upper()
            market_options = ["NYSE", "NASDAQ", "BYMA", "NASDAQGS", "CRYPTO"]
            market = st.selectbox(
                "Market",
                market_options,
                index=market_options.index(default_market) if default_market in market_options else 0,
            )
            asset_type_options = ["stock", "cedear", "bond", "etf", "on"]
            asset_type = st.selectbox(
                "Asset type",
                asset_type_options,
                index=asset_type_options.index(default_asset_type) if default_asset_type in asset_type_options else 0,
            )

        with col_b:
            timeframe_options = ["1D", "1W", "1M"]
            timeframe = st.selectbox(
                "Timeframe",
                timeframe_options,
                index=timeframe_options.index(default_timeframe) if default_timeframe in timeframe_options else 0,
            )
            start_date = st.date_input("Start date", datetime.date.today() - datetime.timedelta(days=30))
            end_date = st.date_input("End date", datetime.date.today())

        ticker_valid = bool(symbol and market)
        ticker_obj = None
        if ticker_valid:
            try:
                selected_id = None
                if selected_row and (
                    symbol == selected_row["symbol"]
                    and market == selected_row["market"]
                    and timeframe == selected_row["timeframe"]
                    and asset_type == selected_row["asset_type"]
                ):
                    selected_id = selected_row["id"]

                ticker_obj = AnalyzedTicker(
                    symbol=symbol,
                    market=market,
                    asset_type=asset_type,
                    timeframe=timeframe,
                    is_active=True,
                    id=selected_id,
                )
            except Exception as e:
                st.error(f"Ticker invalido: {e}")

        c1, c2, c3 = st.columns(3)
        do_investigate = c1.button("Investigar", use_container_width=True, disabled=not ticker_valid)
        do_consult = c2.button("Consultar la base", use_container_width=True, disabled=not ticker_valid)
        do_save = c3.button("Guardar informacion en la base de consulta", use_container_width=True, disabled=not ticker_valid)

        if timeframe != "1D":
            st.warning("Por ahora el provider mock y la persistencia trabajan con timeframe diario (1D).")

        if ticker_obj and do_investigate:
            with st.spinner("Obteniendo datos desde el provider..."):
                try:
                    bars = service.investigate(ticker_obj, start_date=start_date, end_date=end_date)
                    st.session_state["ohlc_last_fetch"] = {
                        "ticker": ticker_obj.to_row(),
                        "bars": [bar.to_row() for bar in bars],
                        "source": provider_name,
                        "mode": "investigate",
                    }
                    st.success(f"Se obtuvieron {len(bars)} velas.")
                except Exception as e:
                    st.error(f"No se pudieron obtener los datos: {e}")

        if ticker_obj and do_consult:
            try:
                bars = service.load_registered(symbol, market, timeframe)
                st.session_state["ohlc_last_fetch"] = {
                    "ticker": ticker_obj.to_row(),
                    "bars": [bar.to_row() for bar in bars],
                    "source": "SQLite",
                    "mode": "database",
                }
                st.success(f"Se encontraron {len(bars)} velas registradas.")
            except Exception as e:
                st.error(f"No se pudo consultar la base: {e}")

        if ticker_obj and do_save:
            payload = st.session_state.get("ohlc_last_fetch", {})
            bars_payload = payload.get("bars", [])
            if not bars_payload:
                st.warning("Primero ejecuta 'Investigar' para cargar datos antes de guardar.")
            else:
                try:
                    bars = [
                        OHLCBar(
                            timestamp=pd.to_datetime(row["timestamp"]).to_pydatetime(),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]),
                        )
                        for row in bars_payload
                    ]
                    saved = service.save_ticker_bars(ticker_obj, bars)
                    st.success(f"Se guardaron {saved} velas en la base de consulta.")
                except Exception as e:
                    st.error(f"No se pudo guardar la informacion: {e}")

        if st.session_state.get("ohlc_last_fetch"):
            st.divider()
            fetch_meta = st.session_state["ohlc_last_fetch"]
            st.caption(f"Ultima fuente mostrada: {fetch_meta.get('source', 'desconocida')}")
            last_df = bars_to_df(fetch_meta["bars"])
            st.markdown("### Ultimo resultado")
            if not last_df.empty:
                st.dataframe(last_df, use_container_width=True, hide_index=True)
            else:
                st.info("No hay datos para mostrar.")

    elif choice == "Indicadores":
        st.subheader("Engine de Indicadores")
        st.caption("Selecciona un ticker, guarda su configuracion de EMAs y calcula los indicadores sobre su serie historica.")

        engine = get_indicator_engine()
        catalog = engine.repository.list_tickers()
        if not catalog:
            st.info("No hay tickers registrados todavia. Carga primero un historico desde 'Consulta OHLC'.")
            st.stop()

        catalog_options = [
            f"{row['symbol']} | {row['market']} | {row['timeframe']} ({row['asset_type']})"
            for row in catalog
        ]
        selected_option = st.selectbox("Ticker disponible", catalog_options)
        selected_row = next(
            row for row in catalog
            if f"{row['symbol']} | {row['market']} | {row['timeframe']} ({row['asset_type']})" == selected_option
        )

        ticker_obj = AnalyzedTicker(
            id=selected_row["id"],
            symbol=selected_row["symbol"],
            market=selected_row["market"],
            asset_type=selected_row["asset_type"],
            timeframe=selected_row["timeframe"],
            is_active=bool(selected_row["is_active"]),
        )

        current_config = engine.repository.get_indicator_config(selected_row["id"])
        default_periods = current_config.ema_periods if current_config else [10, 20, 100]
        default_rsi = current_config.enable_rsi if current_config else False
        default_macd = current_config.enable_macd if current_config else False

        left, right = st.columns(2)
        with left:
            st.markdown("### Configuracion")
            periods_raw = st.text_input(
                "EMA periods separados por coma",
                value=", ".join(str(p) for p in default_periods),
                help="Ejemplo: 10, 20, 100",
            )
            enable_rsi = st.toggle("Habilitar RSI", value=default_rsi)
            enable_macd = st.toggle("Habilitar MACD", value=default_macd)

        with right:
            st.markdown("### Ticker seleccionado")
            st.write(
                {
                    "symbol": ticker_obj.symbol,
                    "market": ticker_obj.market,
                    "asset_type": ticker_obj.asset_type,
                    "timeframe": ticker_obj.timeframe,
                    "ticker_id": ticker_obj.id,
                }
            )
            if current_config:
                st.caption(f"Config actual detectada: EMA {current_config.ema_periods}")
            else:
                st.caption("No hay configuracion guardada para este ticker.")

        def parse_periods(raw):
            items = [part.strip() for part in raw.split(",") if part.strip()]
            periods = [int(item) for item in items]
            if not periods:
                raise ValueError("Debes ingresar al menos un periodo EMA.")
            if len(set(periods)) != len(periods):
                raise ValueError("Los periodos EMA no pueden repetirse.")
            if periods != sorted(periods):
                raise ValueError("Los periodos EMA deben estar ordenados de menor a mayor.")
            return periods

        col_save, col_run = st.columns(2)
        with col_save:
            if st.button("Guardar configuracion de indicadores", use_container_width=True):
                try:
                    periods = parse_periods(periods_raw)
                    existing_config = engine.repository.get_indicator_config(ticker_obj.id)
                    config = IndicatorConfig(
                        id=existing_config.id if existing_config else None,
                        ticker_id=ticker_obj.id,
                        ema_periods=periods,
                        enable_rsi=enable_rsi,
                        enable_macd=enable_macd,
                    )
                    engine.repository.save_indicator_config(config)
                    st.success("Configuracion de indicadores guardada.")
                except Exception as e:
                    st.error(f"No se pudo guardar la configuracion: {e}")

        with col_run:
            run_now = st.button("Calcular indicadores", use_container_width=True)

        if run_now:
            try:
                periods = parse_periods(periods_raw)
                existing_config = engine.repository.get_indicator_config(ticker_obj.id)
                config = IndicatorConfig(
                    id=existing_config.id if existing_config else None,
                    ticker_id=ticker_obj.id,
                    ema_periods=periods,
                    enable_rsi=enable_rsi,
                    enable_macd=enable_macd,
                )
                engine.repository.save_indicator_config(config)
                result = engine.generate(ticker_obj)
                st.session_state["indicator_last_result"] = result
                st.success("Indicadores calculados correctamente.")
            except MissingIndicatorConfigError as e:
                st.error(str(e))
            except NoHistoricalDataError as e:
                st.error(str(e))
            except IndicatorEngineError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Error inesperado al calcular indicadores: {e}")

        result = st.session_state.get("indicator_last_result")
        if result:
            st.divider()
            st.markdown("### Resultado")
            st.json(result)

            bars = engine.repository.load_bars_by_identity(
                ticker_obj.symbol, ticker_obj.market, ticker_obj.timeframe
            )
            if bars:
                df_prices = bars_to_df(bars)
                df_prices = df_prices.rename(columns={"close": "close"})
                chart_df = pd.DataFrame({"timestamp": df_prices["timestamp"], "close": df_prices["close"]})
                for key, values in result["indicators"].items():
                    chart_df[key] = values

                chart_df = chart_df.set_index("timestamp")
                st.markdown("### Precio y EMAs")
                st.line_chart(chart_df)

    elif choice == "Configuración":
        st.subheader("⚙️ Configuración")
        settings = db.load_settings()
        
        # 0. Ajustes Generales
        st.markdown("### Ajustes Generales")
        
        current_auto_update = settings.get("auto_update_enabled", True)
        new_auto_update = st.toggle("Habilitar actualización automática de precios", value=current_auto_update)
        
        if new_auto_update != current_auto_update:
            settings["auto_update_enabled"] = new_auto_update
            db.save_settings(settings)
            st.success("Preferencia de actualización guardada.")
            st.rerun()

        current_ohlc_auto = settings.get("ohlc_auto_update_enabled", False)
        new_ohlc_auto = st.toggle("Habilitar actualización automática de OHLC", value=current_ohlc_auto)

        last_ohlc_update = settings.get("ohlc_last_update", "")
        last_ohlc_status = settings.get("ohlc_last_status", "")

        st.text_input(
            "Última actualización OHLC",
            value=last_ohlc_update if last_ohlc_update else "Sin actualizaciones aún",
            disabled=True,
        )
        if last_ohlc_status:
            st.caption(f"Último estado: {last_ohlc_status}")

        if new_ohlc_auto != current_ohlc_auto:
            settings["ohlc_auto_update_enabled"] = new_ohlc_auto
            db.save_settings(settings)
            st.success("Preferencia de actualización OHLC guardada.")
            st.rerun()

        if st.button("Actualizar OHLC ahora"):
            service = get_history_service()
            try:
                result = service.sync_all_missing(end_date=datetime.date.today())
                settings["ohlc_last_update"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                settings["ohlc_last_status"] = (
                    f"updated_tickers={result['updated_tickers']}; saved_bars={result['saved_bars']}; failed_tickers={result['failed_tickers']}"
                )
                db.save_settings(settings)
                if result["failed_tickers"] > 0:
                    st.warning(
                        f"Actualización OHLC parcial: {result['updated_tickers']} tickers, {result['saved_bars']} velas, {result['failed_tickers']} fallos."
                    )
                    if result["errors"]:
                        st.caption(" | ".join(result["errors"]))
                else:
                    st.success(
                        f"Actualización OHLC completada: {result['updated_tickers']} tickers, {result['saved_bars']} velas."
                    )
                st.rerun()
            except Exception as e:
                settings["ohlc_last_status"] = f"error={e}"
                db.save_settings(settings)
                st.error(f"No se pudo ejecutar la actualización OHLC: {e}")

        st.divider()
        
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
        
        st.markdown("#### Inflación de Estados Unidos (FRED)")
        st.info("Obtén tu API key gratis en: https://fred.stlouisfed.org/docs/api/api_key.html")
        fred_key = st.text_input("FRED API Key", value=settings.get("fred_api_key", ""), type="password")
        if st.button("Guardar FRED Key"):
            settings["fred_api_key"] = fred_key
            db.save_settings(settings)
            st.success("¡FRED API Key guardada exitosamente!")


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
