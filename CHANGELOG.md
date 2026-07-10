# Changelog

## v0.1.0

- Initial extraction from `cli_agent_bridge`: `env_resolver`, `auth` (AuthManager, JWT cookie sessions, scrypt password hashing, per-IP/global rate limiting), `config` (ConfigManager, hot-reloadable `.env`-backed settings), `logging_utils` (secret redaction), `timezone_utils` (safe `ZoneInfo` resolution), `credentials` (generic CLI-tool OAuth expiry watcher).
