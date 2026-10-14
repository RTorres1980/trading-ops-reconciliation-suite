"""Best-execution analytics: how each fill compares to the NBBO at order arrival.

Price improvement per share is positive when the client got a better price than the quote:
  BUY:  ask - fill price
  SELL: fill price - bid
A fill outside the NBBO (negative improvement) is a trade-through and needs review.
"""
import numpy as np
import pandas as pd


def per_trade(trades):
    t = trades.copy()
    buy = t["side"] == "BUY"
    t["midpoint"] = (t["nbbo_bid"] + t["nbbo_ask"]) / 2
    t["quoted_spread"] = t["nbbo_ask"] - t["nbbo_bid"]
    t["improvement_per_share"] = np.where(buy, t["nbbo_ask"] - t["price"], t["price"] - t["nbbo_bid"]).round(4)
    t["total_improvement"] = (t["improvement_per_share"] * t["quantity"]).round(2)
    # Effective spread: twice the distance from the midpoint, the standard Rule 605 measure.
    t["effective_spread"] = (2 * (t["price"] - t["midpoint"]).abs()).round(4)
    t["e_q_ratio"] = (t["effective_spread"] / t["quoted_spread"]).round(3)
    t["outcome"] = np.select(
        [t["improvement_per_share"] > 0.00005, t["improvement_per_share"] >= -0.00005],
        ["IMPROVED", "AT_QUOTE"], default="TRADE_THROUGH")
    return t


def venue_scorecard(trades):
    t = per_trade(trades)
    g = t.groupby("venue")
    out = pd.DataFrame({
        "fills": g.size(),
        "shares": g["quantity"].sum(),
        "pct_improved": (100 * g["outcome"].apply(lambda s: (s == "IMPROVED").mean())).round(1),
        "trade_throughs": g["outcome"].apply(lambda s: int((s == "TRADE_THROUGH").sum())),
        "avg_improvement_per_share": g.apply(
            lambda d: (d["improvement_per_share"] * d["quantity"]).sum() / d["quantity"].sum(),
            include_groups=False).round(4),
        "total_improvement": g["total_improvement"].sum().round(2),
        "avg_e_q_ratio": g["e_q_ratio"].mean().round(3),
    })
    return out.sort_values("avg_improvement_per_share", ascending=False).reset_index()


def trade_throughs(trades):
    t = per_trade(trades)
    cols = ["trade_id", "account", "symbol", "side", "quantity", "price", "nbbo_bid", "nbbo_ask",
            "improvement_per_share", "venue", "exec_time"]
    return t.loc[t["outcome"] == "TRADE_THROUGH", cols].reset_index(drop=True)
