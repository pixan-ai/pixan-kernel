#!/usr/bin/env bash
# L2 client — builds the REAL example client image (installs pinned Claude Code + the Telegram plugin)
# on top of the base image built by l2-docker.sh. Needs Docker and network at build time; no keys.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=tests/lib.sh
. tests/lib.sh

base=pixan-kernel:test; img=pixan-kernel-example-client:test
docker image inspect "$base" >/dev/null 2>&1 || docker build -q -t "$base" .
check "example client image builds" docker build -q -t "$img" --build-arg KERNEL_IMAGE="$base" examples/client
check "claude --version works in the client image" docker run --rm --entrypoint claude "$img" --version
# shellcheck disable=SC2016
check "claude resolves to a root-owned link" docker run --rm --entrypoint bash "$img" -c '[ "$(command -v claude)" = /usr/local/bin/claude ] && [ "$(stat -c %U /usr/local/bin/claude)" = root ]'
check "Telegram plugin is baked" docker run --rm --entrypoint bash "$img" -c 'compgen -G "/opt/client/config/plugins/cache/claude-plugins-official/telegram/*/server.ts"'
check "DISABLE_UPDATES stays on at runtime" test "$(docker run --rm --entrypoint printenv "$img" DISABLE_UPDATES)" = 1
finish "L2 client"
