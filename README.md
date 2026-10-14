# Trading Ops Reconciliation Suite

![CI](https://github.com/RTorres1980/trading-ops-reconciliation-suite/actions/workflows/ci.yml/badge.svg)

End-of-day controls a broker-dealer operations team runs after the close, built on synthetic data:

1. **Position reconciliation**: roll the internal books forward (start-of-day positions plus the day's trades) and compare them to the custodian's end-of-day positions.
2. **Cash reconciliation**: the same for cash, net of trade proceeds and commissions, with a one-cent tolerance.
3. **Best-execution review**: compare every fill to the NBBO at order arrival, score each venue, and list trade-throughs for review.

Each break comes with a suggested first place to look. If the difference equals one of the day's trades, the custodian probably missed that trade. If the custodian holds an exact multiple of the books, look for a stock split that wasn't applied internally.

This complements [m1-trading-ops-suite](https://github.com/RTorres1980/m1-trading-ops-suite), which handles trade-level matching against broker confirmations and compliance surveillance.

## Run it

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python -m recon.main     # generate a trading day and run all three checks
pytest -q
```

Output from the default run:

```
Position breaks: 4
 account symbol  books  custodian  difference  break_type               suggested_cause
ACCT-001   AAPL      0         25          25  UNEXPECTED_AT_CUSTODIAN  Not on internal books; check for a transfer in...
ACCT-003    VTI    725          0        -725  MISSING_AT_CUSTODIAN     Position not reported by custodian...
ACCT-013    JNJ    493        986         493  QUANTITY_MISMATCH        Custodian holds 2x books; check for a 2:1 split
ACCT-020    BND    273        163        -110  QUANTITY_MISMATCH        Matches trade X00125; custodian likely missing it

Cash breaks: 1
ACCT-020   books 280707.39   custodian 280672.39   difference -35.00

Best execution by venue:
  venue  fills  pct_improved  trade_throughs  avg_improvement_per_share  avg_e_q_ratio
CITADEL    161          96.9               5                     0.0332          0.479
  VIRTU    126          99.2               1                     0.0310          0.446
 NASDAQ    127          96.9               4                     0.0266          0.517
   ...
Trade-throughs needing review: 12
```

Results are also written as CSVs to `output/`.

## How it works

| File | Purpose |
|---|---|
| `recon/generate.py` | Builds start-of-day positions and cash, about 600 executions with the NBBO and venue at order time, and the custodian's end-of-day files with planted breaks: an unbooked trade, an unapplied split, a position on only one side, a custodian fee, and a sub-cent rounding difference that should *not* break |
| `recon/positions.py` | Position and cash reconciliation with break classification and suggested causes |
| `recon/best_execution.py` | Price improvement per share, effective spread and effective/quoted (E/Q) ratio per fill (the measures used in SEC Rule 605 reports), a venue scorecard weighted by shares, and the trade-through list |
| `recon/main.py` | Runs everything and writes `output/*.csv` |

**Measures used**

- *Price improvement per share*: for a buy, the ask minus the fill price; for a sell, the fill price minus the bid. Positive means the client did better than the quote.
- *Effective spread*: twice the distance between the fill and the NBBO midpoint.
- *E/Q ratio*: effective spread divided by quoted spread. Below 1.0 means the fill beat the quote.

## Tests

The tests check that every planted break is found and nothing else, that suggested causes point to the right trade or split, that the rounding difference stays under tolerance, the roll-forward arithmetic, the price-improvement and trade-through math on hand-built fills, and that the venue average is weighted by shares. CI runs lint, tests and the full workflow on every push.

## License

MIT
