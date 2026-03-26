#!/usr/bin/env python3
"""todo.py — CLI Task Manager (HamiltonianSwarm generated)"""

import argparse, json, sys
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent / "todo.json"
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
RESET = "\033[0m"
COLOURS = {"high":"\033[91m","medium":"\033[93m","low":"\033[92m"}


def load_data():
    if not DATA_FILE.exists(): return []
    try:
        with open(DATA_FILE, encoding="utf-8") as f: return json.load(f)
    except: return []

def save_data(records):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

def next_id(records):
    return max((r["id"] for r in records), default=0) + 1

def find_record(records, record_id):
    return next((r for r in records if r["id"] == record_id), None)

def cmd_add(args):
    records = load_data()
    r = {"id": next_id(records), "description": " ".join(args.description),
          "priority": args.priority, "status": "pending",
          "created_at": datetime.now().isoformat(timespec="seconds")}
    records.append(r); save_data(records)
    print(f"Added task #{r['id']}: {r['description']} [{r['priority']}]")

def cmd_list(args):
    records = load_data()
    if args.filter: records = [r for r in records if r["priority"]==args.filter]
    if not records: print("No tasks."); return
    print(f"  {'ID':<4} {'Pri':<8} {'Status':<10} Description")
    print("  " + "-"*50)
    for r in sorted(records, key=lambda t:(PRIORITY_ORDER.get(t["priority"],9),t["id"])):
        col = COLOURS.get(r["priority"],"")
        mark = "x" if r["status"]=="done" else " "
        print(f"  {r['id']:<4} {col}{r['priority']:<8}{RESET} [{mark}]       {r['description']}")

def cmd_done(args):
    records = load_data()
    r = find_record(records, args.id)
    if r is None: print(f"Error: no task {args.id}.", file=sys.stderr); sys.exit(1)
    r["status"] = "done"; save_data(records)
    print(f"Task #{args.id} marked as done.")

def cmd_delete(args):
    records = load_data()
    if not find_record(records, args.id):
        print(f"Error: no task {args.id}.", file=sys.stderr); sys.exit(1)
    save_data([r for r in records if r["id"]!=args.id])
    print(f"Task #{args.id} deleted.")

def cmd_clear(args):
    records = load_data()
    before = len(records)
    save_data([r for r in records if r["status"]!="done"])
    print(f"Cleared {before - len([r for r in load_data()])} completed tasks.")

def main():
    p = argparse.ArgumentParser(prog="todo")
    s = p.add_subparsers(dest="command"); s.required = True
    a = s.add_parser("add");   a.add_argument("description",nargs="+")
    a.add_argument("--priority","-p",choices=["high","medium","low"],default="medium")
    a.set_defaults(func=cmd_add)
    a = s.add_parser("list");  a.add_argument("--filter","-f",choices=["high","medium","low"])
    a.set_defaults(func=cmd_list)
    a = s.add_parser("done");  a.add_argument("id",type=int); a.set_defaults(func=cmd_done)
    a = s.add_parser("delete");a.add_argument("id",type=int); a.set_defaults(func=cmd_delete)
    a = s.add_parser("clear"); a.set_defaults(func=cmd_clear)
    args = p.parse_args(); args.func(args)

if __name__ == "__main__":
    main()
