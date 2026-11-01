# Railway

1. Create a service from your **client** repo (its Dockerfile builds `FROM ghcr.io/pixan-ai/pixan-kernel`).
2. Copy `railway.toml` to the client repo root.
3. Attach a volume mounted at `/data`.
4. Variables: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, `AGENT_NAME`, optional
   `AGENT_LANGUAGE`, `PIXAN_ADVISOR_MODEL`. Instead of `ANTHROPIC_API_KEY` you may set your own
   `CLAUDE_CODE_OAUTH_TOKEN` (subscription, for your own individual use; see Auth model in the main README).
   If both are set, the API key wins and the log warns. Each person uses and pays for their own credential.
5. Deploy and look for `heartbeat OK` in the logs. A dead Claude exits 1 and Railway restarts it.

The egress firewall needs `NET_ADMIN`, which Railway does not grant: leave `KERNEL_FIREWALL` unset there.
