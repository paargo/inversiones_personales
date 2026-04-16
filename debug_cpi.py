import sys
import pandas as pd
import datetime
sys.path.append('.')
import database as db
import market_data as md

settings = db.load_settings()
fred_key = settings.get('fred_api_key')
print('FRED KEY present:', bool(fred_key))

df = db.load_data()
if df.empty:
    print('df empty')
    sys.exit()

df['Date'] = pd.to_datetime(df['Date'])
min_d = df['Date'].min()
dr = pd.date_range(start=min_d, end=datetime.date.today(), freq='D')

cpi_raw = md.get_us_cpi(fred_key)
print('CPI Raw items:', len(cpi_raw) if cpi_raw else 0)

if not cpi_raw:
    sys.exit()

cpi_series = pd.Series(cpi_raw)
cpi_series.index = pd.to_datetime(cpi_series.index)
cpi_series = cpi_series.sort_index()

d = dr[0]
print('Testing for date:', d)

try:
    d_cpi_slice = cpi_series.loc[:d]
    print('d_cpi_slice empty:', d_cpi_slice.empty)
    if not d_cpi_slice.empty:
        current_cpi = d_cpi_slice.iloc[-1]
        
        m = df["Date"] <= d
        cf = df[m]
        print('cf size:', len(cf))
        for _, row in cf.iterrows():
            inv_d = row["Date"]
            inv_cpi_slice = cpi_series.loc[:inv_d]
            inv_cpi = inv_cpi_slice.iloc[-1] if not inv_cpi_slice.empty else current_cpi
            print('inv_cpi:', inv_cpi, 'current_cpi:', current_cpi)
            
except Exception as e:
    import traceback
    traceback.print_exc()

