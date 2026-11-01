# Lab checklist: real-credential auth test (one time, not CI)

**Alfredo runs this checklist** by hand, once per release that touches auth or channels, on a throwaway
agent and a test Telegram bot. Use **your own** credentials, set only in that environment. Never paste a
credential into an issue, log, chat or this file; record only pass/fail.

Setup for **every** case: a **fresh volume** (delete and recreate it before each case, so no state from a
previous case can mask a failure), `TELEGRAM_BOT_TOKEN` of a test bot, `OWNER_TELEGRAM_ID` = your own test
account.

For each case below:

1. Boot and check the log shows the expected `auth:` line and no credential value.
2. Telegram: send the bot a message and get a reply.
3. Cron: `docker exec <agent> python3 /opt/kernel/bin/cron.py add --id lab-auth-check --at "<now + 2 min>" --chat-id <your chat> --created-by lab --prompt "Say: lab auth ok"`.
   Within ~3 min the message arrives in Telegram; `cron.py list` shows `delivered`.
4. Check billing/usage shows the activity on the expected account (Console usage or claude.ai usage).
5. `grep -r` the volume for the token/key: only the last 20 characters of an API key may appear, in `.claude.json`.

| # | Environment | Expected log | Telegram | Cron | Billed to |
|---|---|---|---|---|---|
| 1 | `ANTHROPIC_API_KEY` only | `auth: ANTHROPIC_API_KEY` | ☐ | ☐ | Console |
| 2 | `CLAUDE_CODE_OAUTH_TOKEN` only | `auth: CLAUDE_CODE_OAUTH_TOKEN` | ☐ | ☐ | Subscription |
| 3 | Key and token set | `WARN both ...` then `auth: ANTHROPIC_API_KEY` | ☐ | ☐ | Console, for **both** chat and cron |
| 4 | `CLAUDE_CODE_USE_BEDROCK=1` (or Vertex/Foundry) + cloud env | `WARN ... WITHOUT Telegram`, `auth: CLAUDE_CODE_USE_BEDROCK` | n/a (no channels) | ☐ (run `cron.py run`, check the log) | Cloud account |
| 5 | None | `MISSING credential: ...`, exit 1 | n/a | n/a | n/a |

**Case 2 must settle one open question.** Earlier tests with a token showed
`--channels ignored ... Channels are not currently available` on screen. Was that caused by a fake/invalid
token? Run case 2 with a **real, valid** token from `claude setup-token`:

- ☐ Valid token: the message does **not** appear and Telegram replies → it was the fake token.
- ☐ Valid token: the message **still** appears → channels are not available with that token/plan
  (Team/Enterprise: an Owner must enable channels for the organization; re-check after enabling). Record which.

## Extra checks (any working case, e.g. case 1)

| # | Check | How | Expected |
|---|---|---|---|
| A | Unauthorized Telegram ID is dropped | Message the bot from a second account that is **not** `OWNER_TELEGRAM_ID` | No reply, no pairing code; the owner's chat still works (`dmPolicy: allowlist`) |
| B | Telegram server killed | `docker exec <agent> pkill -f 'bun.*server.ts'` | Within ~2 heartbeats: `ERROR: Telegram server (bun server.ts) is not running`, container exits 1 and the platform restarts it; Telegram replies again after restart |
| C | Revoked credential alerts the owner | Revoke the key (Console) or token, then message the bot | Log `ERROR: credential rejected (auth: X); not restarting`; the owner gets **one** Telegram alert naming X; the container keeps running (no restart loop) |

Result: ☐ all pass → OK to merge. Any failure: do not merge; note the case number and the log line.
