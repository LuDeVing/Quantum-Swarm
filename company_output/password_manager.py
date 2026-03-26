#!/usr/bin/env python3
"""vault.py — CLI Password Manager (HamiltonianSwarm generated)"""

import argparse, base64, json, secrets, string, sys
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent / "password_manager.json"
ALPHABET  = string.ascii_letters + string.digits + "!@#$%^&*()"


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
        json.dump(records, f, indent=2)


def find_record(records, service):
    return next((r for r in records if r["service"].lower() == service.lower()), None)


def encode_pw(password: str) -> str:
    return base64.b64encode(password.encode()).decode()


def decode_pw(encoded: str) -> str:
    return base64.b64decode(encoded.encode()).decode()


def cmd_add(args):
    import getpass
    password = getpass.getpass(f"Password for {args.service}: ")
    records = load_data()
    if find_record(records, args.service):
        print(f"Service '{args.service}' already exists. Delete it first.")
        sys.exit(1)
    records.append({
        "service":    args.service,
        "username":   args.username,
        "password":   encode_pw(password),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_data(records)
    print(f"Stored credentials for {args.service}.")


def cmd_get(args):
    records = load_data()
    r = find_record(records, args.service)
    if r is None:
        print(f"Error: service '{args.service}' not found.", file=sys.stderr)
        sys.exit(1)
    pw = decode_pw(r["password"])
    print(f"Service:  {r['service']}")
    print(f"Username: {r['username']}")
    print(f"Password: {pw}")


def cmd_list(args):
    records = load_data()
    if not records:
        print("No credentials stored.")
        return
    print(f"  {'Service':<20} {'Username':<25} {'Created':<22}")
    print("  " + "-" * 68)
    for r in sorted(records, key=lambda x: x["service"].lower()):
        print(f"  {r['service']:<20} {r['username']:<25} {r['created_at']:<22}")


def cmd_delete(args):
    records = load_data()
    if not find_record(records, args.service):
        print(f"Error: service '{args.service}' not found.", file=sys.stderr)
        sys.exit(1)
    records = [r for r in records if r["service"].lower() != args.service.lower()]
    save_data(records)
    print(f"Deleted credentials for {args.service}.")


def cmd_generate(args):
    length = max(8, args.length)
    password = "".join(secrets.choice(ALPHABET) for _ in range(length))
    records = load_data()
    existing = find_record(records, args.service)
    if existing:
        existing["password"]   = encode_pw(password)
        existing["username"]   = args.username
        existing["created_at"] = datetime.now().isoformat(timespec="seconds")
    else:
        records.append({
            "service":    args.service,
            "username":   args.username,
            "password":   encode_pw(password),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
    save_data(records)
    print(f"Generated password for {args.service}: {password}")


def main():
    parser = argparse.ArgumentParser(prog="vault",
        description="CLI Password Manager — HamiltonianSwarm edition")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser("add",  help="Store credentials")
    p.add_argument("service");  p.add_argument("username")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("get",  help="Retrieve credentials")
    p.add_argument("service")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("list", help="List all services")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", help="Remove credentials")
    p.add_argument("service")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("generate", help="Generate a strong password")
    p.add_argument("service"); p.add_argument("username")
    p.add_argument("--length", "-l", type=int, default=16)
    p.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
