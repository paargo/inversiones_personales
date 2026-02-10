import streamlit as st

def safe_float(value):
    """Safely convert string with thousands separators and dot decimal to float"""
    if isinstance(value, (float, int)):
        return float(value)
    if not value or str(value).strip() == "":
        return 0.0
    try:
        s = str(value).strip()
        # If it has both comma and dot, assume US style (comma = thousands, dot = decimal)
        # OR if it has a comma and it appears to be a thousands separator.
        # But safest is: remove all commas, then parse.
        # However, if someone entered "1,50" meaning "1.50", we need to handle that.
        
        # Heuristic: if comma is near the end (2 chars), it might be decimal.
        # But since we use f"{x:,.2f}" for output, we should be careful.
        
        # Simply remove commas and see if it floats.
        clean_s = s.replace(",", "")
        return float(clean_s)
    except ValueError:
        try:
            # Try treating comma as decimal if it failed
            return float(s.replace(",", "."))
        except ValueError:
            return 0.0

def get_secret(key):
    """Safely get a secret from st.secrets to avoid StreamlitSecretNotFoundError"""
    try:
        return st.secrets.get(key)
    except Exception:
        return None
