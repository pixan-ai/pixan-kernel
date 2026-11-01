#!/usr/bin/env bash
# L2 — the real base image + a test layer with a stub `claude` (stands in for a client image).
# Needs Docker; no network at runtime, no real keys.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=tests/lib.sh
. tests/lib.sh

base=pixan-kernel:test; img=pixan-kernel-client:test; c="k-l2-$$"
trap 'docker rm -f "$c" "$c-t" >/dev/null 2>&1' EXIT
check "base image builds" docker build -q -t "$base" .
check "base image has no claude" docker run --rm --entrypoint bash "$base" -c '! command -v claude'
check "test client image builds" docker build -q -t "$img" --build-arg BASE="$base" -f tests/stubs/Dockerfile tests/stubs
check "managed settings are root-owned" test "$(docker run --rm --entrypoint stat "$img" -c %U:%a /etc/claude-code/managed-settings.json)" = root:644

out="$(docker run --rm "$img" 2>&1)"; code=$?
check "no keys: exit is not 0" test "$code" -ne 0
check "no keys: says MISSING" grep -q 'MISSING credential' <<<"$out"

out="$(docker run --rm --entrypoint bash "$img" -c 'echo "{}" > /etc/claude-code/managed-settings.json && /opt/kernel/entrypoint.sh' 2>&1)"
check "tampered guards: refuses to boot" grep -q 'kernel guards were modified' <<<"$out"

docker run -d --name "$c" --network none \
  -e ANTHROPIC_API_KEY=sk-ant-fake -e TELEGRAM_BOT_TOKEN=fake -e OWNER_TELEGRAM_ID=42 \
  -e AGENT_NAME=l2 -e BOOT_WAIT_SEC=1 -e HEARTBEAT_SEC=1 "$img" >/dev/null
for _ in $(seq 1 30); do docker logs "$c" 2>&1 | grep -q 'heartbeat OK' && break; sleep 1; done
logs="$(docker logs "$c" 2>&1)"
check "fake keys: reaches tmux and heartbeat" grep -q 'heartbeat OK' <<<"$logs"
# shellcheck disable=SC2016
check "claude runs as agent, not root" docker exec -u agent "$c" bash -c '[ "$(stat -c %U "/proc/$(tmux -L l2 list-panes -F "#{pane_pid}")")" = agent ]'
check "heartbeat file is written on /data" docker exec "$c" test -s /data/config/heartbeat

docker exec -u agent "$c" bash -c 'kill "$(tmux -L l2 list-panes -F "#{pane_pid}")"'
code="$(timeout 20 docker wait "$c")"
check "claude killed: container exits 1" test "$code" = 1
check "claude killed: logs say so" grep -q 'ERROR: claude died' <<<"$(docker logs "$c" 2>&1)"
[ "$fail" -eq 0 ] || docker logs "$c" 2>&1 | tail -20
finish L2
