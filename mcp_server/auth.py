"""Token- & Invite-Verwaltung + ASGI-Auth-Middleware für den Mem0-MCP-Server.

Design:
- Eine tokens.json (TOKENS_PATH, Default /data/tokens.json) enthält persönliche
  Tokens und einmalige Invite-Codes.
- Jedes Token bildet auf genau eine user_id ab → Memories sind pro Nutzer
  automatisch getrennt (Token = Identität).
- /register erlaubt das Einlösen eines Invite-Codes gegen ein persönliches
  Token. /health und /register sind die einzigen token-freien Pfade.
"""

import json
import os
import secrets
import threading
import time
from contextvars import ContextVar
from pathlib import Path

STORE_PATH = Path(os.getenv("TOKENS_PATH", "/data/tokens.json"))

# Aktueller Nutzer (aus dem Bearer-Token) – wird pro Request von der Middleware
# gesetzt und in den MCP-Tools gelesen (ContextVar propagiert in Tasks/Threads).
current_user: ContextVar = ContextVar("mem0_current_user", default=None)


class TokenStore:
    """Kleiner, dateibasierter Token-/Invite-Store (atomar geschrieben).

    Bewusst simpel gehalten (Datei statt DB): für ~2–20 Nutzer völlig
    ausreichend. Die Datei wird bei jedem Zugriff neu gelesen → Änderungen
    (revoke/invite) greifen sofort, ohne Container-Neustart.
    """

    def __init__(self, path=STORE_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()

    # -- Interna --
    def _empty(self) -> dict:
        return {"tokens": {}, "invites": {}}

    def _load(self) -> dict:
        with self._lock:
            if not self.path.exists():
                self._save(self._empty())
                return self._empty()
            return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(self.path)

    def ensure(self) -> None:
        self._load()

    # -- Tokens --
    def create_token(self, user_id: str, name: str = "") -> dict:
        with self._lock:
            data = self._load()
            token = "mcp_" + secrets.token_urlsafe(32)
            data["tokens"][token] = {
                "user_id": user_id,
                "name": name,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save(data)
            return {"token": token, "user_id": user_id, "name": name}

    def lookup(self, token: str) -> dict | None:
        if not token:
            return None
        return self._load()["tokens"].get(token)

    def revoke(self, token: str | None = None, user_id: str | None = None) -> int:
        with self._lock:
            data = self._load()
            count = 0
            if token and data["tokens"].pop(token, None):
                count += 1
            if user_id:
                for t in [t for t, e in data["tokens"].items() if e["user_id"] == user_id]:
                    data["tokens"].pop(t)
                    count += 1
            self._save(data)
            return count

    # -- Invites --
    def create_invite(self, user_id: str, name: str = "") -> dict:
        with self._lock:
            data = self._load()
            code = "invite_" + secrets.token_urlsafe(12)
            data["invites"][code] = {
                "user_id": user_id,
                "name": name,
                "used": False,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save(data)
            return {"invite_code": code, "user_id": user_id, "name": name}

    def redeem_invite(self, invite_code: str) -> dict | None:
        with self._lock:
            data = self._load()
            inv = data["invites"].get((invite_code or "").strip())
            if not inv or inv.get("used"):
                return None
            token = "mcp_" + secrets.token_urlsafe(32)
            data["tokens"][token] = {
                "user_id": inv["user_id"],
                "name": inv.get("name", ""),
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            inv["used"] = True
            self._save(data)
            return {"token": token, "user_id": inv["user_id"], "name": inv.get("name", "")}

    def list_all(self) -> dict:
        data = self._load()
        return {
            "tokens": [
                {"token": t[:12] + "…", "user_id": e["user_id"], "name": e.get("name", "")}
                for t, e in data["tokens"].items()
            ],
            "invites": [
                {
                    "invite_code": c,
                    "user_id": e["user_id"],
                    "name": e.get("name", ""),
                    "used": e.get("used", False),
                }
                for c, e in data["invites"].items()
            ],
        }


class BearerAuthMiddleware:
    """ASGI-Middleware: prüft Bearer-Token gegen den TokenStore.

    Token-frei (offen) sind nur /health und /register – die Registrierung
    ist selbst durch einmalige Invite-Codes gegated.
    """

    OPEN_PATHS = ("/health", "/register")

    def __init__(self, app, store: TokenStore, disabled: bool = False):
        self.app = app
        self.store = store
        self.disabled = disabled

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.disabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.rstrip("/") in self.OPEN_PATHS:
            await self.app(scope, receive, send)
            return

        token = self._bearer(scope)
        user = self.store.lookup(token) if token else None
        if user is None:
            await self._unauthorized(send)
            return

        # Identität für die Tools bereitstellen (ContextVar + scope-state).
        scope.setdefault("state", {})["user_id"] = user["user_id"]
        current_user.set(dict(user))
        await self.app(scope, receive, send)

    @staticmethod
    def _bearer(scope) -> str | None:
        for k, v in scope.get("headers", []):
            if k.decode("latin-1").lower() == "authorization":
                return v.decode("latin-1").removeprefix("Bearer ").strip() or None
        return None

    @staticmethod
    async def _unauthorized(send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})