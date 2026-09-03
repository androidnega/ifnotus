#!/usr/bin/env bash
# Install supported IFNOTUS Python runtimes on Ubuntu 24.04 host.
set -euo pipefail

apt-get update
apt-get install -y \
  python3.9 python3.9-venv python3.9-dev \
  python3.10 python3.10-venv python3.10-dev \
  python3.11 python3.11-venv python3.11-dev \
  python3.12 python3.12-venv python3.12-dev \
  python3.13 python3.13-venv python3.13-dev

echo "Installed Python runtimes:"
for v in 3.9 3.10 3.11 3.12 3.13; do
  command -v "python${v}" >/dev/null && "python${v}" --version || echo "python${v}: missing"
done
