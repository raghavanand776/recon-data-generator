"""
recon-data-generator / generate.py
Author:  Raghav Anand
Created: 2026-11-05

Generate synthetic data for 3-way reconciliation of a cash-advance app.

Creates four CSV files:
  ledger.csv     - the app's internal ledger
  processor.csv  - the payment processor's settlement report
  bank.csv       - the sponsor bank's statement
  answer_key.csv - every break we injected, so a recon engine can be scored

How to run:
  python3 generate.py            # defaults: 45 days, 8% breaks, seed 42
  python3 generate.py --help     # all options
"""

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

# Federal Reserve holidays in 2026: no ACH money moves on these days.
FED_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25),
    date(2026, 6, 19), date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 11),
    date(2026, 11, 26), date(2026, 12, 25),
}

# Business days until the processor settles, by channel.
SETTLEMENT_LAG = {"instant": 1, "ach": 2}

# The six ways we'll break transactions (used in Step 4).
BREAK_TYPES = [
    "late_bank_posting",
    "missing_at_processor",
    "missing_at_bank",
    "amount_mismatch",
    "duplicate_at_bank",
    "ach_return",
]


def is_business_day(d):
    """True if money can move on this date (Mon-Fri and not a Fed holiday)."""
    return d.weekday() < 5 and d not in FED_HOLIDAYS


def add_business_days(d, n):
    """Move forward n business days, skipping weekends and holidays."""
    while n > 0:
        d += timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return d

def make_ledger(fake, start, days, per_day):
    """Create advances, plus a repayment 7-14 days later if it falls in the window."""
    end = start + timedelta(days=days)
    rows = []
    for offset in range(days):
        ledger_date = start + timedelta(days=offset)
        for _ in range(random.randint(per_day // 2, per_day)):
            amount = random.randrange(25, 505, 5)
            user = fake.name()
            channel = random.choice(["instant", "ach"])
            rows.append({"ledger_date": ledger_date, "txn_type": "advance",
                         "channel": channel, "user_name": user, "amount": amount})
            repay_date = ledger_date + timedelta(days=random.randint(7, 14))
            if repay_date < end:
                rows.append({"ledger_date": repay_date, "txn_type": "repayment",
                             "channel": "ach", "user_name": user, "amount": amount})
    rows.sort(key=lambda r: r["ledger_date"])
    for i, row in enumerate(rows, start=1):
        row["txn_id"] = f"LDG-{i:06d}"
    return rows