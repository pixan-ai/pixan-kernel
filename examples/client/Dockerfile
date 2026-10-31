# Example private client image. Lives in the CLIENT's private repo, not in the kernel.
# Pin both the kernel digest and the Claude Code version for reproducible builds.
ARG KERNEL_IMAGE=ghcr.io/pixan-ai/pixan-kernel:main
FROM ${KERNEL_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG CLAUDE_CODE_VERSION=2.1.0

# Claude Code is installed by the client, pinned, as the non-root agent user.
# DISABLE_AUTOUPDATER=1 is inherited from the kernel: updates ship as new images.
USER 1000
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_CODE_VERSION}" && claude --version

# Client layer: personality, identity and skills. Seeded into /data on first boot only.
# hadolint ignore=DL3002
USER 0
COPY --chown=agent:agent SOUL.md IDENTITY.md /opt/client/workspace/
COPY --chown=agent:agent skills/ /opt/client/workspace/.claude/skills/
# Never COPY anything over /etc/claude-code or /opt/kernel: the boot check refuses to start.
