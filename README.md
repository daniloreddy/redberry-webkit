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

Ogni modulo prende i valori project-specific (path, nomi cookie, TTL, campi JSON) come
parametri — il pacchetto fornisce il meccanismo, mai i valori.

## Installazione in un'app consumer

`requirements.txt`:

```
redberry-webkit @ git+https://github.com/daniloreddy/redberry-webkit.git@v0.1.0
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

## Versionamento

Ogni fix/feature → nuovo tag semver (`vX.Y.Z`). Le app consumer aggiornano il pin nel
proprio `requirements.txt` esplicitamente — nessuna propagazione automatica.

## Sviluppo

```bash
scripts\checks.bat   # Windows
scripts/checks.sh    # Linux/Mac
```

Crea/attiva il venv, installa `requirements.dev.txt`, esegue `ruff check .`, `mypy redberry_webkit`, `pytest`.
