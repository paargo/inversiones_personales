import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import streamlit as st
import utils

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def get_db_connection():
    """Connect to Google Sheets using st.secrets or local credentials.json"""
    try:
        # Check if running on Streamlit Cloud (or if secrets are set locally in .streamlit/secrets.toml)
        creds_dict = utils.get_secret("gcp_service_account")
        if creds_dict:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        else:
            # Fallback to local file for development
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
        
        client = gspread.authorize(creds)
        
        # Open the spreadsheet (assumes user named it "Investment Tracker Data")
        # You can also config the sheet name in secrets
        sheet_name = utils.get_secret("sheet_name") or "Investment Tracker Data"
            
        sh = client.open(sheet_name)
        return sh
    except Exception as e:
        st.error(f"Error de conexión a la base de datos: {e}")
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
                "Currency", "Commission", "Commission_Type", "Commission_Currency", "Total_Cost"
            ])

        # Platforms Sheet
        try:
            ws_platforms = sh.worksheet("Platforms")
        except gspread.WorksheetNotFound:
            ws_platforms = sh.add_worksheet(title="Platforms", rows=100, cols=10)
            ws_platforms.append_row([
                "Platform", "Entry Commission", "Entry Type", 
                "Exit Commission", "Exit Type", "Commission Currency"
            ])
            # Add some defaults
            ws_platforms.append_rows([
                ["Binance", 0.1, "Percentage", 0.1, "Percentage", "BTC"],
                ["Interactive Brokers", 1.0, "Amount", 1.0, "Amount", "USD"],
                ["Coinbase", 0.5, "Percentage", 0.5, "Percentage", "USD"]
            ])

        # Settings Sheet (Ticker Config)
        try:
            ws_settings = sh.worksheet("Settings")
            # Upgrade check: ensure "Type" column exists
            headers = ws_settings.row_values(1)
            if "Type" not in headers:
                ws_settings.update_cell(1, 3, "Type")
        except gspread.WorksheetNotFound:
            ws_settings = sh.add_worksheet(title="Settings", rows=100, cols=5)
            ws_settings.append_row(["Ticker", "Data Source", "Type"])

        # Earnings Sheet
        try:
            ws_earn = sh.worksheet("Earnings")
        except gspread.WorksheetNotFound:
            ws_earn = sh.add_worksheet(title="Earnings", rows=1000, cols=10)
            ws_earn.append_row([
                "Date", "Ticker", "Type", "Currency", "Amount", "Capital_Reduction"
            ])

        return ws_inv, ws_settings
    except Exception as e:
        st.error(f"Error de inicialización de hojas: {e}")
        st.stop()

def load_data():
    sh = get_db_connection()
    ws_inv, _ = init_worksheets(sh)
    # Use UNFORMATTED_VALUE to get raw numbers (floats) instead of formatted strings
    # This avoids locale issues where "3,000" might be parsed as 3000 instead of 3.0
    data = ws_inv.get_all_records(value_render_option='UNFORMATTED_VALUE')
    if data:
        df = pd.DataFrame(data)
        # Ensure all expected columns exist
        expected_cols = ["Date", "Ticker", "Platform", "Quantity", "Price", 
                         "Currency", "Commission", "Commission_Type", "Commission_Currency", "Total_Cost"]
        for col in expected_cols:
            if col not in df.columns:
                df[col] = "" # Default to empty string for missing cols
        
        # Enforce numeric types using safe_float
        numeric_cols = ["Quantity", "Price", "Commission", "Total_Cost"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].apply(utils.safe_float)
        return df
    else:
        return pd.DataFrame(columns=[
            "Date", "Ticker", "Platform", "Quantity", "Price", 
            "Currency", "Commission", "Commission_Type", "Commission_Currency", "Total_Cost"
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
    api_keys = utils.get_secret("api_keys")
    if api_keys:
        settings["api_keys"] = api_keys
    
    # Load Ticker Config from Sheet
    sh = get_db_connection()
    _, ws_settings = init_worksheets(sh)
    records = ws_settings.get_all_records()
    
    config = {}
    for r in records:
        if r["Ticker"]:
            config[r["Ticker"]] = {
                "source": r.get("Data Source", "Manual"),
                "type": r.get("Type", "Acción ARG") # Default to some type if missing
            }
    settings["ticker_config"] = config
    
    return settings

def save_settings(settings):
    # Only saves Ticker Config to Sheet. API keys must be managed in secrets.toml/cloud dashboard.
    sh = get_db_connection()
    _, ws_settings = init_worksheets(sh)
    
    # Prepare dataframe
    config_data = []
    for ticker, info in settings.get("ticker_config", {}).items():
        if isinstance(info, dict):
            config_data.append({
                "Ticker": ticker, 
                "Data Source": info.get("source", "Manual"),
                "Type": info.get("type", "Acción ARG")
            })
        else:
            # Migration path for old format
            config_data.append({
                "Ticker": ticker, 
                "Data Source": info,
                "Type": "Acción ARG"
            })
    
    df_config = pd.DataFrame(config_data)
    
    ws_settings.clear()
    ws_settings.append_row(["Ticker", "Data Source", "Type"])
    if not df_config.empty:
        ws_settings.append_rows(df_config.values.tolist())

def load_platforms():
    sh = get_db_connection()
    try:
        ws = sh.worksheet("Platforms")
        records = ws.get_all_records()
        if not records:
             return pd.DataFrame(columns=["Platform", "Entry Commission", "Entry Type", "Exit Commission", "Exit Type", "Commission Currency"])
        df = pd.DataFrame(records)
        # Ensure numeric
        for col in ["Entry Commission", "Exit Commission"]:
            df[col] = df[col].apply(utils.safe_float)
        return df
    except:
        return pd.DataFrame(columns=["Platform", "Entry Commission", "Entry Type", "Exit Commission", "Exit Type", "Commission Currency"])

def save_platforms(df):
    sh = get_db_connection()
    try:
        ws = sh.worksheet("Platforms")
        ws.clear()
        ws.append_row(df.columns.tolist())
        if not df.empty:
            ws.append_rows(df.values.tolist())
    except Exception as e:
        st.error(f"Error al guardar plataformas: {e}")

def load_earnings():
    sh = get_db_connection()
    try:
        ws = sh.worksheet("Earnings")
        data = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')
        if data:
            df = pd.DataFrame(data)
            # Ensure numeric types
            numeric_cols = ["Amount", "Capital_Reduction"]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = df[col].apply(utils.safe_float)
            return df
        else:
            return pd.DataFrame(columns=["Date", "Ticker", "Type", "Currency", "Amount", "Capital_Reduction"])
    except:
        return pd.DataFrame(columns=["Date", "Ticker", "Type", "Currency", "Amount", "Capital_Reduction"])

def save_earnings(df):
    sh = get_db_connection()
    try:
        ws = sh.worksheet("Earnings")
        
        df_tosave = df.copy()
        if "Date" in df_tosave.columns:
            df_tosave["Date"] = df_tosave["Date"].astype(str)
        df_tosave = df_tosave.fillna("")

        ws.clear()
        ws.append_row(df_tosave.columns.tolist())
        if not df_tosave.empty:
            ws.append_rows(df_tosave.values.tolist())
    except Exception as e:
        st.error(f"Error al guardar beneficios: {e}")
