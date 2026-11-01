# Test-only client image: the stub stands in for Claude Code; a fake Telegram plugin is baked like a client would.
ARG BASE=pixan-kernel:test
FROM ${BASE}
COPY claude /usr/local/bin/claude
RUN mkdir -p /opt/client/config/plugins/cache/claude-plugins-official/telegram/0.0.1 \
 && touch /opt/client/config/plugins/cache/claude-plugins-official/telegram/0.0.1/server.ts
