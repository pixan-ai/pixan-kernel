#!/usr/bin/env bash
# L1 — the entrypoint on this machine, with a stub `claude` and a temp volume.
# Needs bash and tmux; no Docker, no network, no real keys.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=tests/lib.sh
. tests/lib.sh

tmp="$(mktemp -d)"; trap 'tmux -L "k-l1-$$" kill-server 2>/dev/null; rm -rf "$tmp"' EXIT
export PATH="$PWD/tests/stubs:$PATH" KERNEL_DIR="$PWD/kernel" DATA_DIR="$tmp/data" TMUX_TMPDIR="$tmp" \
       CLAUDE_CONFIG_DIR="$tmp/data/config" AGENT_NAME="k-l1-$$" BOOT_WAIT_SEC=1 HEARTBEAT_SEC=1 \
       CURL_LOG="$tmp/curl"
keys=(ANTHROPIC_API_KEY=sk-ant-test-0000000000000000000000 TELEGRAM_BOT_TOKEN=fake-bot OWNER_TELEGRAM_ID=42)
# Stands in for the plugin a client image bakes (no /opt/client here).
bake() { mkdir -p "$DATA_DIR/config/plugins/cache/claude-plugins-official/telegram/0.0.1" \
  && touch "$DATA_DIR/config/plugins/cache/claude-plugins-official/telegram/0.0.1/server.ts"; }
boot() { bake; env "$@" ./kernel/entrypoint.sh > "$tmp/out" 2>&1; }

base=(TELEGRAM_BOT_TOKEN=fake-bot OWNER_TELEGRAM_ID=42)
boot "${base[@]}" STUB_CLAUDE=exit
check "no credential: fails fast with MISSING" grep -q 'MISSING credential' "$tmp/out"
check "no credential: writes nothing" test ! -e "$DATA_DIR/workspace/CLAUDE.md"

boot "${base[@]}" CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-test-1111111111111111 STUB_CLAUDE=exit
check "OAuth only: boots past auth (name from claude auth status)" grep -q 'auth: oauth_token' "$tmp/out"
check "OAuth only: onboarding and trust seeded" grep -q '"hasTrustDialogAccepted": true' "$DATA_DIR/config/.claude.json"
check "OAuth only: no approved key entry" absent customApiKeyResponses "$(cat "$DATA_DIR/config/.claude.json")"
check "OAuth only: token never written to the volume" absent 1111111111111111 "$(cat "$tmp/out"; grep -r . "$DATA_DIR" 2>/dev/null)"
check "dead claude: alert names the credential in use" grep -q 'did not start (auth: oauth_token)' "$tmp/out"
rm -rf "$DATA_DIR"

boot "${keys[@]}" CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-test-1111111111111111 STUB_CLAUDE=exit
check "both set: warns" grep -q 'WARN both ANTHROPIC_API_KEY and CLAUDE_CODE_OAUTH_TOKEN' "$tmp/out"
check "both set: API key wins" grep -q 'auth: ANTHROPIC_API_KEY' "$tmp/out"
check "both set: key pre-approved" grep -q '"00000000000000000000"' "$DATA_DIR/config/.claude.json"
check "both set: no secret value in the log" absent 0000000000 "$(cat "$tmp/out")"
rm -rf "$DATA_DIR"

boot "${base[@]}" CLAUDE_CODE_USE_BEDROCK=1 STUB_CLAUDE=exit
check "cloud: name from claude auth status" grep -q 'auth: bedrock' "$tmp/out"
check "cloud: warns there are no Telegram channels" grep -q 'WARN bedrock: Telegram channels need the Anthropic API' "$tmp/out"
rm -rf "$DATA_DIR"
boot "${keys[@]}" CLAUDE_CODE_USE_BEDROCK=1 STUB_CLAUDE=exit
check "cloud + API key: named by the provider, not the key" grep -q 'auth: bedrock$' "$tmp/out"
rm -rf "$DATA_DIR"
mkdir -p "$DATA_DIR"; env "${keys[@]}" STUB_CLAUDE=exit ./kernel/entrypoint.sh > "$tmp/out" 2>&1
check "plugin not baked: exits with error" grep -q 'ERROR: Telegram plugin missing' "$tmp/out"
rm -rf "$DATA_DIR"

boot "${keys[@]}" STUB_CLAUDE=exit
check "API key only: boots past auth" grep -q 'auth: ANTHROPIC_API_KEY' "$tmp/out"
check "dead claude: exits with error" grep -q 'ERROR: claude did not start (auth: ANTHROPIC_API_KEY)' "$tmp/out"
check "CLAUDE.md gets the agent name" grep -q "You are \*\*k-l1-$$\*\*" "$DATA_DIR/workspace/CLAUDE.md"
check "SOUL.md seeded" grep -q "SOUL — k-l1-$$" "$DATA_DIR/workspace/SOUL.md"
check "scheduled-tasks skill seeded" test -f "$DATA_DIR/workspace/.claude/skills/scheduled-tasks/SKILL.md"
check "owner in allowlist" grep -q '"42"' "$DATA_DIR/config/channels/telegram/access.json"
check "bot token is not written to the volume" absent fake-bot "$(grep -r . "$DATA_DIR" 2>/dev/null)"
check "API key pre-approved (last 20 chars only)" grep -q '"00000000000000000000"' "$DATA_DIR/config/.claude.json"

echo "edited by owner" > "$DATA_DIR/workspace/SOUL.md"
echo '{"allowFrom":["7"]}' > "$DATA_DIR/config/channels/telegram/access.json"
echo '{}' > "$DATA_DIR/config/settings.json"
echo '{"projects":{"/x":{"keep":1}}}' > "$DATA_DIR/config/.claude.json"
boot "${keys[@]}" STUB_CLAUDE=exit AGENT_LANGUAGE=Spanish
check "SOUL.md is not overwritten" grep -qx 'edited by owner' "$DATA_DIR/workspace/SOUL.md"
check "AGENT_LANGUAGE is applied" grep -q 'Talk to people in Spanish.' "$DATA_DIR/workspace/CLAUDE.md"
check "access.json is not overwritten" grep -q '"7"' "$DATA_DIR/config/channels/telegram/access.json"
check ".claude.json merged, not replaced" jq -e '.projects["/x"].keep == 1 and .hasCompletedOnboarding' "$DATA_DIR/config/.claude.json"
check "settings.json is re-imposed" grep -q 'telegram@claude-plugins-official' "$DATA_DIR/config/settings.json"

check "advisor off when PIXAN_ADVISOR_MODEL unset" absent advisorModel "$(cat "$DATA_DIR/config/settings.json")"
boot "${keys[@]}" STUB_CLAUDE=exit PIXAN_ADVISOR_MODEL=opus
check "advisor on with PIXAN_ADVISOR_MODEL=opus" grep -q '"advisorModel": "opus"' "$DATA_DIR/config/settings.json"

boot "${keys[@]}" STUB_CLAUDE=prompt
check "stuck on a prompt: exits with error" grep -q 'stuck waiting for input' "$tmp/out"

# Background boots: run() starts one, wait_for waits for a log line, stop() ends it.
run() { env "$@" ./kernel/entrypoint.sh > "$tmp/out" 2>&1 & pid=$!; }
wait_for() { for _ in $(seq 1 30); do grep -q "$1" "$tmp/out" && return 0; kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done; grep -q "$1" "$tmp/out"; }
stop() { kill "$pid" 2>/dev/null; wait "$pid"; code=$?; tmux -L "$AGENT_NAME" kill-server 2>/dev/null; }

run "${keys[@]}" CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-test-1111111111111111 SERVER_GRACE_SEC=0
wait_for 'heartbeat OK'
check "both set: pane environment has no OAuth token" absent CLAUDE_CODE_OAUTH_TOKEN \
  "$(tr '\0' '\n' < "/proc/$(tmux -L "$AGENT_NAME" list-panes -F '#{pane_pid}')/environ")"
check "alive: logs queued-message age" grep -q 'heartbeat OK freeze=0/20 queue=no' "$tmp/out"
stop

run "${keys[@]}" STUB_CLAUDE=hung FREEZE_CYCLES=3
wait_for 'frozen mid-activity'; stop
check "hung claude: exit 1 on freeze" test "$code" -eq 1

run "${keys[@]}" STUB_CLAUDE=noserver SERVER_GRACE_SEC=0
wait_for 'bun server.ts) is not running'; stop
check "no Telegram server: exit 1" test "$code" -eq 1

rm -f "$tmp/curl"
run "${keys[@]}" STUB_CLAUDE=dropped SERVER_GRACE_SEC=0
wait_for 'Telegram channel is not working'; sleep 3
check "dropped channel: does not restart" kill -0 "$pid"
check "dropped channel: exactly one owner alert" test "$(grep -c '^---$' "$tmp/curl")" = 1
check "dropped channel: alert fits both causes" grep -q 'Telegram is not working: check that ANTHROPIC_API_KEY is valid and channels are enabled' "$tmp/curl"
stop; rm -f "$DATA_DIR/config/auth-alerted"

rm -f "$tmp/curl"
run "${keys[@]}" STUB_CLAUDE=authdead SERVER_GRACE_SEC=0
wait_for 'credential rejected (auth: ANTHROPIC_API_KEY)'; sleep 3
check "dead credential: does not restart" kill -0 "$pid"
check "dead credential: exactly one owner alert" test "$(grep -c '^---$' "$tmp/curl")" = 1
check "dead credential: alert names AUTH_VIA, goes to the owner" grep -q 'chat_id=42.*check that ANTHROPIC_API_KEY is valid' "$tmp/curl"
check "dead credential: bot token not on curl's command line" absent 'fake-bot' "$(grep -v '^url' "$tmp/curl")"
check "dead credential: heartbeat says AUTH-DEAD, not OK" absent 'heartbeat OK' "$(cat "$tmp/out")"
stop
check "dead credential: alert stamp persisted on /data" test -s "$DATA_DIR/config/auth-alerted"
run "${keys[@]}" STUB_CLAUDE=authdead SERVER_GRACE_SEC=0
wait_for 'heartbeat AUTH-DEAD'; stop
check "dead credential, reboot within 24 h: no second alert" test "$(grep -c '^---$' "$tmp/curl")" = 1
echo 1 > "$DATA_DIR/config/auth-alerted"
run "${keys[@]}" STUB_CLAUDE=authdead SERVER_GRACE_SEC=0
wait_for 'credential rejected'; stop
check "dead credential, stamp older than 24 h: alerts again" test "$(grep -c '^---$' "$tmp/curl")" = 2

rm -f "$tmp/curl"; rm -rf "$DATA_DIR"; bake
run "${keys[@]}" STUB_CLAUDE=authdead SERVER_GRACE_SEC=0 CURL_FAIL=1
wait_for 'could not alert the owner'
for _ in $(seq 1 30); do [ "$(grep -c '^---$' "$tmp/curl")" -ge 2 ] && break; sleep 0.5; done; stop
check "alert send fails: no stamp written" test ! -e "$DATA_DIR/config/auth-alerted"
check "alert send fails: retried on the next beat" test "$(grep -c '^---$' "$tmp/curl")" -ge 2

for mode in badkey:ANTHROPIC_API_KEY badtoken:oauth_token; do
  rm -f "$tmp/curl"; rm -rf "$DATA_DIR"; bake
  if [ "${mode%%:*}" = badkey ]; then creds=("${keys[@]}"); else creds=("${base[@]}" CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-test-1111111111111111); fi
  run "${creds[@]}" STUB_CLAUDE="${mode%%:*}" SERVER_GRACE_SEC=0
  wait_for "not restarting"; sleep 3
  check "${mode%%:*}: channel notice is an auth failure, not a restart" kill -0 "$pid"
  check "${mode%%:*}: exactly one owner alert" test "$(grep -c '^---$' "$tmp/curl")" = 1
  check "${mode%%:*}: not reported as dropped messages" absent 'dropping messages' "$(cat "$tmp/out")"
  stop
done
rm -rf "$DATA_DIR"; bake
printf '{"old-one":{"id":"old-one","chat_id":"42","created_by":"42","prompt":"hi","enabled":true,"schedule":"0 9 * * *","until":"2020-01-01"}}' > "$DATA_DIR/config/cron.json"
run "${keys[@]}" STUB_CLAUDE=chatkey SERVER_GRACE_SEC=0
wait_for 'heartbeat AUTH-DEAD'; sleep 2; stop
check "'Invalid API key' in conversation text: cron still ticks" grep -q 'cron: closed: old-one' "$tmp/out"
rm -rf "$DATA_DIR"; bake
rm -f "$tmp/curl"
run "${keys[@]}" STUB_CLAUDE=dropped SERVER_GRACE_SEC=60
wait_for 'heartbeat OK'; stop
check "channel notice inside SERVER_GRACE_SEC: heartbeat OK" grep -q 'heartbeat OK' "$tmp/out"
check "channel notice inside SERVER_GRACE_SEC: no alert" test ! -e "$tmp/curl"
rm -rf "$DATA_DIR"

# Alive, then killed: the heartbeat must notice (zombie != alive).
bake; env "${keys[@]}" ./kernel/entrypoint.sh > "$tmp/out" 2>&1 & pid=$!
for _ in $(seq 1 20); do grep -q 'heartbeat OK' "$tmp/out" && break; sleep 0.5; done
check "alive: heartbeat OK" grep -q 'heartbeat OK' "$tmp/out"
kill "$(tmux -L "$AGENT_NAME" list-panes -F '#{pane_pid}')"
for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
kill "$pid" 2>/dev/null; wait "$pid"; code=$?
check "claude killed: exit 1" test "$code" -eq 1
check "claude killed: says so" grep -q 'ERROR: claude died' "$tmp/out"
finish L1
