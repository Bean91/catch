#!/usr/bin/env bash
# Build on the laptop, ship to the Pi, restart, verify. Never builds on the Pi itself (no
# Node there). Requires deploy/pi-bootstrap.sh to have been run on the Pi at least once
# (creates the `catch` user, systemd units, and the scoped passwordless-sudo rule this
# script's restart step relies on).
set -euo pipefail

HOST=opensky-pi
REMOTE_APP_DIR=/opt/catch/app
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "==> Checking working tree is clean"
if [ -n "$(git status --porcelain)" ]; then
    echo "!! Working tree is dirty — commit or stash before deploying:" >&2
    git status --short >&2
    exit 1
fi

echo "==> Running local checks (make check — same commands CI runs; see README.md #6)"
make check

echo "==> Syncing code to $HOST:$REMOTE_APP_DIR (secrets and data are never touched — they live outside this path)"
rsync -az --delete \
    --exclude='__pycache__' --exclude='*.pyc' \
    ./catch ./pyproject.toml ./uv.lock ./.python-version \
    "$HOST:$REMOTE_APP_DIR/"

echo "==> uv sync on the Pi"
# shellcheck disable=SC2029
ssh "$HOST" '
    set -e
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
        sh /tmp/uv-install.sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
    cd '"$REMOTE_APP_DIR"'
    export UV_PYTHON_INSTALL_DIR=/opt/catch/.uv-python
    export UV_CACHE_DIR=/opt/catch/.uv-cache
    uv sync --frozen
'

if ssh "$HOST" "test -s /var/lib/catch/catch.env" ; then :; else
    echo "!! /var/lib/catch/catch.env is missing or empty on $HOST." >&2
    echo "   Copy deploy/catch.env.example there, fill in real secrets, chmod 600, chown catch:catch." >&2
    exit 1
fi

echo "==> Restarting catch.service"
ssh "$HOST" "sudo systemctl restart catch.service"

echo "==> Health check (retrying for up to 40s — cold start on the Pi 3 takes ~18-20s)"
ok=""
for _ in 1 2 3 4 5 6 7 8; do
    if ssh "$HOST" "curl -fsS http://127.0.0.1:8000/api/health" >/tmp/catch-health.json 2>/dev/null; then
        ok=1
        break
    fi
    sleep 5
done

if [ -n "$ok" ]; then
    echo "==> Healthy: $(cat /tmp/catch-health.json)"
else
    echo "!! /api/health did not respond. Recent logs:" >&2
    ssh "$HOST" "journalctl -u catch.service -n 40 --no-pager" >&2
    exit 1
fi

echo "==> Build deployed: $(ssh "$HOST" "curl -fsS http://127.0.0.1:8000/version.json" 2>/dev/null || echo 'version.json not served (static dir missing?)')"
