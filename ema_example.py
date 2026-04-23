from utils import calculateEMA


prices = [10, 11, 12, 13, 14, 15]
ema_3 = calculateEMA(prices, 3)

print("Prices:", prices)
print("EMA(3):", ema_3)
