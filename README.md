# mem0-oss-mcp

**Eigenbetrieb von [Mem0](https://github.com/mem0ai/mem0) OSS als MCP-Server** – komplett lokal, keine Cloud, keine fremden API-Keys.

| Baustein | Wahl | Warum |
|---|---|---|
| Vector-Store | **Qdrant** (Docker, nur intern) | API-Key, hybride Suche (dense + BM25) |
| LLM | **Ollama nativ**, `qwen2.5:7b-instruct` | robustes JSON + stark auf Deutsch, kein "Thinking"-Overhead |
| Embeddings | **bge-m3** (1024 Dims) | multilingual → deutlich besser für deutsche Texte als nomic-embed-text |
| Transport | **MCP streamable HTTP** (`/mcp`, Port 8000) | netzwerkfähig: Cline, Claude Desktop, beliebige MCP-Clients |
| Auth | **persönliche Bearer-Tokens + Invite-Registrierung** | Token = Identität → Memories sind pro Nutzer automatisch getrennt |

```
Cline / Claude Desktop / jeder MCP-Client
      │  streamable HTTP + Bearer-Token (Token → user_id)
      ▼
mem0-mcp :8000  (nur an 127.0.0.1 gebunden)
      │                          │
      ▼                          ▼
Ollama (nativ unter Windows)   Qdrant (Docker, nur im
qwen2.5:7b-instruct            internen Netz, API-Key aktiv,
bge-m3 (Embeddings)            Collection "memories")
```

> Hinweis: Das offizielle `mem0ai/mem0-mcp` ist **archiviert** und zielt ausschließlich auf die gehostete Mem0-Platform (`MemoryClient(api_key=…)`, keine eigene Base-URL). Deshalb wrappt dieser Server hier Mem0 OSS direkt per `Memory.from_config()`.

## Voraussetzungen (Windows)

| Software | Wofür | Hinweis |
|---|---|---|
| Docker Desktop (WSL2) | Qdrant + MCP-Server | Ollama läuft **nativ**, nicht im Docker → spart RAM und WSL-Overhead |
| Ollama für Windows | LLM + Embeddings | <https://ollama.com/download> |
| (später) Tailscale | Funnel für Internet-Zugriff | nur auf dem hostenden Rechner – dein Kollege braucht **nichts** |

## Setup (erstmal lokal auf Windows)

Alles in PowerShell im Projektordner:

1. **`.env` anlegen**
   ```powershell
   Copy-Item .env.example .env
   ```
   In `.env` einen zufälligen `QDRANT_API_KEY` eintragen (z. B. 32+ zufällige Zeichen).

2. **Ollama-Modelle ziehen** (einmalig, ~5 GB):
   ```powershell
   ollama pull qwen2.5:7b-instruct
   ollama pull bge-m3
   ```

3. **Ollama-Kontextlänge erhöhen** – sonst schneidet Ollama Mem0s Extraction-Prompt still ab (Default `num_ctx` = 4096) und Fakten gehen verloren:
   ```powershell
   setx OLLAMA_CONTEXT_LENGTH 16384
   ```
   Danach Ollama beenden (Tray → Quit) und neu starten, damit die Variable greift.

4. **Stack starten**:
   ```powershell
   docker compose up -d --build
   ```
   Startet `qdrant` (intern) und `mem0-mcp` auf `http://localhost:8000`.

5. **Eigenen Token erzeugen** (du = Admin, keine Registrierung nötig):
   ```powershell
   docker compose exec mem0-mcp python manage.py token --user-id bojan --name Bojan
   ```
   Ausgabe `mcp_…` kopieren und sicher speichern.

6. **Check** – Health-Endpoint + MCP-Smoke-Test (add + search) im Container:
   ```powershell
   .\scripts\check.ps1 -Token <dein-token>
   ```

## MCP-Client einbinden

**Cline** – `cline_mcp_settings.json` (Vorlage: `client-config/cline.example.json`):

```json
{
  "mcpServers": {
    "mem0-oss": {
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer HIER_DEIN_TOKEN" }
    }
  }
}
```

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`), per `mcp-remote`:

```json
{
  "mcpServers": {
    "mem0-oss": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "http://localhost:8000/mcp",
        "--header", "Authorization: Bearer HIER_DEIN_TOKEN"
      ]
    }
  }
}
```

`localhost` funktioniert, solange Client und Server auf demselben Rechner laufen. Für Zugriff aus dem LAN: Server-IP eintragen, in `docker-compose.yml` auf `0.0.0.0:8000:8000` binden und den Port in der Windows-Firewall freigeben – **oder** direkt Funnel nehmen (unten), das ist die sauberere Variante.

## Kollegen einladen (einmalige Registrierung – kein Tailscale für ihn)

```text
1. Du:      .\scripts\new-user.ps1 -UserId max -Name "Max"   → druckt Invite-Code
2. Du:      Code + Registrierungs-URL einmalig an den Kollegen schicken
3. Kollege: http://<server>:8000/register im Browser öffnen, Code eingeben
4. Kollege: persönliches Token wird angezeigt → als
            "Authorization: Bearer …" in seine MCP-Config eintragen. Fertig.
```

- **Token = Identität:** Alles, was der Kollege speichert/sucht, läuft automatisch unter `user_id: max` – die Memories sind pro Nutzer getrennt, ohne dass jemand eine user_id angeben muss.
- Invite-Codes sind einmalig (`used: true` nach Einlösung) – ein Code kann genau ein Token ziehen.
- Widerruf wirkt sofort (tokens.json wird je Request neu gelesen): `docker compose exec mem0-mcp python manage.py revoke --user-id max`
- Verwaltung/Übersicht: `docker compose exec mem0-mcp python manage.py list` (Tokens maskiert)

## Ins Internet bringen: Tailscale Funnel (optional)

Wenn der Kollege ohne VPN und ohne Tailscale-Installation aus dem Internet zugreifen soll – **nur der Server** braucht Tailscale, der Kollege nur einen Browser:

```powershell
# 1. Tailscale installieren (https://tailscale.com/download), dann:
tailscale up            # Login im Browser
# 2. Funnel in der Admin-Console erlauben:
#    Access Controls → "Add Funnel to policy" (setzt nodeAttrs mit "funnel")
# 3. Öffentlich machen (HTTPS 443 → lokal 8000):
tailscale funnel 8000
```

Danach ist der Server öffentlich unter `https://<tailnet-name>.ts.net/` erreichbar (TLS-Zertifikat provisioniert Tailscale automatisch via Let's Encrypt).

- MCP-Config des Kollegen: `"url": "https://<tailnet-name>.ts.net/mcp"` + sein Bearer-Token.
- Nur der MCP-Port geht nach draußen – **Qdrant und Ollama bleiben im internen Docker-Netz** (kein `ports:`-Mapping, kein Funnel-Ziel).
- Schlägt `tailscale funnel` fehl, fehlt meist das Funnel-Attribut in der ACL (Admin-Console → „Add Funnel to policy").

## Betrieb & Wartung

| Thema | Kommando / Hinweis |
|---|---|
| Logs | `docker compose logs -f mem0-mcp` |
| Backups | Docker-Volumes `qdrant_data` (Memories) **und** `mcp_data` (`tokens.json` + `history.db` – der komplette Änderungsverlauf!) |
| Health | `.\scripts\check.ps1` (mit `-Token` inkl. MCP-Smoke-Test) |
| Chat-Modell wechsel | `.env`: `CHAT_MODEL` → `docker compose up -d` |
| Embedding wechseln | Dimensions-Check! `bge-m3`=1024, `nomic-embed-text`=768 (`EMBEDDING_DIMS`) + neue Collection (`COLLECTION_NAME`) |
| Update | `docker compose build --pull mem0-mcp; docker compose up -d` |
| Token-/Invite-Verwaltung | `docker compose exec mem0-mcp python manage.py --help` |

## Troubleshooting

| Symptom | Ursache | Lösung |
|---|---|---|
| Collection-Anlegen schlägt fehl / Dimensionsfehler | `EMBEDDING_DIMS` ≠ Modell-Dims | `bge-m3` → `1024`, `nomic-embed-text` → `768` |
| Extrahierte Fakten wirken zufällig unvollständig | Ollama-Default `num_ctx`=4096 schneidet Mem0s Extraction-Prompt still ab | `setx OLLAMA_CONTEXT_LENGTH 16384`, Ollama beenden (Tray → Quit) und neu starten |
| `mem0-mcp` erreicht Ollama nicht | `host.docker.internal` | Docker Desktop läuft? `OLLAMA_BASE_URL` in `.env` prüfen |
| 401 bei MCP-Requests | Token falsch/verrutscht | neu erzeugen: `docker compose exec mem0-mcp python manage.py token --user-id …` |
| Qdrant/Ollama von außen erreichbar? | – | Soll es **nicht** sein: kein `ports:`-Mapping für `qdrant`; nur `mem0-mcp` veröffentlicht 8000 (nur an `127.0.0.1`) |

## Projektstruktur

```text
mem0-oss-mcp/
├── docker-compose.yml         # qdrant (nur intern) + mem0-mcp; Ollama nativ unter Windows
├── .env.example               # Vorlage: QDRANT_API_KEY, Modelle, …
├── README.md
├── mcp_server/                # MCP-Server (Docker-Image)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── auth.py               # Token-/Invite-Store + Bearer-Middleware
│   ├── mcp_server.py          # MCP-Tools + /health + /register
│   ├── manage.py              # CLI: token / invite / list / revoke
│   └── smoke_test.py          # echter MCP-Client als Smoke-Test
├── client-config/cline.example.json
└── scripts/
    ├── new-user.ps1           # Invite/Token für Kollegen anlegen
    └── check.ps1              # Health + optional MCP-Smoke-Test
```

## Design-Entscheidungen & Grenzen

- **Ollama nativ unter Windows** (nicht im Docker): spart WSL-RAM und hält die GPU-Nutzung simpel – das Compose-Profil `ollama-docker` ist für den späteren Linux-Server-Betrieb vorgesehen (dort `OLLAMA_BASE_URL=http://ollama:11434` setzen und `docker compose --profile ollama-docker up -d`).
- **`qwen2.5:7b-instruct`** (Q4, ~4,7 GB): robuste JSON-Fact-Extraction, stark auf Deutsch, kein „Thinking"-Overhead (Qwen3 denkt per Default mit, ohne dass Mem0 das abschaltet). Für mehr Tempo: `qwen2.5:3b`; für Volllast-Server später: `qwen3:8b`.
- **`bge-m3`** (1024 Dims): multilingual – für deutsche Memories deutlich bessere Treffer als englisch trainierte Embeddings wie `nomic-embed-text`.
- **Token = Identität** statt Login/Sessions: keine Passwörter, keine Nutzerverwaltung – Tokens sind ≥ 32 Bytes Zufall, per `tokens.json` administrierbar. Grenze: ~20 Nutzer; darüber → echte DB.
- **`MCP_AUTH_DISABLED=true`** nur für lokale Experimente – niemals zusammen mit Funnel oder Portfreigabe.
- Der offizielle `mem0ai/mem0-mcp`-Server ist archiviert und spricht ausschließlich die gehostete Mem0-Platform an (`MemoryClient` ohne eigene Base-URL) – deshalb dieser eigene, kompakte Wrapper um `Memory.from_config()`.