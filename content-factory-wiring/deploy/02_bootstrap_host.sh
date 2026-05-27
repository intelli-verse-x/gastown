#!/usr/bin/env bash
# 02_bootstrap_host.sh — prepare a Gas Town host for content-factory studio gates.
#
# Idempotent. Safe to re-run.
#
# Usage:
#   bash deploy/02_bootstrap_host.sh [--no-systemd]
set -euo pipefail

INSTALL_SYSTEMD=true
for arg in "$@"; do
  case "$arg" in
    --no-systemd) INSTALL_SYSTEMD=false ;;
  esac
done

echo "==> 1. checking go ..."
if ! command -v go >/dev/null; then
  echo "Go not found — installing 1.22"
  case "$(uname -s)" in
    Linux)  ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
            curl -fsSL "https://go.dev/dl/go1.22.linux-${ARCH}.tar.gz" \
              | sudo tar -C /usr/local -xz ;;
    Darwin) brew install go ;;
    *) echo "unsupported OS"; exit 1 ;;
  esac
  export PATH="$PATH:/usr/local/go/bin:$(go env GOPATH 2>/dev/null)/bin"
fi
GOPATH=$(go env GOPATH)
export PATH="$PATH:$GOPATH/bin"

echo "==> 2. installing bd (beads) CLI ..."
if ! command -v bd >/dev/null; then
  # ICU is required for bd's regex package on macOS; Linux usually has it.
  if [[ "$(uname -s)" == "Darwin" ]] && ! pkg-config --exists icu-uc 2>/dev/null; then
    brew install icu4c
    BREW_ICU=$(brew --prefix icu4c)
    export PKG_CONFIG_PATH="${BREW_ICU}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
    export CGO_CFLAGS="-I${BREW_ICU}/include"
    export CGO_LDFLAGS="-L${BREW_ICU}/lib"
  fi
  go install github.com/steveyegge/beads/cmd/bd@latest
fi
bd --version || (echo "bd install failed"; exit 1)

echo "==> 3. installing gt (Gas Town) CLI ..."
if ! command -v gt >/dev/null; then
  echo "gt not found — please install per Gas Town docs (out of scope here)"
  echo "  https://github.com/<your-org>/gastown"
fi

echo "==> 4. python deps for studio gates ..."
PYTHON=$(command -v python3.12 || command -v python3.11 || command -v python3)
"$PYTHON" -m pip install --user --upgrade \
  pillow numpy rembg jsonschema 'fastapi[standard]' uvicorn pydantic httpx tomli

# Optional: face embedding upgrade for G4 (skip silently if it fails)
"$PYTHON" -m pip install --user face_recognition || \
  echo "  (warn) face_recognition not installed — G4 falls back to perceptual hash"

echo "==> 5. ffmpeg ..."
if ! command -v ffmpeg >/dev/null; then
  case "$(uname -s)" in
    Linux)  sudo apt-get update && sudo apt-get install -y ffmpeg ;;
    Darwin) brew install ffmpeg ;;
  esac
fi
ffmpeg -version | head -1

echo "==> 6. CONTENTX_CERT_KEY ..."
if [[ -z "${CONTENTX_CERT_KEY:-}" ]]; then
  echo "WARNING: CONTENTX_CERT_KEY not in environment."
  echo "Add to ~/.profile or systemd EnvironmentFile:"
  echo "    export CONTENTX_CERT_KEY=\$(vault kv get -field=value contentx/cert-key)"
fi

echo "==> 7. running post-deploy verifier ..."
HERE=$(cd "$(dirname "$0")"/.. && pwd)
if [[ -n "${CONTENTX_CERT_KEY:-}" ]]; then
  "$PYTHON" "$HERE/tools/studio_gates/post_deploy_verify.py" || {
    echo "FATAL: post_deploy_verify failed — see report"; exit 1;
  }
else
  echo "SKIP: set CONTENTX_CERT_KEY then re-run post_deploy_verify"
fi

if $INSTALL_SYSTEMD && [[ "$(uname -s)" == "Linux" ]]; then
  echo "==> 8. installing systemd units (postiz-webhook, hermes-cron) ..."
  if [[ -f /etc/systemd/system/postiz-webhook.service ]]; then
    sudo systemctl daemon-reload
  else
    sudo cp "$HERE/services/postiz_webhook/postiz-webhook.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable postiz-webhook
  fi
fi

echo ""
echo "host bootstrap complete"
