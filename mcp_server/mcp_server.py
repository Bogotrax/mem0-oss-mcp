"""
Mem0-OSS-MCP-Server
===================

Wrappt Mem0 OSS (Qdrant + Ollama) als MCP-Server (streamable HTTP, Port 8000)
mit Bearer-Token-Auth und Einmal-Registrierung per Invite-Code (/register).

Alle Einstellungen laufen über Umgebungsvariablen
(siehe README.md und docker-compose.yml / .env.example).
"""

import os

os.environ.setdefault("MEM0_TELEMETRY", "false")  # Privatsphäre by default

import asyncio

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import HTMLResponse, JSONResponse

from mem0 import Memory

from auth import BearerAuthMiddleware, TokenStore, current_user

# --------------------------------------------------------------------------
# Konfiguration (Env)
# --------------------------------------------------------------------------
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "memories")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:7b-instruct")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", "1024"))
DEFAULT_USER_ID = os.getenv("MEM0_DEFAULT_USER_ID", "default")
HISTORY_DB_PATH = os.getenv("HISTORY_DB_PATH", "/data/history.db")
AUTH_DISABLED = os.getenv("MCP_AUTH_DISABLED", "false").lower() == "true"

memory = Memory.from_config(
    {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": COLLECTION_NAME,
                "host": QDRANT_HOST,
                "port": QDRANT_PORT,
                "api_key": QDRANT_API_KEY,
                "on_disk": True,
                # Qdrant lauscht nur auf HTTP im internen Docker-Netz; ohne
                # explizites "https": False wuerde der qdrant-client wegen
                # des API-Keys versuchen, per TLS zu verbinden (prefer_https).
                "https": False,
                # MUSS zum Embedding-Modell passen (bge-m3=1024, nomic-embed-text=768)!
                "embedding_model_dims": EMBEDDING_DIMS,
            },
        },
        "llm": {
            "provider": "ollama",
            "config": {
                "model": CHAT_MODEL,
                "temperature": 0,
                "max_tokens": 2000,
                "ollama_base_url": OLLAMA_BASE_URL,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {"model": EMBEDDING_MODEL, "ollama_base_url": OLLAMA_BASE_URL},
        },
        "history_db_path": HISTORY_DB_PATH,
    }
)

# Transport-Security EXPLIZIT setzen – nicht dem SDK-Default überlassen:
# FastMCP aktiviert bei host=127.0.0.1 (Default) automatisch DNS-Rebinding-Schutz
# mit localhost-only allowed_hosts → hinter TLS-Proxies (Tailscale Funnel,
# Caddy) lehnt /mcp jeden fremden Host-Header mit HTTP 421 ab.
# MCP_ALLOWED_HOSTS (kommagetrennt) gesetzt → Check aktiv mit diesen Hosts;
# leer (Default) → Check aus. Das ist sicher: /mcp schützt die
# Bearer-Token-Middleware, TLS übernimmt der Proxy (Funnel).
_ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
]
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=bool(_ALLOWED_HOSTS),
    allowed_hosts=_ALLOWED_HOSTS,
)

try:
    # stateless_http: jeder Request wird unabhängig behandelt → die per-Request
    # gesetzte Token-Identität (ContextVar) erreicht die Tools zuverlässig.
    mcp = FastMCP(
        name="mem0-oss",
        stateless_http=True,
        transport_security=_transport_security,
    )
except TypeError:  # älteres mcp-SDK ohne stateless_http/transport_security
    mcp = FastMCP(name="mem0-oss")

STORE = TokenStore()


def _resolve_user(user_id: str | None) -> str:
    """Expliziter Parameter gewinnt, sonst Token-Identität, sonst Default."""
    if user_id:
        return user_id
    cur = current_user.get()
    return cur["user_id"] if cur else DEFAULT_USER_ID


# --------------------------------------------------------------------------
# MCP-Tools (blockierende Mem0-Aufrufe via to_thread – Event-Loop frei halten)
# --------------------------------------------------------------------------


@mcp.tool()
async def add_memory(text: str, user_id: str | None = None) -> dict:
    """Speichert Fakten aus einem Text oder Chat-Verlauf im Langzeitgedächtnis.

    text kann ein einzelner Satz oder eine ganze Chat-Historie sein; Mem0
    extrahiert die Fakten automatisch per lokalem LLM (dauert ein paar
    Sekunden). user_id normalerweise weglassen – wird aus dem Bearer-Token
    abgeleitet.
    """
    return await asyncio.to_thread(memory.add, text, user_id=_resolve_user(user_id))


@mcp.tool()
async def search_memories(query: str, top_k: int = 5, user_id: str | None = None) -> dict:
    """Semantische Suche im Langzeitgedächtnis – relevanteste Memories zuerst."""
    return await asyncio.to_thread(
        memory.search, query, filters={"user_id": _resolve_user(user_id)}, top_k=top_k
    )


@mcp.tool()
async def get_memories(user_id: str | None = None) -> dict:
    """Listet ALLE Memories eines Nutzers auf (ohne semantische Suche)."""
    return await asyncio.to_thread(
        memory.get_all, filters={"user_id": _resolve_user(user_id)}
    )


@mcp.tool()
async def get_memory(memory_id: str) -> dict:
    """Holt genau einen Memory anhand seiner ID."""
    return await asyncio.to_thread(memory.get, memory_id=memory_id)


@mcp.tool()
async def update_memory(memory_id: str, text: str) -> dict:
    """Überschreibt den Inhalt eines Memories (memory_id vorher beim Nutzer erfragen)."""
    return await asyncio.to_thread(memory.update, memory_id=memory_id, data=text)


@mcp.tool()
async def delete_memory(memory_id: str) -> dict:
    """Löscht einen einzelnen Memory (memory_id vorher vom Nutzer bestätigen lassen)."""
    return await asyncio.to_thread(memory.delete, memory_id=memory_id)


@mcp.tool()
async def delete_all_memories(user_id: str | None = None) -> dict:
    """Löscht ALLE Memories eines Nutzers – nur nach expliziter Bestätigung ausführen!"""
    return await asyncio.to_thread(
        memory.delete_all, filters={"user_id": _resolve_user(user_id)}
    )


@mcp.tool()
async def memory_history(memory_id: str) -> dict:
    """Zeigt den Änderungsverlauf (ADD/UPDATE/DELETE) eines Memories."""
    return await asyncio.to_thread(memory.history, memory_id=memory_id)


# --------------------------------------------------------------------------
# HTTP-Routen (token-frei): /health und /register
# --------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    """Health-Check: Erreichbarkeit von Ollama + Qdrant."""
    info = {"service": "ok"}
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            info["ollama"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception:
            info["ollama"] = "unreachable"
        try:
            headers = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
            r = await client.get(
                f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections", headers=headers
            )
            info["qdrant"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception:
            info["qdrant"] = "unreachable"
    return JSONResponse(
        info, status_code=200 if all(v == "ok" for v in info.values()) else 503
    )


_PAGE = (
    "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
    "<title>Mem0-Zugang</title><style>"
    "body{font-family:system-ui,sans-serif;max-width:420px;margin:60px auto;padding:0 16px}"
    "input,button{font-size:1rem;padding:8px}"
    "</style></head><body><h2>&#128273; Mem0-Zugang</h2>"
    "<p>Einmaligen Invite-Code eingeben, um ein pers&ouml;nliches Token zu erhalten:</p>"
    "<form method='post'><input name='invite_code' placeholder='invite_&hellip;' required>"
    "<button type='submit'>Token erzeugen</button></form></body></html>"
)


@mcp.custom_route("/register", methods=["GET"])
async def register_form(_request):
    return HTMLResponse(_PAGE)


@mcp.custom_route("/register", methods=["POST"])
async def register_submit(request):
    ctype = request.headers.get("content-type") or ""
    wants_json = ctype.startswith("application/json") or (
        request.headers.get("accept") or ""
    ).startswith("application/json")
    if ctype.startswith("application/json"):
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        data = dict(await request.form())

    result = STORE.redeem_invite(str(data.get("invite_code", "")))
    if not result:
        msg = "Invite-Code ungültig oder bereits benutzt."
        if wants_json:
            return JSONResponse({"error": msg}, status_code=400)
        return HTMLResponse(
            f"<h3>&#10060; {msg}</h3><p><a href='/register'>Nochmal versuchen</a></p>",
            status_code=400,
        )
    if wants_json:
        return JSONResponse(result)
    return HTMLResponse(
        "<h2>&#9989; Token erstellt</h2>"
        "<p>Dein pers&ouml;nliches Token (sicher speichern – wird nur einmal angezeigt):</p>"
        f"<p><code>{result['token']}</code></p>"
        "<p>Im MCP-Client als HTTP-Header hinterlegen:<br>"
        f"<code>Authorization: Bearer {result['token']}</code></p>"
        "<p>MCP-Endpoint: <code>/mcp</code></p>"
    )


# --------------------------------------------------------------------------
# App zusammenbauen. Wichtig: streamable_http_app() erst NACH Registrierung
# aller custom_routes aufrufen (deshalb Funktion, nicht auf Modul-Ebene).
# --------------------------------------------------------------------------


def create_app():
    return BearerAuthMiddleware(mcp.streamable_http_app(), STORE, disabled=AUTH_DISABLED)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8000")))