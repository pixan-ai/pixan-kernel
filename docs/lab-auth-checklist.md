# Lab checklist: real-credential auth test (one time, not CI)

Run once per release that touches auth, on a throwaway agent with a throwaway volume and a test
Telegram bot. Use **your own** credentials, set only in that environment. Never paste a credential into
an issue, log, chat or this file; record only pass/fail.

Setup for every case: fresh volume, `TELEGRAM_BOT_TOKEN` of a test bot, `OWNER_TELEGRAM_ID` = your
own test account.

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
| 3 | Both set | `WARN both ...` then `auth: ANTHROPIC_API_KEY` | ☐ | ☐ | Console, for **both** chat and cron |
| 4 | `CLAUDE_CODE_USE_BEDROCK=1` (or Vertex) + cloud env | `auth: CLAUDE_CODE_USE_BEDROCK` | n/a (no channels) | ☐ (run `cron.py run`, check the log) | Cloud account |
| 5 | None | `MISSING credential: ...`, exit 1 | n/a | n/a | n/a |
| 6 | Revoked key or token | Alert names the variable in use | ☐ | Chat gets "could not complete ... check that X is valid" | n/a |

Team/Enterprise subscription: confirm an Owner has enabled channels for the organization before case 2.
