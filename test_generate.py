"""
recon-data-generator / test_generate.py
Author:  Raghav Anand
Created: 2026-11-05

Tests for generate.py. Run with:
  python3 -m pytest -v
"""

from datetime import date

from generate import add_business_days, generate


def test_weekend_is_skipped():
    # Friday + 1 business day should be Monday.
    friday = date(2026, 11, 6)
    assert add_business_days(friday, 1) == date(2026, 11, 9)


def test_fed_holiday_is_skipped():
    # Tuesday + 1 should skip Wed Nov 11 (Veterans Day) and land on Thursday.
    tuesday = date(2026, 11, 10)
    assert add_business_days(tuesday, 1) == date(2026, 11, 12)


def test_same_seed_gives_same_data():
    # Run twice with seed 7: every table must be identical.
    a = generate(date(2026, 10, 1), 10, 10, 0.1, seed=7)
    b = generate(date(2026, 10, 1), 10, 10, 0.1, seed=7)
    for name in a:
        assert a[name].equals(b[name])


def test_zero_break_rate_means_everything_matches():
    # No breaks: same row counts, empty answer key, same dollar totals.
    tables = generate(date(2026, 10, 1), 10, 10, 0.0, seed=7)
    ledger, processor, bank = tables["ledger.csv"], tables["processor.csv"], tables["bank.csv"]
    assert len(ledger) == len(processor) == len(bank)
    assert tables["answer_key.csv"].empty
    assert ledger["amount"].sum() == processor["amount"].sum()


def test_every_break_points_to_a_real_ledger_row():
    # Every txn_id in the answer key must exist in the ledger.
    tables = generate(date(2026, 10, 1), 30, 20, 0.1, seed=7)
    ledger_ids = set(tables["ledger.csv"]["txn_id"])
    assert set(tables["answer_key.csv"]["txn_id"]) <= ledger_ids