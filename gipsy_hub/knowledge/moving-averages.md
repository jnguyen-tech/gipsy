# Moving averages and EMAs

## What a moving average is
A moving average smooths price into one line so the trend is easier to see. A simple moving average (SMA) of 20 days adds the last 20 closing prices and divides by 20. Tomorrow, the oldest day drops off and the newest is added, so the average "moves". It filters out day-to-day noise. The cost is lag: because it averages the past, it always turns after price has already turned. Longer averages are smoother and lag more. Shorter ones react faster and give more false signals.

## EMA vs SMA
An exponential moving average (EMA) gives more weight to recent prices, so it reacts faster than an SMA of the same length. The formula: pick the length N and compute the multiplier k = 2 / (N + 1). Each new day, EMA today = close today × k + EMA yesterday × (1 − k). For a 20 EMA, k = 2 / 21 ≈ 0.095, so today's close counts for about 9.5% and yesterday's EMA for about 90.5%. For a 200 EMA, k ≈ 0.01. The very first value is usually seeded with a simple average. Because each EMA builds on the last one, every past price still has a tiny influence, which fades exponentially. That is where the name comes from. Gipsy's get_emas tool uses exactly this formula on daily closes.

## A worked EMA example
Say a 3-day EMA (k = 2 / 4 = 0.5) and closes of 10, 11, 12, 13, then 9. Seed with the SMA of the first three: (10 + 11 + 12) / 3 = 11. Day four: 13 × 0.5 + 11 × 0.5 = 12. Day five: 9 × 0.5 + 12 × 0.5 = 10.5. A 3-day SMA on day five would be (12 + 13 + 9) / 3 ≈ 11.33. The EMA dropped further, faster, because it weighs the newest close more. That responsiveness is why many traders prefer EMAs on shorter timeframes.

## The common lengths: 9, 21, 20, 50, 200
There is nothing magic about these numbers. They are popular, so many people watch the same lines, and that can make reactions around them more likely. 9 and 21 EMAs are short-term, used by swing and day traders to judge momentum. The 20 EMA covers roughly a month of trading days and shows the short trend. The 50 EMA, roughly a quarter, shows the medium trend. The 200 EMA, roughly a trading year, is the classic long-term trend line. Big funds and the financial press often say an asset is in a "long-term uptrend" when it trades above its 200-day average. On the daily chart a simple rule of thumb: price above a rising 200 EMA is a long-term uptrend, below a falling 200 EMA is a long-term downtrend.

## Reading the stack and the slope
Look at the order of the lines. When price is above the 20, the 20 is above the 50, and the 50 is above the 200, all fanned out and rising, the trend is strong and up (a bullish stack). The reverse order, all falling, is a strong downtrend. Lines tangled together and flat mean a sideways market, and moving-average signals are unreliable there. The slope matters as much as the position: a flat 200 EMA says there is no long-term trend, even if price is slightly above it. The distance between price and the EMA also matters. When price stretches far above the 20 EMA it often pauses or pulls back toward it.

## Crossovers: golden cross and death cross
A crossover is when a faster average crosses a slower one. 20 crossing above 50 hints that short-term momentum is turning up. The famous one is the 50 crossing the 200. When the 50 crosses above the 200 it is called a golden cross, and it is read as a sign that a long-term uptrend may be starting. When the 50 crosses below the 200 it is a death cross. Some people use SMAs for this and some use EMAs. EMA crosses happen a little earlier. Important caveats: crosses lag, sometimes by weeks or months, because the averages are slow. In sideways markets they whipsaw, crossing back and forth and generating losing signals. A cross is better treated as confirmation of what price already did than as a prediction.

## EMAs as dynamic support and resistance
In a healthy uptrend, pullbacks often stall near the 20 or 50 EMA before the trend resumes. Traders call that dynamic support because the level moves with the average. In a downtrend, rallies often stall near a falling EMA (dynamic resistance). This works because many people watch the same lines, and it fails often enough that you should never rely on it alone. Look for agreement with something else: a horizontal support level, a higher low, or a bullish candle with good volume.

## Pitfalls with moving averages
They lag, so they will always miss the exact top and bottom. They fail in ranges. Changing the lengths until history looks perfect (curve fitting) makes a system that worked in the past and fails in the future. The same length means different things on different timeframes. A 200 on a 5-minute chart is less than 17 hours. Gaps and very volatile assets like small crypto coins chop through averages. Use moving averages to describe trend and to frame decisions, then add risk management. They are a map of where price has been, not a forecast.

## Setting up EMAs on TradingView
Open Indicators, search "Moving Average Exponential", add it three times and set the lengths to 20, 50 and 200. Make the 200 the thickest. Save them as an indicator template called "EMA 20/50/200" so you can apply them to any chart. To get an alert on a crossover, open the alert dialog, set the condition to the EMA 50 line "Crossing" the EMA 200 line, and choose "Once per bar close" so a cross that reverses inside the day doesn't trigger it.
