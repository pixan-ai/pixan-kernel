# shellcheck shell=bash
# Shared helpers for the test layers. Source it; don't run it.
fail=0
ok()  { printf 'ok   %s\n' "$*"; }
bad() { printf 'FAIL %s\n' "$*"; fail=1; }
check() {  # check "description" command...
  local what="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then ok "$what"; else bad "$what"; printf '%s\n' "$out" | tail -n 15; fi
}
finish() { if [ "$fail" -eq 0 ]; then echo "PASS $1"; else echo "FAILED $1"; exit 1; fi; }
absent() { ! grep -q "$1" <<<"$2"; }   # absent PATTERN TEXT
