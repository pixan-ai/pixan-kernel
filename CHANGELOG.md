# Changelog

## 2026-11-04

### Batch 2a merged (#3, `7a8deb3`)
- Seeded `USER.md`, `STACK.md` and `MEMORY.md`, loaded via `@` imports; core identity files are locked against agent edits.
- Encrypted local backups (age) with optional client-side-encrypted Cloudflare R2 copy (`kernel/bin/backup.py`).
- Secret filter for backups and owner alerts (`kernel/bin/secret_filter.py`).
- Session reset without a container restart (`SESSION_RESET_IDLE_MIN`, `SESSION_RESET_HOUR`).
- Queue alert (`QUEUE_ALERT_SEC`, default 900 s) and per-tenant deny list (`/opt/client/tenant-deny.json`).
- Full SSRF guard: IPv4 embedded in IPv6 (mapped, 6to4, Teredo, NAT64), metadata host names, double DNS check.
- `/start` text overridable with `START_TEXT`; `kernel/smoke.sh` (ShellCheck-clean).
- CI on `main` publishes the exact image L2 tested to `ghcr.io/pixan-ai/pixan-kernel` (tags `:main`, `:sha-<commit>`; no `:latest`).

### Repository hardening
- `main` ruleset: pull request required; required checks L0, L1 and L2; deletion and force-push blocked; admin bypass kept as an accident guardrail.
- Private vulnerability reporting enabled.

### Docs
- README: Telegram access wording now states that deny rules cover Claude's file tools only; a shell command could still write `access.json`.
- README: documented image tags (`:main`, `:sha-<commit>`; no `:latest`).
