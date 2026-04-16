import sys
import pandas as pd
import datetime
sys.path.append('.')
import database as db
import market_data as md

settings = db.load_settings()
fred_key = settings.get('fred_api_key')
print('FRED KEY:', 'Configured' if fred_key else 'Not Configured')

if fred_key:
    cpi_raw = md.get_us_cpi(fred_key)
    print('CPI points:', len(cpi_raw) if cpi_raw else 0)
    if not cpi_raw:
         print('API returned empty! Maybe invalid key?')

try:
    df = db.load_data()
    if df.empty:
        print('No data to plot')
        sys.exit(0)
        
    df['Date'] = pd.to_datetime(df['Date'])
    min_d = df['Date'].min()
    dr = pd.date_range(start=min_d, end=datetime.date.today(), freq='D')
    
    cpi_series = None
    if fred_key:
        cpi_raw = md.get_us_cpi(fred_key)
        if cpi_raw:
            cpi_series = pd.Series(cpi_raw)
            cpi_series.index = pd.to_datetime(cpi_series.index)
            cpi_series = cpi_series.sort_index()
            print('CPI Series initialized, items:', len(cpi_series))

    d = dr[0]
    print('Testing date:', d)
    d_cpi_slice = cpi_series.loc[:d]
    print('d_cpi_slice len:', len(d_cpi_slice))
    current_cpi = d_cpi_slice.iloc[-1]
    print('current_cpi:', current_cpi)

except Exception as e:
    import traceback
    traceback.print_exc()

