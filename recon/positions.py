"""End-of-day position and cash reconciliation: internal books vs custodian."""

CASH_TOLERANCE = 0.01


def reconcile_positions(expected, custodian, trades=None):
    """Compare expected EOD positions to the custodian's. Returns breaks with a suggested cause.

    Suggested causes are heuristics an ops analyst would check first:
      - the difference equals one of the day's trades in that account/symbol -> likely unbooked trade
      - the custodian holds an exact multiple of the books -> likely a split not applied internally
    """
    m = expected.merge(custodian, on=["account", "symbol"], how="outer",
                       suffixes=("_books", "_custodian"), indicator=True)
    m[["quantity_books", "quantity_custodian"]] = m[["quantity_books", "quantity_custodian"]].fillna(0).astype(int)
    m["difference"] = m["quantity_custodian"] - m["quantity_books"]
    breaks = m[m["difference"] != 0].copy()

    breaks["break_type"] = breaks["_merge"].map({
        "left_only": "MISSING_AT_CUSTODIAN",
        "right_only": "UNEXPECTED_AT_CUSTODIAN",
        "both": "QUANTITY_MISMATCH",
    }).astype(str)
    breaks["suggested_cause"] = [_suggest(r, trades) for r in breaks.itertuples()]
    cols = ["account", "symbol", "quantity_books", "quantity_custodian", "difference", "break_type", "suggested_cause"]
    return breaks[cols].sort_values(["account", "symbol"]).reset_index(drop=True)


def _suggest(row, trades):
    if row.break_type == "MISSING_AT_CUSTODIAN":
        return "Position not reported by custodian; confirm transfer out or reporting gap"
    if row.break_type == "UNEXPECTED_AT_CUSTODIAN":
        return "Not on internal books; check for a transfer in or unbooked activity"
    if trades is not None:
        t = trades[(trades["account"] == row.account) & (trades["symbol"] == row.symbol)]
        signed = t["quantity"].where(t["side"] == "BUY", -t["quantity"])
        hit = t[signed == -row.difference]
        if len(hit):
            return f"Matches trade {hit['trade_id'].iloc[0]}; custodian likely missing it"
    if row.quantity_books and row.quantity_custodian % row.quantity_books == 0:
        ratio = row.quantity_custodian // row.quantity_books
        if ratio > 1:
            return f"Custodian holds {ratio}x books; check for a {ratio}:1 split"
    return "Investigate"


def reconcile_cash(expected, custodian, tolerance=CASH_TOLERANCE):
    m = expected.merge(custodian, on="account", how="outer", suffixes=("_books", "_custodian"))
    m[["cash_books", "cash_custodian"]] = m[["cash_books", "cash_custodian"]].fillna(0.0)
    m["difference"] = (m["cash_custodian"] - m["cash_books"]).round(2)
    return m[m["difference"].abs() > tolerance].sort_values("account").reset_index(drop=True)
