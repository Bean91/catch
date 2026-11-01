#!/bin/sh
# One-time root setup for Catch on the Pi. Run this yourself, interactively, once:
#
#   rsync -a deploy/ opensky-pi:/tmp/catch-deploy/
#   ssh -t opensky-pi 'sudo sh /tmp/catch-deploy/pi-bootstrap.sh'
#
# Idempotent — safe to re-run after editing any file in deploy/ (e.g. to pick up a changed
# systemd unit). Never touches piaware/fr24feed/tar1090/lighttpd or their ports; only adds
# a new dedicated `catch` user, a capped journald rule, and Catch's own units.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this with sudo." >&2
    exit 1
fi

SRC_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

echo "==> Baseline: confirming PiAware services are untouched before we start"
systemctl is-active piaware fr24feed tar1090 || true

echo "==> Dedicated service user"
if ! id catch >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin catch
fi
# opensky (the deploy/rsync user) needs read access to the backups directory catch owns,
# for the laptop pull-backups command, and to journald's logs for deploy.sh's failure path.
usermod -aG catch opensky
usermod -aG systemd-journal opensky

echo "==> Directories"
mkdir -p /opt/catch/app
chown opensky:opensky /opt/catch
chown opensky:opensky /opt/catch/app
chmod 755 /opt/catch /opt/catch/app
# Shared, world-readable install location for uv's own downloaded Python build + cache —
# NOT under /home/opensky (mode 0700), which the `catch` user can't traverse, so its venv's
# symlinked interpreter would otherwise fail with EACCES at service start.
mkdir -p /opt/catch/.uv-python /opt/catch/.uv-cache
chown opensky:opensky /opt/catch/.uv-python /opt/catch/.uv-cache
chmod 755 /opt/catch/.uv-python /opt/catch/.uv-cache
# Staging spot for the one-time real-secrets/DB handoff below — opensky-writable (it has to
# rsync the files in from the laptop) but not catch- or world-readable, since real secrets
# sit here briefly before this script moves them into /var/lib/catch and deletes the copy.
mkdir -p /opt/catch/.staging
chown opensky:opensky /opt/catch/.staging
chmod 700 /opt/catch/.staging

mkdir -p /var/lib/catch /var/lib/catch/backups
chown catch:catch /var/lib/catch /var/lib/catch/backups
chmod 750 /var/lib/catch
chmod 750 /var/lib/catch/backups

if [ ! -f /var/lib/catch/catch.env ]; then
    echo "   (no /var/lib/catch/catch.env yet — deploy.sh will tell you to put one there)"
    touch /var/lib/catch/catch.env
    chown catch:catch /var/lib/catch/catch.env
    chmod 600 /var/lib/catch/catch.env
fi

echo "==> Adopting any staged real secrets/DB (left in /opt/catch/.staging by the laptop side)"
if [ -f /opt/catch/.staging/catch.env ]; then
    install -o catch -g catch -m 600 /opt/catch/.staging/catch.env /var/lib/catch/catch.env
    rm -f /opt/catch/.staging/catch.env
    echo "   adopted catch.env"
fi
if [ -f /opt/catch/.staging/catch.db ]; then
    install -o catch -g catch -m 640 /opt/catch/.staging/catch.db /var/lib/catch/catch.db
    rm -f /opt/catch/.staging/catch.db
    echo "   adopted catch.db"
fi
if [ -d /opt/catch/.staging/fit ]; then
    mkdir -p /var/lib/catch/fit
    cp -a /opt/catch/.staging/fit/. /var/lib/catch/fit/
    chown -R catch:catch /var/lib/catch/fit
    find /var/lib/catch/fit -type f -exec chmod 640 {} \;
    find /var/lib/catch/fit -type d -exec chmod 750 {} \;
    rm -rf /opt/catch/.staging/fit
    echo "   adopted fit/"
fi

echo "==> sqlite3 (needed for nightly backups; no other packages touched, no apt upgrade)"
if ! command -v sqlite3 >/dev/null 2>&1; then
    NEEDRESTART_MODE=l apt-get install -y --no-install-recommends sqlite3
fi

echo "==> systemd units"
install -m 644 "$SRC_DIR/catch.service" /etc/systemd/system/catch.service
install -m 644 "$SRC_DIR/catch-backup.service" /etc/systemd/system/catch-backup.service
install -m 644 "$SRC_DIR/catch-backup.timer" /etc/systemd/system/catch-backup.timer
install -m 755 "$SRC_DIR/backup.sh" /usr/local/bin/catch-backup.sh

echo "==> journald cap (SystemMaxUse only — never touches Storage=, which PiAware also uses)"
mkdir -p /etc/systemd/journald.conf.d
install -m 644 "$SRC_DIR/journald-catch.conf" /etc/systemd/journald.conf.d/catch.conf
systemctl restart systemd-journald

echo "==> scoped passwordless sudo for deploy.sh (restart/status of catch.service only)"
visudo -c -f "$SRC_DIR/sudoers-catch-deploy"
install -m 440 "$SRC_DIR/sudoers-catch-deploy" /etc/sudoers.d/catch-deploy

systemctl daemon-reload
systemctl enable catch.service catch-backup.timer
systemctl start catch-backup.timer
# catch.service itself is NOT started here — there's no app code at /opt/catch/app yet.
# deploy.sh does the first `systemctl restart catch.service` once code has been rsynced.

echo "==> Tailscale serve (HTTPS -> local :8000, tailnet-only; current config shown first)"
tailscale serve status || true
tailscale serve --bg 8000

echo "==> Memory cgroup controller (needed for catch.service's MemoryMax to actually enforce
anything — Raspberry Pi OS ships it compiled in but off by default; /proc/cgroups confirmed
no 'memory' line before this)"
REBOOT_NEEDED=""
CMDLINE=/boot/firmware/cmdline.txt
if [ -f "$CMDLINE" ] && ! grep -q 'cgroup_memory=1' "$CMDLINE"; then
    cp "$CMDLINE" "$CMDLINE.catch-bak"
    sed -i 's/$/ cgroup_memory=1 cgroup_enable=memory/' "$CMDLINE"
    echo "   $CMDLINE updated (backup at $CMDLINE.catch-bak)"
    REBOOT_NEEDED=1
fi

echo "==> Done. PiAware check:"
systemctl is-active piaware fr24feed tar1090

echo ""
echo "Next: put real secrets in /var/lib/catch/catch.env (mode 600, owned by catch), then"
echo "run ./deploy.sh from your laptop."

if [ -n "$REBOOT_NEEDED" ]; then
    echo ""
    echo "==> Rebooting now to activate the memory cgroup controller (piaware/fr24feed/tar1090"
    echo "    restart automatically on boot — brief interruption, not a lasting one)."
    sleep 2
    reboot
fi
