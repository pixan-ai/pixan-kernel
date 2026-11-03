#!/usr/bin/env bash
# L0 — static checks + unit tests. No Docker, no network, no real keys.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=tests/lib.sh
. tests/lib.sh

check "shellcheck" shellcheck -x kernel/entrypoint.sh kernel/firewall/*.sh tests/*.sh tests/stubs/claude lab/*.sh
for f in $(git ls-files '*.sh' tests/stubs/claude tests/stubs/curl); do check "no CR (LF only): $f" absent $'\r' "$(cat "$f")"; done
check "hadolint: Dockerfile" hadolint --failure-threshold warning Dockerfile
check "hadolint: client example" hadolint --failure-threshold warning examples/client/Dockerfile
for f in $(git ls-files -co --exclude-standard '*.json'); do check "valid JSON: $f" python3 -m json.tool "$f"; done
for f in $(git ls-files -co --exclude-standard '*.yml' '*.yaml' '*.toml'); do
  case "$f" in *.toml) check "valid TOML: $f" python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$f" ;;
  *) check "valid YAML: $f" python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1]))' "$f" ;; esac
done
check "CLAUDE.md imports @SOUL.md"     grep -qx '@SOUL.md' kernel/seed/workspace/CLAUDE.md
check "CLAUDE.md imports @IDENTITY.md" grep -qx '@IDENTITY.md' kernel/seed/workspace/CLAUDE.md
check "base image has no Claude Code" absent 'claude.ai/install.sh\|@anthropic-ai/claude-code' "$(cat Dockerfile)"
check "channels enabled in managed settings" jq -e '.channelsEnabled == true' kernel/managed-settings.json
check "managed hooks use /usr/bin/python3" jq -e '[.. | objects | select(.type? == "command") | .command] | all(. == "/usr/bin/python3")' kernel/managed-settings.json
check "no Write(...) deny rules (they never match)" absent '"Write(' "$(cat kernel/managed-settings.json)"
check "Telegram access is allowlist-only" jq -e '.dmPolicy == "allowlist"' kernel/seed/access.json
check "plugins are not in managed settings" absent 'enabledPlugins' "$(cat kernel/managed-settings.json)"
check "advisor is off in the seed" absent 'advisorModel' "$(cat kernel/seed/settings.json kernel/managed-settings.json)"
# shellcheck disable=SC2016
check "advisor only switches on with PIXAN_ADVISOR_MODEL" grep -q 'if \[ -n "${PIXAN_ADVISOR_MODEL:-}" \]' kernel/entrypoint.sh
check "unit tests (python)" python3 -m unittest discover -s tests/unit -q
if command -v gitleaks >/dev/null; then check "gitleaks: no secrets in history" gitleaks git --no-banner --redact .; fi
finish L0
