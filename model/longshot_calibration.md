# Longshot probability correction

The public graded results export from November 12–20, 2026 exposed a calibration error in +400 and longer player props. Across 5,807 settled rows with positive displayed EV, 469 won and a 1u stake on every row lost 1,316.79u. These rows include many correlated lines on the same players and are not a strategy backtest.

The correction in `bdlbox/markets.py` uses only November 12–18 positive-EV rows for the fit. Observed wins divided by wins expected from displayed probabilities were 236/260.2 (0.907) for +400–799, 94/135.5 (0.694) for +800–1499, and 43/67.8 (0.634) for +1500 and longer. We apply conservative factors of 0.88, 0.68, and 0.50 to the calibrated probability at the offered price. No offered odds are excluded by this correction.

November 19–20 were held out. On 1,300 settled positive-EV +400 rows, the old probabilities expected 134.9 wins and observed wins were 96. The corrected probabilities expected 103.7. Mean binary log loss improved from 0.2487 to 0.2407. No holdout rows cleared 8% EV after correction. This short and correlated sample is an interim reliability adjustment; refit with more independent game dates before treating longshots as validated picks.
