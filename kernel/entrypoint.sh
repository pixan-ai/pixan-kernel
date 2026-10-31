#!/usr/bin/env bash
# Boot: guards → volume → auth → seed → Claude in tmux → heartbeat (+ cron tick).
set -euo pipefail
NAME="${AGENT_NAME:-agent}"
LANGUAGE="${AGENT_LANGUAGE:-English}"
DATA="${DATA_DIR:-/data}"; KERNEL="${KERNEL_DIR:-/opt/kernel}"; SEED="$KERNEL/seed"
WS="$DATA/workspace"; CFG="$DATA/config"
log() { printf '[%s] %s\n' "$NAME" "$*"; }
t() { tmux -L "$NAME" "$@"; }   # own tmux server per agent
fill() { sed -e "s|{{AGENT_NAME}}|$NAME|g" -e "s|{{AGENT_LANGUAGE}}|$LANGUAGE|g" "$1"; }

# 1. As root only: verify kernel guards, optional firewall, fix volume owner, drop privileges.
if [ "$(id -u)" -eq 0 ]; then
  if ! (cd / && sha256sum --quiet -c "$KERNEL/kernel.sha256"); then
    log "ERROR: kernel guards were modified by a client layer"; exit 1
  fi
  if [ "${KERNEL_FIREWALL:-0}" = "1" ]; then "$KERNEL/firewall/init-firewall.sh" || { log "ERROR: firewall"; exit 1; }; fi
  mkdir -p "$WS" "$CFG/channels/telegram" && chown -R agent:agent "$DATA"
  exec runuser -u agent -- "$0"
fi
mkdir -p "$WS" "$CFG/channels/telegram"

# 2. Auth: the client's own API key (or Bedrock/Vertex). Subscription OAuth is refused.
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  log "REFUSED CLAUDE_CODE_OAUTH_TOKEN: use ANTHROPIC_API_KEY, Bedrock or Vertex"; exit 1
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ "${CLAUDE_CODE_USE_BEDROCK:-}" != 1 ] && [ "${CLAUDE_CODE_USE_VERTEX:-}" != 1 ]; then
  log "MISSING ANTHROPIC_API_KEY (or CLAUDE_CODE_USE_BEDROCK=1 / CLAUDE_CODE_USE_VERTEX=1)"; exit 1
fi
for v in TELEGRAM_BOT_TOKEN OWNER_TELEGRAM_ID; do
  [ -n "${!v:-}" ] || { log "MISSING $v"; exit 1; }   # presence only; values never printed
done

# 3. Instructions: CLAUDE.md rewritten every boot; SOUL, IDENTITY and skills only if missing.
#    A client image may ship its own in /opt/client/workspace (they win over kernel seeds).
fill "$SEED/workspace/CLAUDE.md" > "$WS/CLAUDE.md"
for f in SOUL.md IDENTITY.md; do
  src="$SEED/workspace/$f"; [ -f "/opt/client/workspace/$f" ] && src="/opt/client/workspace/$f"
  [ -f "$WS/$f" ] || fill "$src" > "$WS/$f"
done
mkdir -p "$WS/.claude/skills"
for d in "$SEED"/workspace/.claude/skills/* /opt/client/workspace/.claude/skills/*; do
  [ -d "$d" ] && [ ! -e "$WS/.claude/skills/$(basename "$d")" ] && cp -r "$d" "$WS/.claude/skills/"
done

# 4. User settings (plugins) re-imposed every boot. Deny rules and hooks live in
#    /etc/claude-code/managed-settings.json, which the agent cannot edit.
cp -f "$SEED/settings.json" "$CFG/settings.json"
# Optional advisor tool (experimental, OFF unless PIXAN_ADVISOR_MODEL is set: opus|sonnet|full id).
# Set via the advisorModel setting, not --advisor, so a bad pairing never blocks the boot.
if [ -n "${PIXAN_ADVISOR_MODEL:-}" ]; then
  jq --arg m "$PIXAN_ADVISOR_MODEL" '.advisorModel = $m' "$SEED/settings.json" > "$CFG/settings.json"
  log "advisor: $PIXAN_ADVISOR_MODEL (experimental, may use more tokens)"
fi
umask 077
key="${ANTHROPIC_API_KEY:-}"
[ -f "$CFG/.claude.json" ] || printf '{"hasCompletedOnboarding":true,"customApiKeyResponses":{"approved":["%s"]},"projects":{"%s":{"hasTrustDialogAccepted":true,"hasCompletedProjectOnboarding":true}}}\n' \
  "${key: -20}" "$WS" > "$CFG/.claude.json"

# 5. Telegram: bot token, and who may talk to the bot (owner only, first boot only).
printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN" > "$CFG/channels/telegram/.env"
[ -f "$CFG/channels/telegram/access.json" ] || sed "s|{{OWNER}}|$OWNER_TELEGRAM_ID|" "$SEED/access.json" > "$CFG/channels/telegram/access.json"
python3 "$KERNEL/bin/patch_rich_message.py" "$CFG/plugins/cache" 2>&1 | sed 's/^/rich-patch: /' || true

# 6. Claude inside tmux (it needs a terminal). --continue resumes the previous conversation.
command -v claude >/dev/null || { log "ERROR: claude is not installed (build a client image)"; exit 1; }
cd "$WS"
start() {
  t kill-server 2>/dev/null || true
  t new-session -d -s "$NAME" claude "$@" --dangerously-skip-permissions --channels plugin:telegram@claude-plugins-official
  sleep "${BOOT_WAIT_SEC:-10}"; t has-session -t "$NAME" 2>/dev/null
}
start --continue || start || { log "ERROR: claude did not start"; exit 1; }
if t capture-pane -t "$NAME" -p | grep -Eq 'Do you want|Press Enter|/login|\(Y/n\)'; then
  log "ERROR: claude is stuck waiting for input on screen"; exit 1
fi

# 7. Heartbeat: a dead pane exits 1 (zombie != alive) so the platform restarts us.
#    Each beat also launches at most one due scheduled task, in a separate `claude -p`.
log "started — heartbeat every ${HEARTBEAT_SEC:-30}s"
while sleep "${HEARTBEAT_SEC:-30}"; do
  [ "$(t list-panes -t "$NAME" -F '#{pane_dead}' 2>/dev/null)" = "0" ] || { log "ERROR: claude died"; exit 1; }
  date +%s > "$CFG/heartbeat"
  if [ "${KERNEL_CRON:-1}" = "1" ]; then
    cron_msg="$(python3 "$KERNEL/bin/cron.py" tick 2>&1 || true)"
    [ -z "$cron_msg" ] || log "cron: $cron_msg"
  fi
  log "heartbeat OK"
done
