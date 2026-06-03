#!/usr/bin/env bash
# ONE-TIME: log Antigravity CLI (`agy`) into a Linux container that matches the Harbor
# sandbox (ubuntu:24.04, root, $HOME=/root) and CAPTURE its native Linux token store, so
# the matrix can run antigravity-cli on your Google *subscription* at $0 — no API key.
#
# WHY: agy keeps its OAuth token in a Go keyring (macOS Keychain on your host), under its
# OWN OAuth client — NOT in ~/.gemini/oauth_creds.json. There is no host file to inject.
# Letting agy do the OAuth exchange *inside* a matching Linux container makes it write the
# credentials in exactly the layout the sandbox will read. We tar that out for reuse.
#
# WHAT YOU DO: run this in your OWN terminal (it needs an interactive TTY for the code
# paste). A Google login URL prints; open it, approve, copy the authorization code, paste
# it back here, press Enter. ~2 minutes, once. The token has a refresh_token, so it lasts.
#
# OUTPUT: runs/harbor_auth/agy_token_store.tgz  (+ new_files_after_login.txt)
#         These hold a live credential — gitignored, never commit.
#
# Usage:  bash scripts/agy_login_capture.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="runs/harbor_auth"
mkdir -p "$OUT"
IMG="ubuntu:24.04"   # same base as the task sandboxes (see */environment/Dockerfile)

echo ">>> Pulling/using $IMG and installing agy inside it. A browser login will follow."
echo ">>> Have your browser ready — the auth code prompt can time out if you stall."
echo

# -it gives agy's auth sub-flow a real TTY so you can paste the authorization code.
# --rm: ephemeral; we copy the token store to the mounted /capture before exit.
docker run -it --rm \
  -v "$PWD/$OUT:/capture" \
  -e HOME=/root \
  "$IMG" bash -lc '
set -e
echo "[1/4] installing curl + agy ..."
apt-get update -y >/dev/null 2>&1 || true
apt-get install -y curl ca-certificates >/dev/null 2>&1 || true
curl -fsSL https://antigravity.google/cli/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
agy --version || true

# snapshot AFTER install, BEFORE login — the diff isolates the token store
find "$HOME" -type f 2>/dev/null | sort > /tmp/before.txt || true

echo
echo "=================================================================="
echo ">>> [2/4] A Google login URL will print below."
echo ">>>       Open it in your browser, approve, COPY the code, PASTE it"
echo ">>>       here, press Enter. (If it says timed out, just rerun the"
echo ">>>       same command shown after — be quick on the paste.)"
echo "=================================================================="
echo
# Triggers the OAuth flow (needs auth -> prints URL + reads the pasted code from stdin),
# then runs a trivial prompt to confirm the session works.
agy -p "Reply with exactly: AGY_AUTH_OK" || true

echo
echo "[3/4] capturing token store ..."
find "$HOME" -type f 2>/dev/null | sort > /tmp/after.txt || true
comm -13 /tmp/before.txt /tmp/after.txt > /capture/new_files_after_login.txt || true
# Grab the credential-bearing dirs (broad on purpose; we narrow on the host side).
tar czf /capture/agy_token_store.tgz -C "$HOME" .gemini .config .local/share 2>/dev/null || true
chmod 600 /capture/agy_token_store.tgz 2>/dev/null || true

echo "[4/4] done. files created/changed by the login:"
cat /capture/new_files_after_login.txt 2>/dev/null || true
'
echo
echo ">>> Captured to $OUT/ . Tell Claude it is done; it will verify the token landed"
echo ">>> and wire it into the antigravity-cli matrix cell."
