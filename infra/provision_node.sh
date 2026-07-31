#!/usr/bin/env bash
# Provision a bare Ubuntu 24.04 LTS Server box into an Atlas GPU worker node.
# Target hardware: HP Z8 (multi-GPU) and Lenovo i9 (single GPU). Same script, both boxes.
#
# Runs in two stages because the NVIDIA driver needs a reboot in between.
#
#   stage 1:  sudo bash infra/provision_node.sh      -> installs driver, then reboot
#   reboot
#   stage 2:  sudo bash infra/provision_node.sh      -> docker, container toolkit, tailscale
#
# The script tracks its own progress in /var/lib/atlas/provision.stage, so re-running is
# safe and it always resumes from the right place.
#
# NOTE: only the NVIDIA *driver* is installed on the host. CUDA itself is NOT installed
# system-wide — it ships inside the containers. This keeps the host clean and lets
# different workloads pin different CUDA versions without fighting each other.

set -euo pipefail

STATE_DIR=/var/lib/atlas
STATE_FILE="$STATE_DIR/provision.stage"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo."
mkdir -p "$STATE_DIR"
STAGE="$(cat "$STATE_FILE" 2>/dev/null || echo 0)"

# ─────────────────────────────────────────────────────────────── preflight
preflight() {
  log "Preflight"

  . /etc/os-release
  echo "    OS:        $PRETTY_NAME"
  [[ "$ID" == "ubuntu" ]] || die "Expected Ubuntu. Found: $ID"
  [[ "$VERSION_ID" == "24.04" ]] || warn "Expected 24.04 LTS, found $VERSION_ID — continuing, but this is untested."

  local gpus
  gpus="$(lspci | grep -ci 'nvidia' || true)"
  [[ "$gpus" -gt 0 ]] || die "No NVIDIA device found on the PCI bus. Check the card is seated and powered."
  echo "    NVIDIA PCI devices: $gpus"

  # Secure Boot blocks the proprietary driver unless the module is MOK-signed.
  if command -v mokutil >/dev/null 2>&1; then
    local sb; sb="$(mokutil --sb-state 2>/dev/null || echo unknown)"
    echo "    Secure Boot: $sb"
    if grep -qi enabled <<<"$sb"; then
      die "Secure Boot is ENABLED. Disable it in BIOS and re-run, or you will be signing kernel modules by hand on every update."
    fi
  fi

  echo "    RAM:  $(free -g | awk '/^Mem:/{print $2}') GB"
  echo "    Disk: $(df -h / | awk 'NR==2{print $4}') free on /"
}

# ─────────────────────────────────────────────────────────── stage 1: driver
stage1() {
  log "Stage 1 — base packages and NVIDIA driver"

  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    build-essential git curl wget ca-certificates gnupg lsb-release \
    python3 python3-venv python3-pip \
    ffmpeg jq htop nvtop tmux unzip \
    ubuntu-drivers-common mokutil

  log "Installing NVIDIA driver (server/gpgpu variant, headless)"
  # --gpgpu selects the datacenter/headless driver flavour: no X, no desktop deps.
  ubuntu-drivers install --gpgpu || {
    warn "ubuntu-drivers failed; falling back to the recommended desktop driver"
    ubuntu-drivers install
  }

  # Persistence mode keeps the driver resident so the first job of the day isn't slow.
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nvidia-utils-* 2>/dev/null || true
  systemctl enable nvidia-persistenced 2>/dev/null || true

  echo 1 > "$STATE_FILE"
  log "Stage 1 complete — REBOOT NOW, then re-run this script"
  echo "    sudo reboot"
}

# ────────────────────────────────────── stage 2: docker, toolkit, tailscale
stage2() {
  log "Stage 2 — verifying driver"
  command -v nvidia-smi >/dev/null || die "nvidia-smi missing. Did the reboot happen?"
  nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv || die "nvidia-smi failed — driver did not load."

  log "Installing Docker CE"
  install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  # Naml lesson: Docker lost every image on host reboot until storage was pinned.
  # Verify data-root explicitly rather than trusting the default.
  log "Docker data-root: $(docker info --format '{{.DockerRootDir}}')"

  log "Installing NVIDIA Container Toolkit"
  if [[ ! -f /etc/apt/keyrings/nvidia-container-toolkit.gpg ]]; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | gpg --dearmor -o /etc/apt/keyrings/nvidia-container-toolkit.gpg
  fi
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia-container-toolkit.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker

  log "Installing Tailscale"
  if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi

  echo 2 > "$STATE_FILE"

  log "Verifying GPU access from inside a container"
  if docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi -L; then
    log "GPU passthrough into Docker: OK"
  else
    warn "Container could not see the GPU. Check: nvidia-ctk runtime configure --runtime=docker && systemctl restart docker"
  fi

  cat <<'NEXT'

──────────────────────────────────────────────────────────────
 Node provisioned. Two manual steps remain — both need YOUR account:

   1.  sudo tailscale up --hostname=atlas-<z8|lenovo>
       (opens a URL you approve in a browser)

   2.  Tell Claude the node is up. The Atlas worker agent,
       ComfyUI and model weights get deployed from there.

 Deliberately NOT installed: CUDA toolkit system-wide.
 It ships inside containers so workloads can pin their own version.
──────────────────────────────────────────────────────────────
NEXT
}

# ───────────────────────────────────────────────────────────────── dispatch
case "$STAGE" in
  0) preflight; stage1 ;;
  1) stage2 ;;
  2) log "Node already provisioned."
     nvidia-smi --query-gpu=index,name,memory.total --format=csv
     echo "    Re-run from scratch with: sudo rm $STATE_FILE" ;;
  *) die "Unknown stage '$STAGE' in $STATE_FILE" ;;
esac
