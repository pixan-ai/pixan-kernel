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

# 1. Kernel guards, checked as root and again as the agent. Missing manifest in the image = tampered.
if [ -f "$KERNEL/kernel.sha256" ]; then
  (cd / && sha256sum --quiet -c "$KERNEL/kernel.sha256") || { log "ERROR: kernel guards were modified by a client layer"; exit 1; }
elif [ "$KERNEL" = /opt/kernel ]; then
  log "ERROR: kernel guards were modified by a client layer (manifest missing)"; exit 1
fi
# As root only: optional firewall, fix volume owner, drop privileges.
if [ "$(id -u)" -eq 0 ]; then
  if [ "${KERNEL_FIREWALL:-0}" = "1" ]; then "$KERNEL/firewall/init-firewall.sh" || { log "ERROR: firewall"; exit 1; }; fi
  mkdir -p "$WS" "$CFG/channels/telegram" && chown -R agent:agent "$DATA"
  exec runuser -u agent -- "$0"
fi
mkdir -p "$WS" "$CFG/channels/telegram"

# 2. Auth: the person's own credential, set in their own environment. Never logged or copied.
#    Resolved in Claude Code's own precedence, so the name we log/alert is the one actually used:
#    cloud (Bedrock/Vertex/Foundry) > ANTHROPIC_AUTH_TOKEN > ANTHROPIC_API_KEY > apiKeyHelper > OAuth token.
#    When anything outranks the OAuth token, the token is dropped from the environment so chat
#    and cron (`claude -p`) can never bill different accounts.
on() { [ -n "${!1:-}" ] && [ "${!1}" != 0 ] && [ "${!1}" != false ]; }
MANAGED="${MANAGED_SETTINGS:-/etc/claude-code/managed-settings.json}"
AUTH_VIA=""
for v in CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY; do
  on "$v" && { AUTH_VIA=$v; break; }
done
if [ -z "$AUTH_VIA" ]; then
  if [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then AUTH_VIA=ANTHROPIC_AUTH_TOKEN
  elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then AUTH_VIA=ANTHROPIC_API_KEY
  elif jq -e '.apiKeyHelper // empty' "$MANAGED" >/dev/null 2>&1; then AUTH_VIA=apiKeyHelper
  elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then AUTH_VIA=CLAUDE_CODE_OAUTH_TOKEN
  else
    log "MISSING credential: set one of CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY=1, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_API_KEY, apiKeyHelper or CLAUDE_CODE_OAUTH_TOKEN"; exit 1
  fi
fi
if [ "$AUTH_VIA" != CLAUDE_CODE_OAUTH_TOKEN ] && [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  log "WARN both $AUTH_VIA and CLAUDE_CODE_OAUTH_TOKEN are set: using $AUTH_VIA for chat and cron; CLAUDE_CODE_OAUTH_TOKEN is ignored"
  unset CLAUDE_CODE_OAUTH_TOKEN
fi
CHANNELS=1
case "$AUTH_VIA" in CLAUDE_CODE_USE_*)
  CHANNELS=0; log "WARN $AUTH_VIA: Telegram channels are not available on cloud providers; the agent runs WITHOUT Telegram" ;;
esac
export AUTH_VIA; log "auth: $AUTH_VIA"   # the variable name only, never its value
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
# (a) Onboarding + workspace trust merged in every boot (a fresh or half-written volume never
#     shows a first-run screen). The API key is pre-approved by its last 20 chars, as Claude records it.
[ -s "$CFG/.claude.json" ] || echo '{}' > "$CFG/.claude.json"
key="${ANTHROPIC_API_KEY:-}"
{ jq --arg ws "$WS" --arg k "${key: -20}" '
  .hasCompletedOnboarding = true
  | .projects[$ws] = ((.projects[$ws] // {}) + {hasTrustDialogAccepted: true, hasCompletedProjectOnboarding: true})
  | if $k == "" then . else .customApiKeyResponses.approved = (((.customApiKeyResponses.approved // []) - [$k]) + [$k]) end' \
  "$CFG/.claude.json" > "$CFG/.claude.json.tmp" && mv -f "$CFG/.claude.json.tmp" "$CFG/.claude.json"; } \
  || { log "ERROR: .claude.json"; exit 1; }

# 5. Telegram: bot token, and who may talk to the bot (owner only, first boot only).
printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN" > "$CFG/channels/telegram/.env"
[ -f "$CFG/channels/telegram/access.json" ] || sed "s|{{OWNER}}|$OWNER_TELEGRAM_ID|" "$SEED/access.json" > "$CFG/channels/telegram/access.json"
command -v claude >/dev/null || { log "ERROR: claude is not installed (build a client image)"; exit 1; }
# (b) Telegram plugin, in the foreground, before Claude starts. A client image may bake it in
#     /opt/client/config/plugins (refreshed every boot, so the plugin version follows the image digest);
#     otherwise it is installed once, only if missing.
PLUGIN_GLOB="$CFG/plugins/cache/claude-plugins-official/telegram/*/server.ts"
if [ "$CHANNELS" = 1 ]; then
  if [ -d /opt/client/config/plugins ]; then
    rm -rf "$CFG/plugins" && cp -r /opt/client/config/plugins "$CFG/plugins"
    find "$CFG/plugins" -maxdepth 1 -name '*.json' -exec sed -i "s|/opt/client/config|$CFG|g" {} +
  fi
  if ! compgen -G "$PLUGIN_GLOB" >/dev/null; then
    { claude plugin marketplace add anthropics/claude-plugins-official \
      && claude plugin install telegram@claude-plugins-official; } 2>&1 | sed 's/^/plugin: /'
    compgen -G "$PLUGIN_GLOB" >/dev/null || { log "ERROR: Telegram plugin could not be installed"; exit 1; }
  fi
  # (c) Kernel patches on the installed plugin (rich messages + last-inbound stamp).
  python3 "$KERNEL/bin/patch_rich_message.py" "$CFG/plugins/cache" 2>&1 | sed 's/^/rich-patch: /' || true
fi

# (d) Claude inside tmux (it needs a terminal). --continue resumes the previous conversation.
cd "$WS"
start() {
  t kill-server 2>/dev/null || true
  t new-session -d -s "$NAME" claude "$@" --dangerously-skip-permissions --channels plugin:telegram@claude-plugins-official
  sleep "${BOOT_WAIT_SEC:-10}"; t has-session -t "$NAME" 2>/dev/null
}
start --continue || start || { log "ERROR: claude did not start (auth: $AUTH_VIA)"; exit 1; }
# A first-run/picker screen (theme picker, any "Enter to confirm" menu) blocks the session.
# Sampled several times: one frame can be scrolled-back conversation text.
stuck=0
for _ in $(seq 1 "${STUCK_SAMPLES:-3}"); do
  grep -Eq 'Enter to confirm|Choose the text style' <<<"$(t capture-pane -t "$NAME" -p)" && stuck=$((stuck + 1))
  sleep "${STUCK_INTERVAL_SEC:-2}"
done
if [ "$stuck" -ge "${STUCK_SAMPLES:-3}" ]; then
  log "ERROR: claude is stuck waiting for input on screen (setup screen? check that $AUTH_VIA is valid)"; exit 1
fi

# 7. Heartbeat. Exits 1 (the platform restarts us) on: dead pane, Telegram server (bun server.ts)
#    gone, channel messages being dropped, or a TUI frozen mid-activity. A dead credential does
#    NOT restart (a restart cannot fix it): the owner gets one Telegram alert naming $AUTH_VIA.
#    Each beat also logs queued-message age and launches at most one due scheduled task.
AUTH_DEAD_RE='Invalid API key|OAuth access token is invalid|OAuth token has expired|authentication_error|disabled Claude subscription access|Credit balance is too low|Please run /login|login required'
ACTIVE_RE='esc to interrupt|(^|[^A-Za-z])(Thinking|Brewing)([^A-Za-z]|$)|● Running|Calling plugin|Calling tool'
DROP_RE='silently dropped|Messages are dropped'
alert_owner() {  # token goes through curl's stdin config, never on the command line
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TELEGRAM_BOT_TOKEN" \
    | curl -fsS --connect-timeout 8 --max-time 15 -K - -d "chat_id=$OWNER_TELEGRAM_ID" --data-urlencode "text=[$NAME] $1" >/dev/null 2>&1 \
    || log "WARN could not alert the owner on Telegram"
}
queue_age() {  # seconds a delivered message has waited with no transcript write after it, or "no"
  local inbound last
  inbound="$(stat -c %Y "$CFG/channels/telegram/last-inbound" 2>/dev/null || echo 0)"
  last="$(find "$CFG/projects" -name '*.jsonl' -printf '%T@\n' 2>/dev/null | sort -rn | head -n1)"
  if [ "$inbound" -gt "${last%.*}" ] 2>/dev/null || { [ -z "$last" ] && [ "$inbound" -gt 0 ]; }; then
    echo "$(( $(date +%s) - inbound ))s"; else echo no; fi
}
started=$(date +%s); freeze=0; last_hash=""; rm -f "$CFG/auth-dead"
log "started — heartbeat every ${HEARTBEAT_SEC:-30}s"
while sleep "${HEARTBEAT_SEC:-30}"; do
  [ "$(t list-panes -t "$NAME" -F '#{pane_dead}' 2>/dev/null)" = "0" ] || { log "ERROR: claude died"; exit 1; }
  date +%s > "$CFG/heartbeat"
  up=$(( $(date +%s) - started ))
  screen="$(t capture-pane -t "$NAME" -p -S -12 2>/dev/null | sed '/^[[:space:]]*$/d' | tail -n 8)"
  if [ "$CHANNELS" = 1 ] && [ "$up" -ge "${SERVER_GRACE_SEC:-90}" ]; then
    pgrep -u "$(id -u)" -f 'bun.*server\.ts' >/dev/null || { log "ERROR: Telegram server (bun server.ts) is not running"; exit 1; }
    ! grep -Eiq "$DROP_RE" <<<"$screen" || { log "ERROR: Telegram channel is dropping messages (see screen)"; exit 1; }
  fi
  hash="$(sha256sum <<<"$screen")"
  if grep -Eiq "$ACTIVE_RE" <<<"$screen" && ! grep -Eiq 'Brewed |Worked for|· done' <<<"$screen" \
     && [ "$hash" = "$last_hash" ]; then freeze=$((freeze + 1)); else freeze=0; fi
  last_hash="$hash"
  [ "$freeze" -lt "${FREEZE_CYCLES:-20}" ] || { log "ERROR: claude frozen mid-activity ($freeze identical beats)"; exit 1; }
  if grep -Eiq "$AUTH_DEAD_RE" <<<"$screen"; then
    if [ ! -f "$CFG/auth-dead" ]; then
      date +%s > "$CFG/auth-dead"; log "ERROR: credential rejected (auth: $AUTH_VIA); not restarting"
      alert_owner "Claude is rejecting the credential. Check that $AUTH_VIA is valid, then restart the agent."
    fi
  else rm -f "$CFG/auth-dead"; fi
  if [ "${KERNEL_CRON:-1}" = "1" ]; then
    cron_msg="$(python3 "$KERNEL/bin/cron.py" tick 2>&1 || true)"
    [ -z "$cron_msg" ] || log "cron: $cron_msg"
  fi
  log "heartbeat OK freeze=$freeze/${FREEZE_CYCLES:-20} queue=$(queue_age)"
done
