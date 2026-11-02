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
#    Claude itself reports which credential it uses (`claude auth status`, JSON); we log only its name.
command -v claude >/dev/null || { log "ERROR: claude is not installed (build a client image)"; exit 1; }
if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  log "WARN both ANTHROPIC_API_KEY and CLAUDE_CODE_OAUTH_TOKEN are set: using ANTHROPIC_API_KEY for chat and cron; CLAUDE_CODE_OAUTH_TOKEN is ignored"
  unset CLAUDE_CODE_OAUTH_TOKEN
fi
status="$(claude auth status 2>/dev/null || true)"
jq -e '.loggedIn == true' >/dev/null 2>&1 <<<"$status" || { log "MISSING credential: claude auth status reports not logged in"; exit 1; }
# A cloud provider is named by its provider even when an API key is also set (the CLI then
# still reports apiKeySource); only firstParty is named by the credential itself.
AUTH_VIA="$(jq -r 'if .apiProvider == "firstParty" then (.apiKeySource // .authMethod) else .apiProvider end' <<<"$status")"; CHANNELS=1
if [ "$(jq -r .apiProvider <<<"$status")" != firstParty ]; then
  CHANNELS=0; log "WARN $AUTH_VIA: Telegram channels need the Anthropic API; the agent runs WITHOUT Telegram"
fi
export AUTH_VIA; log "auth: $AUTH_VIA"   # the credential's name only, never its value
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

# 5. Telegram: who may talk to the bot (owner only, first boot only). The plugin reads the token from env.
[ -f "$CFG/channels/telegram/access.json" ] || sed "s|{{OWNER}}|$OWNER_TELEGRAM_ID|" "$SEED/access.json" > "$CFG/channels/telegram/access.json"
# (b) Telegram plugin, baked by the client image in /opt/client/config/plugins and refreshed every boot
#     (so the plugin version follows the image digest). Never installed at runtime.
PLUGIN_GLOB="$CFG/plugins/cache/claude-plugins-official/telegram/*/server.ts"
if [ "$CHANNELS" = 1 ]; then
  if [ -d /opt/client/config/plugins ]; then
    rm -rf "$CFG/plugins" && cp -r /opt/client/config/plugins "$CFG/plugins"
    find "$CFG/plugins" -maxdepth 1 -name '*.json' -exec sed -i "s|/opt/client/config|$CFG|g" {} +
  fi
  compgen -G "$PLUGIN_GLOB" >/dev/null || { log "ERROR: Telegram plugin missing (bake it in the client image)"; exit 1; }
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
if grep -Eq 'Enter to confirm|Choose the text style' <<<"$(t capture-pane -t "$NAME" -p)"; then
  log "ERROR: claude is stuck waiting for input on screen (setup screen? check that $AUTH_VIA is valid)"; exit 1
fi

# 7. Heartbeat. A rejected credential, or a Telegram channel that is off or dropping messages, does
#    NOT restart (a restart cannot fix it): the owner gets one Telegram alert naming $AUTH_VIA,
#    re-sent at most every 24 h (the stamp lives on /data, so it survives restarts). Otherwise exits 1
#    (the platform restarts us) on: dead pane, Telegram server (bun server.ts) gone, or a TUI frozen
#    mid-activity. Each beat also logs queued-message age and launches at most one due scheduled task.
AUTH_DEAD_RE='Invalid API key|authentication rejected \(401\)|OAuth access token is invalid|OAuth token has expired|authentication_error|disabled Claude subscription access|Credit balance is too low|Please run /login|login required'
# Channel notices: only on their own lines, and only after SERVER_GRACE_SEC (policy may still be loading).
CHANNEL_RE='^[^[:alnum:]-]*(Messages are dropped until it loads|Channels are not currently available|--channels ignored( \(.*\))?|.*silently dropped)\.?[[:space:]]*$'
AUTH_STAMP="$CFG/auth-alerted"; AUTH_REALERT_SEC="${AUTH_REALERT_SEC:-86400}"
ACTIVE_RE='esc to interrupt|(^|[^A-Za-z])(Thinking|Brewing)([^A-Za-z]|$)|● Running|Calling plugin|Calling tool'
alert_owner() {  # token goes through curl's stdin config, never on the command line; returns curl's status
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TELEGRAM_BOT_TOKEN" \
    | curl -fsS --connect-timeout 8 --max-time 15 -K - -d "chat_id=$OWNER_TELEGRAM_ID" --data-urlencode "text=[$NAME] $1" >/dev/null 2>&1 \
    || { local rc=$?; log "WARN could not alert the owner on Telegram (will retry next beat)"; return "$rc"; }
}
alert_once() {  # one owner alert per $AUTH_REALERT_SEC, shared by the credential and channel checks
  local last_alert; last_alert="$(cat "$AUTH_STAMP" 2>/dev/null || true)"; case "$last_alert" in ''|*[!0-9]*) last_alert=0 ;; esac
  [ $(( $(date +%s) - last_alert )) -ge "$AUTH_REALERT_SEC" ] || return 0
  log "ERROR: $1 (auth: $AUTH_VIA); not restarting"
  if alert_owner "Telegram is not working: check that $AUTH_VIA is valid and channels are enabled."; then
    date +%s > "$AUTH_STAMP"; fi  # stamp only once the owner was told; otherwise retry next beat
}
queue_age() {  # seconds a delivered message has waited with no transcript write after it, or "no"
  local inbound last
  inbound="$(stat -c %Y "$CFG/channels/telegram/last-inbound" 2>/dev/null || echo 0)"
  last="$(find "$CFG/projects" -name '*.jsonl' -printf '%T@\n' 2>/dev/null | sort -rn | head -n1)"
  if [ "$inbound" -gt "${last%.*}" ] 2>/dev/null || { [ -z "$last" ] && [ "$inbound" -gt 0 ]; }; then
    echo "$(( $(date +%s) - inbound ))s"; else echo no; fi
}
started=$(date +%s); freeze=0; last_hash=""
log "started — heartbeat every ${HEARTBEAT_SEC:-30}s"
while sleep "${HEARTBEAT_SEC:-30}"; do
  [ "$(t list-panes -t "$NAME" -F '#{pane_dead}' 2>/dev/null)" = "0" ] || { log "ERROR: claude died"; exit 1; }
  up=$(( $(date +%s) - started ))
  screen="$(t capture-pane -t "$NAME" -p -S -12 2>/dev/null | sed '/^[[:space:]]*$/d' | tail -n 8)"
  problem=""
  ! grep -Eiq -e "$AUTH_DEAD_RE" <<<"$screen" || problem="credential rejected"
  if [ "$CHANNELS" = 1 ] && [ "$up" -ge "${SERVER_GRACE_SEC:-90}" ]; then
    pgrep -u "$(id -u)" -f 'bun.*server\.ts' >/dev/null || { log "ERROR: Telegram server (bun server.ts) is not running"; exit 1; }
    [ -n "$problem" ] || ! grep -Eiq -e "$CHANNEL_RE" <<<"$screen" || problem="Telegram channel is not working (see screen)"
  fi
  # A clean screen once past the grace period proves the credential works: clear the stamp.
  if [ -n "$problem" ]; then alert_once "$problem"; elif [ "$up" -ge "${SERVER_GRACE_SEC:-90}" ]; then rm -f "$AUTH_STAMP"; fi
  hash="$(sha256sum <<<"$screen")"
  if grep -Eiq "$ACTIVE_RE" <<<"$screen" && ! grep -Eiq 'Brewed |Worked for|· done' <<<"$screen" \
     && [ "$hash" = "$last_hash" ]; then freeze=$((freeze + 1)); else freeze=0; fi
  last_hash="$hash"
  [ "$freeze" -lt "${FREEZE_CYCLES:-20}" ] || { log "ERROR: claude frozen mid-activity ($freeze identical beats)"; exit 1; }
  if [ "${KERNEL_CRON:-1}" = "1" ]; then
    cron_msg="$(python3 "$KERNEL/bin/cron.py" tick 2>&1 || true)"
    [ -z "$cron_msg" ] || log "cron: $cron_msg"
  fi
  if [ -n "$problem" ]; then log "heartbeat AUTH-DEAD auth=$AUTH_VIA ($problem; alerted, not restarting)"
  else log "heartbeat OK freeze=$freeze/${FREEZE_CYCLES:-20} queue=$(queue_age)"; fi
done
