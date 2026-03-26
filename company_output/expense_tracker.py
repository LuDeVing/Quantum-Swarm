#!/usr/bin/env python3
"""expenses.py — CLI Expense Tracker (HamiltonianSwarm generated)"""

import argparse, csv, json, sys
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent / "expense_tracker.json"

CATEGORIES = ["food","transport","housing","health","entertainment","other"]
CAT_COLOUR = {
    "food":"\033[93m","transport":"\033[94m","housing":"\033[91m",
    "health":"\033[92m","entertainment":"\033[95m","other":"\033[96m",
}
RESET = "\033[0m"


def load_data():
    if not DATA_FILE.exists():
        return []
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_data(records):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def next_id(records):
    return max((r["id"] for r in records), default=0) + 1


def find_record(records, record_id):
    return next((r for r in records if r["id"] == record_id), None)


def cmd_add(args):
    try:
        amount = float(args.amount)
        if amount <= 0:
            raise ValueError
    except ValueError:
        print(f"Error: amount must be a positive number.", file=sys.stderr)
        sys.exit(1)
    records = load_data()
    record = {
        "id":          next_id(records),
        "amount":      round(amount, 2),
        "category":    args.category.lower(),
        "description": args.description,
        "date":        datetime.now().isoformat(timespec="seconds"),
    }
    records.append(record)
    save_data(records)
    print(f"Added expense #{record['id']}: ${record['amount']:.2f} "
          f"[{record['category']}] {record['description']}")


def cmd_list(args):
    records = load_data()
    if args.category:
        records = [r for r in records if r["category"] == args.category.lower()]
    if args.month:
        records = [r for r in records if r["date"].startswith(args.month)]
    if not records:
        print("No expenses found.")
        return
    print(f"  {'ID':<4} {'Amount':>9} {'Category':<15} {'Date':<22} Description")
    print("  " + "-" * 65)
    for r in sorted(records, key=lambda x: x["date"], reverse=True):
        col = CAT_COLOUR.get(r["category"], "")
        print(f"  {r['id']:<4} ${r['amount']:>8.2f} "
              f"{col}{r['category']:<15}{RESET} "
              f"{r['date']:<22} {r['description']}")
    total = sum(r["amount"] for r in records)
    print(f"\n  Total: ${total:.2f} ({len(records)} expenses)")


def cmd_summary(args):
    records = load_data()
    if not records:
        print("No expenses to summarise.")
        return
    totals = {}
    for r in records:
        totals[r["category"]] = totals.get(r["category"], 0.0) + r["amount"]
    grand = sum(totals.values())
    print(f"\n  Expense Summary — Total: ${grand:.2f}")
    print("  " + "-" * 45)
    for cat, amt in sorted(totals.items(), key=lambda x: -x[1]):
        pct   = amt / grand * 100
        bar   = "#" * int(pct / 2)
        col   = CAT_COLOUR.get(cat, "")
        print(f"  {col}{cat:<15}{RESET} ${amt:>8.2f} {pct:>5.1f}%  {bar}")


def cmd_delete(args):
    records = load_data()
    record = find_record(records, args.id)
    if record is None:
        print(f"Error: no expense with id {args.id}.", file=sys.stderr)
        sys.exit(1)
    records = [r for r in records if r["id"] != args.id]
    save_data(records)
    print(f"Deleted expense #{args.id}.")


def cmd_export(args):
    records = load_data()
    out = Path(args.filename)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id","amount","category","description","date"])
        writer.writeheader()
        writer.writerows(records)
    print(f"Exported {len(records)} records to {out}.")


def main():
    parser = argparse.ArgumentParser(
        prog="expenses",
        description="CLI Expense Tracker — HamiltonianSwarm edition",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser("add", help="Log an expense")
    p.add_argument("amount",      help="Amount spent (e.g. 12.50)")
    p.add_argument("category",    help=f"Category: {', '.join(CATEGORIES)}")
    p.add_argument("description", help="Brief description")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="Show expenses")
    p.add_argument("--category", "-c", help="Filter by category")
    p.add_argument("--month",    "-m", help="Filter by month YYYY-MM")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("summary", help="Spending breakdown by category")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("delete", help="Delete an expense")
    p.add_argument("id", type=int, help="Expense ID")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("export", help="Export to CSV")
    p.add_argument("filename", help="Output CSV filename")
    p.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
