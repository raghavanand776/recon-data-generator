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

def make_processor_and_bank(ledger):
    """Build the 'perfect world' processor and bank records for every ledger row."""
    processor, bank = {}, {}
    for i, row in enumerate(ledger, start=1):
        # When does money actually move? 1 business day (instant) or 2 (ACH).
        settle = add_business_days(row["ledger_date"], SETTLEMENT_LAG[row["channel"]])

        # Processor's record: echoes our txn_id, adds its own reference.
        processor[row["txn_id"]] = {
            "processor_ref": f"PRC-{i:06d}", "txn_id": row["txn_id"],
            "amount": row["amount"], "status": "settled", "return_code": "",
            "settle_date": settle,
        }

        # Bank's view: advances are money OUT (negative), repayments are money IN.
        sign = -1 if row["txn_type"] == "advance" else 1

        # The bank does NOT know our txn_id; only the processor ref, buried in text.
        # It's a list so Step 4 can add duplicates/returns or empty it.
        bank[row["txn_id"]] = [{
            "bank_ref": f"BNK-{i:06d}", "posted_date": settle,
            "amount": sign * row["amount"], "description": f"PROC SETTLE PRC-{i:06d}",
        }]
    return processor, bank

def inject_breaks(ledger, processor, bank, rate):
    """Break a random sample of transactions and record each break in the answer key."""
    answer_key = []
    # Pick ~8% of transactions, never the same one twice.
    for row in random.sample(ledger, k=int(len(ledger) * rate)):
        txn_id = row["txn_id"]
        # Only repayments can bounce, so advances skip the last type (ach_return).
        options = BREAK_TYPES if row["txn_type"] == "repayment" else BREAK_TYPES[:-1]
        kind = random.choice(options)

        if kind == "late_bank_posting":
            # Bank posts 1-3 business days late (long weekends, cut-off times).
            extra = random.randint(1, 3)
            entry = bank[txn_id][0]
            entry["posted_date"] = add_business_days(entry["posted_date"], extra)
            detail = f"bank posted {extra} business day(s) late"

        elif kind == "missing_at_processor":
            # Processor never got it, so no money moved: remove processor + bank.
            del processor[txn_id]
            bank[txn_id] = []
            detail = "processor never received it, so no money moved"

        elif kind == "missing_at_bank":
            # Processor says settled, bank never posted: money "in flight".
            bank[txn_id] = []
            detail = "processor settled but bank never posted"

        elif kind == "amount_mismatch":
            # Processor quietly deducts a small fee.
            fee = round(random.uniform(0.25, 2.00), 2)
            net = round(row["amount"] - fee, 2)
            processor[txn_id]["amount"] = net
            entry = bank[txn_id][0]
            entry["amount"] = net if entry["amount"] > 0 else -net  # keep the sign
            detail = f"processor deducted a ${fee:.2f} fee"

        elif kind == "duplicate_at_bank":
            # Bank posts the same item twice (re-sent settlement file).
            duplicate = dict(bank[txn_id][0])  # dict() makes a copy
            duplicate["bank_ref"] += "-DUP"
            bank[txn_id].append(duplicate)
            detail = "bank posted the same item twice"

        else:  # ach_return
            # Repayment posts, then bounces 2 business days later (R01 = insufficient funds).
            processor[txn_id]["status"] = "returned"
            processor[txn_id]["return_code"] = "R01"
            original = bank[txn_id][0]
            bank[txn_id].append({
                "bank_ref": original["bank_ref"] + "-RET",
                "posted_date": add_business_days(original["posted_date"], 2),
                "amount": -original["amount"],  # opposite sign cancels it out
                "description": f"ACH RETURN R01 {processor[txn_id]['processor_ref']}",
            })
            detail = "repayment returned for insufficient funds (R01)"

        # Record what we did, so the recon engine can be scored later.
        answer_key.append({"txn_id": txn_id, "break_type": kind, "detail": detail})
    return answer_key

def generate(start, days, per_day, break_rate, seed):
    """Run every stage and return the four tables as pandas DataFrames."""
    # Seed BOTH random generators so the same seed gives the same data, names included.
    random.seed(seed)
    Faker.seed(seed)
    fake = Faker()

    # The three stages you built in Steps 2-4.
    ledger = make_ledger(fake, start, days, per_day)
    processor, bank = make_processor_and_bank(ledger)
    answer_key = inject_breaks(ledger, processor, bank, break_rate)

    # Bank entries are grouped per transaction; flatten them into one list.
    bank_rows = [entry for entries in bank.values() for entry in entries]

    # Turn each book into a table, sorted like a real report.
    return {
        "ledger.csv": pd.DataFrame(ledger, columns=[
            "txn_id", "ledger_date", "txn_type", "channel", "user_name", "amount"]),
        "processor.csv": pd.DataFrame(list(processor.values()))
            .sort_values(["settle_date", "processor_ref"]),
        "bank.csv": pd.DataFrame(bank_rows).sort_values(["posted_date", "bank_ref"]),
        "answer_key.csv": pd.DataFrame(answer_key, columns=["txn_id", "break_type", "detail"])
            .sort_values("txn_id"),
    }


def main():
    """Read command-line options, generate the data, and write four CSV files."""
    parser = argparse.ArgumentParser(description="Generate 3-way recon test data.")
    parser.add_argument("--start", default="2026-10-01", help="first ledger date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=45, help="number of days to generate")
    parser.add_argument("--per-day", type=int, default=20, help="max advances per day")
    parser.add_argument("--break-rate", type=float, default=0.08, help="share of txns to break")
    parser.add_argument("--seed", type=int, default=42, help="same seed = same data")
    parser.add_argument("--out", default="data", help="output folder")
    args = parser.parse_args()

    tables = generate(date.fromisoformat(args.start), args.days, args.per_day,
                      args.break_rate, args.seed)

    # Create the output folder and write each table as a CSV.
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out_dir / name, index=False)
        print(f"{name:<16}{len(df):>6} rows")

    print("\nBreaks injected:")
    print(tables["answer_key.csv"]["break_type"].value_counts().to_string())


# Only run main() when this file is executed directly (not when tests import it).
if __name__ == "__main__":
    main()