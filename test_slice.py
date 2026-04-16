import pandas as pd
import datetime

d = pd.to_datetime('2023-01-15')
s = pd.Series({ '2023-01-01': 100.0, '2023-02-01': 101.0 })
s.index = pd.to_datetime(s.index)
s = s.sort_index()

print("s.index type:", type(s.index))
print("d type:", type(d))

try:
    slice1 = s.loc[:d]
    print("slice length:", len(slice1))
    print(slice1)
except Exception as e:
    print("Exception on slicing:", e)

