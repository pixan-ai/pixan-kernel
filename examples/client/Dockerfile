# Example private client image. Lives in the CLIENT's private repo, not in the kernel.
# Pin both the kernel digest and the Claude Code version for reproducible builds.
# KERNEL_IMAGE must be a digest, never a moving tag. Get the current one with:
#   docker buildx imagetools inspect ghcr.io/pixan-ai/pixan-kernel:main --format '{{json .Manifest.Digest}}'
# and build with --build-arg KERNEL_IMAGE=ghcr.io/pixan-ai/pixan-kernel@sha256:<64 hex chars>.
ARG KERNEL_IMAGE=ghcr.io/pixan-ai/pixan-kernel@sha256:REPLACE_WITH_KERNEL_DIGEST
FROM ${KERNEL_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG CLAUDE_CODE_VERSION=2.1.309

# /opt/client/config holds the Telegram plugin baked at build time; the kernel copies it
# into the volume on every boot, so the plugin version follows this image's digest.
USER 0
RUN mkdir -p /opt/client/config && chown 1000:1000 /opt/client/config

# Claude Code is installed by the client, pinned, as the non-root agent user.
# DISABLE_AUTOUPDATER=1 and DISABLE_UPDATES=1 are inherited from the kernel: updates ship as new images.
# The installer obeys DISABLE_UPDATES too (prints "Updates are disabled", exits 0, installs nothing),
# so it runs without it; the running agent keeps it.
USER 1000
RUN curl -fsSL https://claude.ai/install.sh | env -u DISABLE_UPDATES bash -s "${CLAUDE_CODE_VERSION}" \
 && /home/agent/.local/bin/claude --version
# Root-owned link: the agent-writable ~/.local/bin is not on PATH.
USER 0
RUN ln -s /home/agent/.local/bin/claude /usr/local/bin/claude && claude --version
USER 1000
RUN export CLAUDE_CONFIG_DIR=/opt/client/config \
 && claude plugin marketplace add anthropics/claude-plugins-official \
 && claude plugin install telegram@claude-plugins-official \
 && for d in /opt/client/config/plugins/cache/claude-plugins-official/telegram/*/; do bun install --cwd "$d"; done

# Client layer: personality, identity and skills. Seeded into /data on first boot only.
# hadolint ignore=DL3002
USER 0
COPY --chown=agent:agent SOUL.md IDENTITY.md /opt/client/workspace/
COPY --chown=agent:agent skills/ /opt/client/workspace/.claude/skills/
# Never COPY anything over /etc/claude-code or /opt/kernel: the boot check refuses to start.
