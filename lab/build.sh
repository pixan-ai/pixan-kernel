#!/usr/bin/env bash
# Builds a runnable lab image from the CURRENT checkout (no registry, nothing published):
# the kernel base, then the real example client on top (pinned Claude Code + baked Telegram plugin).
# Usage: ./lab/build.sh            -> images pixan-kernel:lab and pixan-lab-client:lab
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t pixan-kernel:lab .
docker build -t pixan-lab-client:lab --build-arg KERNEL_IMAGE=pixan-kernel:lab examples/client
docker run --rm --entrypoint claude pixan-lab-client:lab --version
echo "lab image ready: pixan-lab-client:lab (kernel $(git rev-parse --short HEAD))"
