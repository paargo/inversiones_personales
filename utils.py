import streamlit as st

def safe_float(value):
    """Safely convert string with comma or dot to float"""
    if isinstance(value, (float, int)):
        return float(value)
    if not value:
        return 0.0
    try:
        # Replace comma with dot and convert
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return 0.0

def get_secret(key):
    """Safely get a secret from st.secrets to avoid StreamlitSecretNotFoundError"""
    try:
        return st.secrets.get(key)
    except Exception:
        return None
