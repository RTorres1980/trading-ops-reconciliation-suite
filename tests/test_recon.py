import pandas as pd
import pytest

from recon import best_execution, positions
from recon.generate import expected_eod, generate
from recon.main import load, run


@pytest.fixture(scope="module")
def day(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    planted = generate(seed=3, out_dir=str(out))
    return load(str(out)), planted, str(out)


def test_every_planted_position_break_found(day):
    d, planted, _ = day
    exp_pos, _ = expected_eod(d["sod_positions"], d["sod_cash"], d["trades"])
    breaks = positions.reconcile_positions(exp_pos, d["custodian_positions"], d["trades"])
    want = set(map(tuple, planted.loc[planted["kind"] == "POSITION", ["account", "symbol"]].values))
    assert set(map(tuple, breaks[["account", "symbol"]].values)) == want


def test_suggested_causes(day):
    d, planted, _ = day
    exp_pos, _ = expected_eod(d["sod_positions"], d["sod_cash"], d["trades"])
    breaks = positions.reconcile_positions(exp_pos, d["custodian_positions"], d["trades"]).set_index(
        ["account", "symbol"])
    for p in planted[planted["kind"] == "POSITION"].itertuples():
        cause = breaks.loc[(p.account, p.symbol), "suggested_cause"]
        if p.cause.startswith("unbooked trade"):
            assert p.cause.split()[-1] in cause
        elif p.cause == "2:1 split":
            assert "2:1 split" in cause


def test_cash_fee_found_and_rounding_ignored(day):
    d, planted, _ = day
    _, exp_cash = expected_eod(d["sod_positions"], d["sod_cash"], d["trades"])
    breaks = positions.reconcile_cash(exp_cash, d["custodian_cash"])
    assert list(breaks["account"]) == list(planted.loc[planted["kind"] == "CASH", "account"])
    assert breaks["difference"].iloc[0] == -35.0


def test_expected_eod_math():
    sod = pd.DataFrame([("A", "X", 100)], columns=["account", "symbol", "quantity"])
    cash = pd.DataFrame([("A", 1000.0)], columns=["account", "cash"])
    trades = pd.DataFrame([
        {"account": "A", "symbol": "X", "side": "BUY", "quantity": 10, "price": 5.0, "commission": 0.05},
        {"account": "A", "symbol": "X", "side": "SELL", "quantity": 4, "price": 6.0, "commission": 0.02},
    ])
    pos, c = expected_eod(sod, cash, trades)
    assert pos.loc[0, "quantity"] == 106
    assert c.loc[0, "cash"] == round(1000 - 50 - 0.05 + 24 - 0.02, 2)


def _fill(side, price, bid=99.98, ask=100.02, qty=100, venue="V"):
    return {"trade_id": "t", "account": "A", "symbol": "X", "side": side, "quantity": qty, "price": price,
            "nbbo_bid": bid, "nbbo_ask": ask, "venue": venue, "exec_time": "2025-06-02 10:00:00"}


def test_price_improvement_and_trade_through():
    trades = pd.DataFrame([
        _fill("BUY", 100.00),   # 2 cents better than the ask
        _fill("SELL", 99.98),   # at the bid
        _fill("BUY", 100.05),   # paid above the ask
    ])
    t = best_execution.per_trade(trades)
    assert list(t["outcome"]) == ["IMPROVED", "AT_QUOTE", "TRADE_THROUGH"]
    assert t.loc[0, "improvement_per_share"] == pytest.approx(0.02)
    assert t.loc[0, "e_q_ratio"] == pytest.approx(0.0)
    assert len(best_execution.trade_throughs(trades)) == 1


def test_venue_scorecard_weights_by_shares():
    trades = pd.DataFrame([_fill("BUY", 100.00, qty=300), _fill("BUY", 100.02, qty=100)])
    card = best_execution.venue_scorecard(trades)
    assert card.loc[0, "avg_improvement_per_share"] == pytest.approx(0.015)


def test_full_run_writes_outputs(day, tmp_path):
    _, _, data_dir = day
    results = run(use_existing=True, data_dir=data_dir, output_dir=str(tmp_path), quiet=True)
    assert {p.name for p in tmp_path.iterdir()} == {f"{k}.csv" for k in results}
