"""Verwaltung für Tokens & Invite-Codes.

Im Container (empfohlen):
    docker compose exec mem0-mcp python manage.py token --user-id bojan --name Bojan
    docker compose exec mem0-mcp python manage.py invite --user-id max --name Max
    docker compose exec mem0-mcp python manage.py list
    docker compose exec mem0-mcp python manage.py revoke --user-id max

Nativ (ohne Docker): TOKENS_PATH auf eine lokale Datei setzen, z. B.:
    $env:TOKENS_PATH = "C:\\mem0\\tokens.json"
"""

import argparse
import json

from auth import TokenStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Token-/Invite-Verwaltung")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_token = sub.add_parser("token", help="Direkt ein persönliches Token anlegen (Admin/Owner)")
    p_token.add_argument("--user-id", required=True)
    p_token.add_argument("--name", default="")

    p_invite = sub.add_parser("invite", help="Einmal-Invite-Code für einen neuen Nutzer anlegen")
    p_invite.add_argument("--user-id", required=True)
    p_invite.add_argument("--name", default="")

    sub.add_parser("list", help="Tokens & Invites auflisten (Tokens maskiert)")

    p_revoke = sub.add_parser("revoke", help="Token(s) widerrufen (per --token oder --user-id)")
    p_revoke.add_argument("--token", default=None)
    p_revoke.add_argument("--user-id", default=None)

    sub.add_parser("init", help="Store-Datei anlegen, falls sie fehlt")

    args = parser.parse_args()
    store = TokenStore()

    if args.cmd == "token":
        print(json.dumps(store.create_token(args.user_id, args.name), indent=2, ensure_ascii=False))
    elif args.cmd == "invite":
        inv = store.create_invite(args.user_id, args.name)
        print(json.dumps(inv, indent=2, ensure_ascii=False))
        print("\n→ An den Kollegen schicken:")
        print(f"   Registrierung: https://<server>/register")
        print(f"   Invite-Code:    {inv['invite_code']}")
    elif args.cmd == "list":
        print(json.dumps(store.list_all(), indent=2, ensure_ascii=False))
    elif args.cmd == "revoke":
        if not args.token and not args.user_id:
            parser.error("revoke braucht --token oder --user-id")
        n = store.revoke(token=args.token, user_id=args.user_id)
        print(f"{n} Token(s) widerrufen.")
    elif args.cmd == "init":
        store.ensure()
        print("Store initialisiert.")


if __name__ == "__main__":
    main()