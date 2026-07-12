# redberry-webkit

Moduli condivisi, project-agnostic, per applicazioni FastAPI + NiceGUI. Estratti da
`cli_agent_bridge` dopo aver verificato drift reale su 7 progetti sibling (parametri
scrypt duplicati con valori diversi, posizione dei file diversa). Obiettivo: stesso
codice = stesso comportamento, importato una volta sola invece di rigenerato progetto
per progetto.

## Moduli

| Modulo | Cosa fa |
|---|---|
| `env_resolver` | `resolve_env_path()` — precedenza `ENV_FILE` (Docker) > `--env-file` (CLI) > `.env` più vicino |
| `auth` | `AuthManager` (JWT cookie session, scrypt password hashing, rate limit per-IP/globale) + `verify_api_token`, `is_secure_context`, `client_ip` |
| `config` | `ConfigManager` — `.env`-backed, hot-reload via mtime polling, scrivibile da UI (`update_many`) |
| `logging_utils` | `redact()` + `CredentialFilter` — scrubbing di password/token/secret dai log |
| `timezone_utils` | `resolve_timezone(tz_name)` — `ZoneInfo` sicuro, fallback UTC con warning |
| `credentials` | `watch_loop()` / `CredentialsStatus` — monitor generico di scadenza per un JSON di credenziali OAuth di un CLI esterno |
| `metrics` | `MetricsStore` — storico richieste async su SQLite (record/get_stats/get_history/purge_old), campo `extra` libero per dati project-specific |

Ogni modulo prende i valori project-specific (path, nomi cookie, TTL, campi JSON) come
parametri — il pacchetto fornisce il meccanismo, mai i valori.

## Installazione in un'app consumer

`requirements.txt`:

```
redberry-webkit @ git+https://github.com/daniloreddy/redberry-webkit.git@v0.2.0
```

```bash
pip install -r requirements.txt
```

Nome import (underscore, non trattino):

```python
from redberry_webkit.auth import AuthManager
from redberry_webkit.env_resolver import resolve_env_path
from redberry_webkit.config import ConfigManager
```

## Note operative

- **`AuthManager.verify_password()`/`set_password()` sono sincrone e CPU/memory-bound**
  (scrypt N=131072 → ~150-250ms, ~128MB per chiamata). In un handler FastAPI async,
  vanno eseguite via `asyncio.to_thread(...)`, non chiamate inline — vedi
  `redberry-webapp-template/app/ui/router.py.jinja` per il pattern di riferimento.
  Password impostate con versioni precedenti (N=16384) restano verificabili: i
  parametri KDF usati all'hashing sono persistiti in `auth.json`, non ricalcolati
  dal modulo corrente — non c'è re-hash automatico al login, solo al prossimo
  `set_password()`.
- **`ConfigManager.update_many()` valida chiavi e rifiuta newline nei valori** prima
  di scrivere su `.env` (protezione da injection quando il chiamante è una web UI).
  Chiavi non valide o valori con `\n`/`\r` vengono scartati silenziosamente (loggati
  a `warning`), non sollevano eccezione.

## Versionamento

Ogni fix/feature → nuovo tag semver (`vX.Y.Z`). Le app consumer aggiornano il pin nel
proprio `requirements.txt` esplicitamente — nessuna propagazione automatica.

## Sviluppo

```bash
scripts\checks.bat   # Windows
scripts/checks.sh    # Linux/Mac
```

Crea/attiva il venv, installa `requirements.dev.txt`, esegue `ruff check .`, `mypy redberry_webkit`, `pytest`.
