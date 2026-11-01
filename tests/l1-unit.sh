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
       STUCK_INTERVAL_SEC=0 MANAGED_SETTINGS="$PWD/kernel/managed-settings.json" CURL_LOG="$tmp/curl"
keys=(ANTHROPIC_API_KEY=sk-ant-test-0000000000000000000000 TELEGRAM_BOT_TOKEN=fake-bot OWNER_TELEGRAM_ID=42)
boot() { env "$@" ./kernel/entrypoint.sh > "$tmp/out" 2>&1; }

base=(TELEGRAM_BOT_TOKEN=fake-bot OWNER_TELEGRAM_ID=42)
boot "${base[@]}" STUB_CLAUDE=exit
check "no credential: fails fast with MISSING" grep -q 'MISSING credential' "$tmp/out"
check "no credential: MISSING lists every option" grep -q 'BEDROCK/VERTEX/FOUNDRY=1, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_API_KEY, apiKeyHelper or CLAUDE_CODE_OAUTH_TOKEN' "$tmp/out"
check "no credential: writes nothing" test ! -e "$DATA_DIR/workspace/CLAUDE.md"

boot "${base[@]}" CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-test-1111111111111111 STUB_CLAUDE=exit
check "OAuth only: boots past auth" grep -q 'auth: CLAUDE_CODE_OAUTH_TOKEN' "$tmp/out"
check "OAuth only: onboarding and trust seeded" grep -q '"hasTrustDialogAccepted": true' "$DATA_DIR/config/.claude.json"
check "OAuth only: plugin installed before claude starts" grep -q 'plugin: stub-claude plugin install telegram@claude-plugins-official' "$tmp/out"
check "OAuth only: no approved key entry" absent customApiKeyResponses "$(cat "$DATA_DIR/config/.claude.json")"
check "OAuth only: token never written to the volume" absent 1111111111111111 "$(cat "$tmp/out"; grep -r . "$DATA_DIR" 2>/dev/null)"
check "dead claude: alert names the credential in use" grep -q 'did not start (auth: CLAUDE_CODE_OAUTH_TOKEN)' "$tmp/out"
rm -rf "$DATA_DIR"

boot "${keys[@]}" CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-test-1111111111111111 STUB_CLAUDE=exit
check "both set: warns" grep -q 'WARN both ANTHROPIC_API_KEY and CLAUDE_CODE_OAUTH_TOKEN' "$tmp/out"
check "both set: API key wins" grep -q 'auth: ANTHROPIC_API_KEY' "$tmp/out"
check "both set: key pre-approved" grep -q '"00000000000000000000"' "$DATA_DIR/config/.claude.json"
check "both set: no secret value in the log" absent 0000000000 "$(cat "$tmp/out")"
rm -rf "$DATA_DIR"

boot "${base[@]}" ANTHROPIC_AUTH_TOKEN=at ANTHROPIC_API_KEY=k CLAUDE_CODE_OAUTH_TOKEN=t STUB_CLAUDE=exit
check "precedence: ANTHROPIC_AUTH_TOKEN beats key and token" grep -q 'auth: ANTHROPIC_AUTH_TOKEN' "$tmp/out"
boot "${base[@]}" CLAUDE_CODE_USE_FOUNDRY=1 ANTHROPIC_API_KEY=k STUB_CLAUDE=exit
check "precedence: Foundry (cloud) wins" grep -q 'auth: CLAUDE_CODE_USE_FOUNDRY' "$tmp/out"
check "cloud: warns there are no Telegram channels" grep -q 'WARN CLAUDE_CODE_USE_FOUNDRY: Telegram channels are not available' "$tmp/out"
rm -rf "$DATA_DIR"

boot "${keys[@]}" STUB_CLAUDE=exit
check "API key only: boots past auth" grep -q 'auth: ANTHROPIC_API_KEY' "$tmp/out"
check "dead claude: exits with error" grep -q 'ERROR: claude did not start (auth: ANTHROPIC_API_KEY)' "$tmp/out"
check "CLAUDE.md gets the agent name" grep -q "You are \*\*k-l1-$$\*\*" "$DATA_DIR/workspace/CLAUDE.md"
check "SOUL.md seeded" grep -q "SOUL — k-l1-$$" "$DATA_DIR/workspace/SOUL.md"
check "scheduled-tasks skill seeded" test -f "$DATA_DIR/workspace/.claude/skills/scheduled-tasks/SKILL.md"
check "owner in allowlist" grep -q '"42"' "$DATA_DIR/config/channels/telegram/access.json"
check "bot token file is private" test "$(stat -c %a "$DATA_DIR/config/channels/telegram/.env")" = 600
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

run "${keys[@]}" STUB_CLAUDE=dropped SERVER_GRACE_SEC=0
wait_for 'dropping messages'; stop
check "dropped channel: exit 1" test "$code" -eq 1

rm -f "$tmp/curl"
run "${keys[@]}" STUB_CLAUDE=authdead SERVER_GRACE_SEC=0
wait_for 'credential rejected (auth: ANTHROPIC_API_KEY)'; sleep 3
check "dead credential: does not restart" kill -0 "$pid"
check "dead credential: exactly one owner alert" test "$(grep -c '^---$' "$tmp/curl")" = 1
check "dead credential: alert names AUTH_VIA, goes to the owner" grep -q 'chat_id=42.*Check that ANTHROPIC_API_KEY is valid' "$tmp/curl"
check "dead credential: bot token not on curl's command line" absent 'fake-bot' "$(grep -v '^url' "$tmp/curl")"
stop

# Alive, then killed: the heartbeat must notice (zombie != alive).
env "${keys[@]}" ./kernel/entrypoint.sh > "$tmp/out" 2>&1 & pid=$!
for _ in $(seq 1 20); do grep -q 'heartbeat OK' "$tmp/out" && break; sleep 0.5; done
check "alive: heartbeat OK" grep -q 'heartbeat OK' "$tmp/out"
check "alive: heartbeat file is fresh" test $(( $(date +%s) - $(cat "$DATA_DIR/config/heartbeat") )) -le 2
kill "$(tmux -L "$AGENT_NAME" list-panes -F '#{pane_pid}')"
for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
kill "$pid" 2>/dev/null; wait "$pid"; code=$?
check "claude killed: exit 1" test "$code" -eq 1
check "claude killed: says so" grep -q 'ERROR: claude died' "$tmp/out"
finish L1
