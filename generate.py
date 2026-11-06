"""Generate synthetic data for 3-way reconciliation of a cash-advance app.

Creates four CSV files:
  ledger.csv     - the app's internal ledger
  processor.csv  - the payment processor's settlement report
  bank.csv       - the sponsor bank's statement
  answer_key.csv - every break we injected, so a recon engine can be scored
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