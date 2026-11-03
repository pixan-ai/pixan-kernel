#!/usr/bin/env bash
# Smoke test, run INSIDE a running agent container:  docker exec <container> /opt/kernel/smoke.sh
# Read-only: checks the agent is set up and alive. Exit 0 all good, 1 something is wrong.
set -uo pipefail
DATA="${DATA_DIR:-/data}"; KERNEL="${KERNEL_DIR:-/opt/kernel}"; NAME="${AGENT_NAME:-agent}"
fails=0
ok()   { printf 'ok    %s\n' "$1"; }
bad()  { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
info() { printf 'info  %s\n' "$1"; }
check() { local what="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$what"; else bad "$what"; fi; }

check "kernel guards intact" sh -c "cd / && sha256sum --quiet -c '$KERNEL/kernel.sha256'"
check "managed settings in place" test -s /etc/claude-code/managed-settings.json
check "volume writable" sh -c "touch '$DATA/.smoke' && rm -f '$DATA/.smoke'"
for f in CLAUDE.md SOUL.md IDENTITY.md USER.md STACK.md MEMORY.md; do
  check "workspace has $f" test -s "$DATA/workspace/$f"
done
for f in SOUL IDENTITY USER STACK MEMORY; do
  check "CLAUDE.md imports @$f.md" grep -qx "@$f.md" "$DATA/workspace/CLAUDE.md"
done
check "claude session running (tmux)" pgrep -f "tmux -L $NAME"
check "claude session runs as agent, not root" sh -c "! pgrep -u 0 -x claude"
if pgrep -f 'bun.*server\.ts' >/dev/null; then ok "Telegram server (bun) running"; else info "Telegram server not running (no channels, or still booting)"; fi
if [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  last="$(cat "$DATA/config/backup-last" 2>/dev/null || echo 0)"
  age=$(( $(date +%s) - ${last:-0} )); limit=$(( 2 * ${BACKUP_INTERVAL_SEC:-3600} + 120 ))
  if [ "$last" -gt 0 ] && [ "$age" -le "$limit" ]; then ok "last backup ${age}s ago"
  elif [ "$last" -eq 0 ]; then info "no backup yet (first one runs on the first heartbeat)"
  else bad "last backup ${age}s ago (more than ${limit}s)"; fi
else
  info "backups off (BACKUP_AGE_RECIPIENT not set)"
fi
[ "$fails" -eq 0 ] && echo "smoke: all good" || echo "smoke: $fails problem(s)"
[ "$fails" -eq 0 ]
