# Lab checklist: real-credential auth test (one time, not CI)

**The maintainer runs this checklist** by hand, once per release that touches auth or channels, on a throwaway
agent and a test Telegram bot. Use **your own** credentials, set only in that environment. Never paste a
credential into an issue, log, chat or this file; record only pass/fail.

## Where the lab runs

It needs a real Docker host. A dev PC may have no Docker, and Railway cannot test the firewall
(no `NET_ADMIN`). Use a machine with Docker, e.g. a laptop with Docker Desktop (WSL2 backend) or a
small Linux VPS. Run every command below in a **Linux or WSL shell** (not PowerShell or cmd); the repo's
`.gitattributes` keeps scripts LF so a Windows checkout does not break them (`env: 'bash\r'`). Nothing is published: `lab/build.sh` builds the images locally from the checkout.

```bash
git clone https://github.com/pixan-ai/pixan-kernel && cd pixan-kernel
git checkout batch-1-foundation        # or the lab/** branch under test
./lab/build.sh                          # -> pixan-lab-client:lab, prints claude --version
# Credentials: type them into a local env file ONLY on the lab host; never commit or paste it.
cat > ~/lab.env <<'ENV'
TELEGRAM_BOT_TOKEN=
OWNER_TELEGRAM_ID=
ANTHROPIC_API_KEY=
ENV
chmod 600 ~/lab.env
# Run one case (fresh volume each time):
docker rm -f lab 2>/dev/null; docker volume rm lab-data 2>/dev/null
docker run -d --name lab --env-file ~/lab.env -e AGENT_NAME=lab -v lab-data:/data pixan-lab-client:lab
docker logs -f lab                       # Ctrl-C to stop following
docker inspect -f '{{.RestartCount}}' lab
```

Run `cron.py` as the agent user, never as root: `docker exec -u agent lab python3 /opt/kernel/bin/cron.py list`.
With `--restart unless-stopped` added, `RestartCount` shows whether the container loops.

Setup for **every** case: a **fresh volume** (delete and recreate it before each case, so no state from a
previous case can mask a failure), `TELEGRAM_BOT_TOKEN` of a test bot, `OWNER_TELEGRAM_ID` = your own test
account.

For each case below:

1. Boot and check the log shows the expected `auth:` line and no credential value.
2. Telegram: send the bot a message and get a reply.
3. Cron: `docker exec -u agent lab python3 /opt/kernel/bin/cron.py add --id lab-auth-check --at "<now + 2 min>" --chat-id <your chat> --created-by lab --prompt "Say: lab auth ok"`.
   Within ~3 min the message arrives in Telegram; `cron.py list` shows `delivered`.
4. Check billing/usage shows the activity on the expected account (Console usage or claude.ai usage).
5. `grep -r` the volume for the token/key: only the last 20 characters of an API key may appear, in `.claude.json`.

| # | Environment | Expected log | Telegram | Cron | Billed to |
|---|---|---|---|---|---|
| 1 | `ANTHROPIC_API_KEY` only | `auth: ANTHROPIC_API_KEY` | ☐ | ☐ | Console |
| 2 | `CLAUDE_CODE_OAUTH_TOKEN` only | `auth: oauth_token` | ☐ | ☐ | Subscription |
| 3 | Key and token set | `WARN both ...` then `auth: ANTHROPIC_API_KEY` | ☐ | ☐ | Console, for **both** chat and cron |
| 4 | `CLAUDE_CODE_USE_BEDROCK=1` (or Vertex/Foundry) + cloud env | `WARN ... WITHOUT Telegram`, `auth:` with the name `claude auth status` reports | n/a (no channels) | ☐ (run `cron.py run`, check the log) | Cloud account |
| 5 | None | `MISSING credential: claude auth status reports not logged in`, exit 1 | n/a | n/a | n/a |

**Case 1 must also assert** (valid key, after `SERVER_GRACE_SEC`, default 90 s): no owner alert, no
`AUTH-DEAD` in the log, and `heartbeat OK` lines.

- ☐ No alert, no `AUTH-DEAD`, `heartbeat OK`.
- If `Messages are dropped until it loads` **stays painted** on screen with a valid credential (`docker exec -u agent lab tmux -L lab capture-pane -p -t lab`),
  the channel-notice check is wrong and **this design must change** before merge. We have never seen that
  screen with a valid credential, so it may be transient or may stay.

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
| B | Telegram server killed | `docker exec lab pkill -f 'bun.*server.ts'` | Within ~2 heartbeats: `ERROR: Telegram server (bun server.ts) is not running`, container exits 1 and the platform restarts it; Telegram replies again after restart |
| D | Plugin reads the bot token from env | Any working case: confirm `/data/config/channels/telegram/.env` does **not** exist | Telegram still replies (the plugin reads `TELEGRAM_BOT_TOKEN` from the environment) |
| C | Revoked credential alerts the owner | Revoke the key (Console) or token, then message the bot | Log `ERROR: credential rejected (auth: X); not restarting`, then `heartbeat AUTH-DEAD`; the owner gets **exactly one** Telegram alert naming X; `docker inspect -f '{{.RestartCount}}' lab` stays the same |
| E | Invalid key from boot | `ANTHROPIC_API_KEY=sk-ant-api03-lab-invalid-0000000000000000000000000000` (fake, 40+ chars: the kernel pre-approves the key by `${key: -20}`, which is empty below 20 chars, so a short key gets the approval prompt and exits 1 `stuck waiting for input` instead of reaching the alert), run with `--restart unless-stopped`, wait 5 min | Exactly one alert; `RestartCount` stays 0 (no "Messages are dropped" restart loop). `docker restart lab`: still no second alert (stamp in `/data/config/auth-alerted`, re-alert after 24 h) |
| F | Invalid OAuth token from boot | `CLAUDE_CODE_OAUTH_TOKEN=invalid` only | Screen shows `--channels ignored` / `Channels are not currently available`; log `ERROR: credential rejected (auth: oauth_token)` or `ERROR: Telegram channel is not working (see screen) (auth: oauth_token)`, exactly one alert, no restarts, no `heartbeat OK` |
| G | Baked plugin | Any working case | `docker exec lab ls /data/config/plugins/cache/claude-plugins-official/telegram/` shows the version baked in the image; Telegram replies |
| H | Firewall | Case 1 plus `-e KERNEL_FIREWALL=1 --cap-add NET_ADMIN --cap-add NET_RAW` | Log has no `ERROR: firewall`; Telegram replies; `docker exec -u agent lab curl -sS -m 5 https://example.com` fails; `docker exec -u agent lab curl -sS -m 5 -o /dev/null -w '%{http_code}' https://api.anthropic.com` answers |

Result: ☐ all pass → OK to merge. Any failure: do not merge; note the case number and the log line.
