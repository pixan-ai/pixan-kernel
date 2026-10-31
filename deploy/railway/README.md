# Railway

1. Create a service from your **client** repo (its Dockerfile builds `FROM ghcr.io/pixan-ai/pixan-kernel`).
2. Copy `railway.toml` to the client repo root.
3. Attach a volume mounted at `/data`.
4. Variables: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, `AGENT_NAME`, optional
   `AGENT_LANGUAGE`, `PIXAN_ADVISOR_MODEL`. Do not set `CLAUDE_CODE_OAUTH_TOKEN` (refused).
5. Deploy and look for `heartbeat OK` in the logs. A dead Claude exits 1 and Railway restarts it.

The egress firewall needs `NET_ADMIN`, which Railway does not grant: leave `KERNEL_FIREWALL` unset there.
