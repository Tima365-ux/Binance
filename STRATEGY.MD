Trading Bot Signal Conditions (Updated)
Here is a complete breakdown of the rules for the bot to generate a real trading signal. The bot can now generate both LONG (BUY) and SHORT (SELL) signals.

A signal is generated for a crypto asset only if ALL conditions for either a LONG or a SHORT are met.

LONG (BUY) Signal Conditions
Condition 1: Bullish Trend Alignment (Higher Timeframes)

The bot checks for an uptrend on at least 2 out of 3 higher timeframes (30m, 1h, 4h).

Rule: The faster moving average (EMA 50) must be above the slower one (EMA 200).

Condition 2: Bullish Entry Setup (5-minute Timeframe)

If the trend is aligned, the bot looks for ALL of the following on the 5-minute chart:

RSI Crossover: The RSI crosses up from below the "Oversold" level (e.g., from 29 to 31).

Volume Surge: Trading volume is at least 1.5x higher than the average of the last 20 candles.

Price Confirmation: The current price is above the short-term moving average (EMA 20).

SHORT (SELL) Signal Conditions
Condition 1: Bearish Trend Alignment (Higher Timeframes)

The bot checks for a downtrend on at least 2 out of 3 higher timeframes (30m, 1h, 4h).

Rule: The faster moving average (EMA 50) must be below the slower one (EMA 200).

Condition 2: Bearish Entry Setup (5-minute Timeframe)

If the trend is aligned, the bot looks for ALL of the following on the 5-minute chart:

RSI Crossover: The RSI crosses down from above the "Overbought" level (e.g., from 71 to 69).

Volume Surge: Trading volume is at least 1.5x higher than the average of the last 20 candles.

Price Confirmation: The current price is below the short-term moving average (EMA 20).

Stop Loss and Take Profit Calculation
When a signal is generated, the bot automatically calculates the recommended Stop Loss (SL) and Take Profit (TP) levels based on the market's recent volatility (using the ATR indicator).

Stop Loss: The distance is calculated by multiplying the current ATR value by the "Stop Loss ATR Multiplier" you set in the admin panel.

Take Profit: The distance is calculated by multiplying the current ATR value by the "Take Profit ATR Multiplier".

These calculated prices are sent in the Telegram alert and the SL is recorded in your trade history.