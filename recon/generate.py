"""Synthetic data for one trading day at a small broker-dealer.

Files written to data/:
  sod_positions.csv        start-of-day positions per account and symbol (internal books)
  sod_cash.csv             start-of-day cash per account
  trades.csv               the day's executions, with the NBBO at order arrival and the venue
  custodian_positions.csv  end-of-day positions reported by the custodian (with planted breaks)
  custodian_cash.csv       end-of-day cash reported by the custodian (with planted breaks)
"""
import argparse
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

PRICES = {"AAPL": 190.0, "MSFT": 410.0, "JNJ": 155.0, "XOM": 112.0, "KO": 62.0,
          "VTI": 270.0, "BND": 72.0, "IWM": 205.0, "PG": 165.0, "HD": 360.0}
VENUES = ["NASDAQ", "NYSE", "ARCA", "VIRTU", "CITADEL", "IEX"]
COMMISSION_PER_SHARE = 0.005


def _sod(rng, n_accounts):
    accounts = [f"ACCT-{n:03d}" for n in range(1, n_accounts + 1)]
    rows = []
    for a in accounts:
        for s in rng.choice(list(PRICES), size=rng.integers(3, 7), replace=False):
            rows.append((a, s, int(rng.integers(10, 800))))
    positions = pd.DataFrame(rows, columns=["account", "symbol", "quantity"])
    cash = pd.DataFrame({"account": accounts,
                         "cash": np.round(rng.uniform(20_000, 250_000, len(accounts)), 2)})
    return positions, cash


def _trades(rng, positions, n_trades, trade_date):
    held = positions.sample(n=n_trades, replace=True, random_state=int(rng.integers(1e9))).reset_index(drop=True)
    side = np.where(rng.random(n_trades) < 0.55, "BUY", "SELL")
    qty = rng.integers(1, 120, n_trades)
    # Never sell more than was held at the open.
    qty = np.where(side == "SELL", np.minimum(qty, held["quantity"] // 3 + 1), qty)

    mid = np.array([PRICES[s] for s in held["symbol"]]) * (1 + rng.normal(0, 0.004, n_trades))
    half_spread = np.round(np.maximum(0.01, mid * rng.uniform(0.00005, 0.0004, n_trades)), 2)
    bid, ask = np.round(mid - half_spread, 2), np.round(mid + half_spread, 2)
    venue = rng.choice(VENUES, n_trades, p=[0.2, 0.15, 0.1, 0.2, 0.25, 0.1])

    # Most fills land inside the spread; a few at the touch; some venues improve price more often.
    improve = rng.beta(2, 5, n_trades) * (ask - bid)
    improve = np.where(np.isin(venue, ["CITADEL", "VIRTU"]), improve * 1.3, improve)
    price = np.where(side == "BUY", ask - improve, bid + improve)
    # A small share of fills trade through the NBBO (worse than the quote), which best ex should catch.
    through = rng.random(n_trades) < 0.015
    price = np.where(through & (side == "BUY"), ask + 0.03, price)
    price = np.where(through & (side == "SELL"), bid - 0.03, price)

    start = pd.Timestamp(trade_date) + pd.Timedelta(hours=9, minutes=30)
    return pd.DataFrame({
        "trade_id": [f"X{i:05d}" for i in range(1, n_trades + 1)],
        "account": held["account"],
        "symbol": held["symbol"],
        "side": side,
        "quantity": qty.astype(int),
        "price": np.round(price, 4),
        "commission": np.round(qty * COMMISSION_PER_SHARE, 2),
        "venue": venue,
        "nbbo_bid": bid,
        "nbbo_ask": ask,
        "exec_time": [start + pd.Timedelta(seconds=int(s)) for s in rng.integers(0, 23400, n_trades)],
    })


def expected_eod(positions, cash, trades):
    """Internal books rolled forward: SOD plus the day's trades."""
    signed = np.where(trades["side"] == "BUY", trades["quantity"], -trades["quantity"])
    flows = trades.assign(delta=signed).groupby(["account", "symbol"], as_index=False)["delta"].sum()
    pos = positions.merge(flows, on=["account", "symbol"], how="outer").fillna(0)
    pos["quantity"] = (pos["quantity"] + pos["delta"]).astype(int)
    pos = pos.drop(columns="delta")

    gross = trades["quantity"] * trades["price"]
    cash_flow = np.where(trades["side"] == "BUY", -gross, gross) - trades["commission"]
    cf = trades.assign(cf=cash_flow).groupby("account", as_index=False)["cf"].sum()
    c = cash.merge(cf, on="account", how="left").fillna(0)
    c["cash"] = (c["cash"] + c["cf"]).round(2)
    return pos[pos["quantity"] != 0].reset_index(drop=True), c.drop(columns="cf")


def _custodian(rng, eod_pos, eod_cash, trades):
    """Custodian's view of EOD, with realistic breaks planted. Returns (pos, cash, planted)."""
    pos, cash = eod_pos.copy(), eod_cash.copy()
    planted = []

    # 1. A trade the custodian never received: its quantity is missing from the position.
    t = trades.iloc[int(rng.integers(len(trades)))]
    sign = 1 if t["side"] == "BUY" else -1
    m = (pos["account"] == t["account"]) & (pos["symbol"] == t["symbol"])
    pos.loc[m, "quantity"] -= sign * t["quantity"]
    planted.append(("POSITION", t["account"], t["symbol"], f"unbooked trade {t['trade_id']}"))

    # 2. A 2-for-1 split the custodian applied but internal books did not.
    i = int(rng.integers(len(pos)))
    pos.loc[i, "quantity"] *= 2
    planted.append(("POSITION", pos.at[i, "account"], pos.at[i, "symbol"], "2:1 split"))

    # 3. A position the custodian holds that internal books don't know about (e.g. a transfer in).
    acct = pos["account"].iloc[0]
    missing_sym = next(s for s in PRICES if not ((pos["account"] == acct) & (pos["symbol"] == s)).any())
    pos = pd.concat([pos, pd.DataFrame([(acct, missing_sym, 25)], columns=pos.columns)], ignore_index=True)
    planted.append(("POSITION", acct, missing_sym, "unexpected at custodian"))

    # 4. A position internal books hold that the custodian dropped.
    j = int(rng.integers(len(pos) - 1))
    planted.append(("POSITION", pos.at[j, "account"], pos.at[j, "symbol"], "missing at custodian"))
    pos = pos.drop(index=j).reset_index(drop=True)

    # 5. Cash: a fee the custodian charged that internal books didn't accrue, and a rounding difference.
    k = int(rng.integers(len(cash)))
    cash.loc[k, "cash"] = round(cash.at[k, "cash"] - 35.00, 2)
    planted.append(("CASH", cash.at[k, "account"], None, "custodian fee"))
    k2 = (k + 1) % len(cash)
    cash.loc[k2, "cash"] = round(cash.at[k2, "cash"] + 0.004, 3)  # within tolerance, should NOT break

    return pos, cash, pd.DataFrame(planted, columns=["kind", "account", "symbol", "cause"])


def generate(n_accounts=25, n_trades=600, trade_date="2025-06-02", seed=11, out_dir=DATA_DIR):
    rng = np.random.default_rng(seed)
    positions, cash = _sod(rng, n_accounts)
    trades = _trades(rng, positions, n_trades, trade_date)
    eod_pos, eod_cash = expected_eod(positions, cash, trades)
    cust_pos, cust_cash, planted = _custodian(rng, eod_pos, eod_cash, trades)

    os.makedirs(out_dir, exist_ok=True)
    positions.to_csv(os.path.join(out_dir, "sod_positions.csv"), index=False)
    cash.to_csv(os.path.join(out_dir, "sod_cash.csv"), index=False)
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False)
    cust_pos.to_csv(os.path.join(out_dir, "custodian_positions.csv"), index=False)
    cust_cash.to_csv(os.path.join(out_dir, "custodian_cash.csv"), index=False)
    return planted


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--trades", type=int, default=600)
    args = p.parse_args()
    planted = generate(n_trades=args.trades, seed=args.seed)
    print(f"Data written to {DATA_DIR}\nPlanted breaks:\n{planted.to_string(index=False)}")
