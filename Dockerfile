# pixan-kernel base image. It does NOT contain Claude Code: each client image
# installs a pinned version on top (see examples/client/Dockerfile).
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Base image is pinned by digest; pinning each apt package would break on Debian point releases.
# iptables/ipset/dnsutils/aggregate are only used by the optional egress firewall.
# procps gives pgrep, which the heartbeat uses to see the Telegram server (bun server.ts).
# hadolint ignore=DL3008
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      ca-certificates curl git python3 tmux tzdata unzip jq procps iptables ipset dnsutils aggregate \
 && rm -rf /var/lib/apt/lists/*

ENV HOME=/home/agent \
    PATH="/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    LANG=C.UTF-8 \
    TZ=America/Mexico_City \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_UPDATES=1 \
    CLAUDE_CONFIG_DIR=/data/config \
    TELEGRAM_STATE_DIR=/data/config/channels/telegram \
    AGENT_WORKSPACE=/data/workspace

# Claude Code refuses --dangerously-skip-permissions as root: run as a normal user.
RUN useradd -m -u 1000 -s /bin/bash agent && mkdir -p /data && chown agent:agent /data

# Bun is required by the official Telegram plugin. Pinned like everything else.
ARG BUN_VERSION=bun-v1.2.23
USER agent
RUN curl -fsSL https://bun.sh/install | bash -s "${BUN_VERSION}" && /home/agent/.bun/bin/bun --version

# Kernel files are root-owned and read-only for the agent. The manifest lets the
# boot check detect a client layer that overwrote a guard.
# hadolint ignore=DL3002
USER root
# Agent-writable dirs stay off PATH; root-owned links in /usr/local/bin point at the pinned installs.
RUN ln -s /home/agent/.bun/bin/bun /usr/local/bin/bun && bun --version
COPY kernel/managed-settings.json /etc/claude-code/managed-settings.json
COPY kernel/ /opt/kernel/
RUN rm /opt/kernel/managed-settings.json \
 && chmod 0755 /opt/kernel/entrypoint.sh /opt/kernel/bin/*.py /opt/kernel/firewall/*.sh \
 && chmod 0644 /etc/claude-code/managed-settings.json \
 && { sha256sum /etc/claude-code/managed-settings.json /opt/kernel/entrypoint.sh \
      /opt/kernel/bin/*.py /opt/kernel/firewall/*.sh \
      && find /opt/kernel/seed -type f -print0 | sort -z | xargs -0 sha256sum; } > /opt/kernel/kernel.sha256 \
 && chmod 0444 /opt/kernel/kernel.sha256

VOLUME ["/data"]
WORKDIR /data/workspace
ENTRYPOINT ["/opt/kernel/entrypoint.sh"]
