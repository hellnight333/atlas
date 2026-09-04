#!/usr/bin/env bash
#
# The repository the model-backed worker is allowed to change.
#
#   ./infra/install_notes_origin.sh            # create it, idempotently
#   ./infra/install_notes_origin.sh --check    # report without touching anything
#
# Why this exists at all.
#
# A worker started with `--agent llm` and no `--origin` can only take missions
# declaring origin `none`, and `none` has no workspace. So a coding agent
# reports success, changes no file, and the worker correctly refuses the claim —
# three attempts, then failed. That refusal is right (an agent's "done" is a
# claim, and the workspace is what decides) and the outcome is useless: a
# conversation in the console can never finish.
#
# `qevik` — the checkout itself, self-modification — is deliberately *not*
# available here and needs no configuration to be absent. ADR-0010 ships a git
# archive, so /opt/qevik/atlas has no `.git` and the origin registry does not
# offer it. Self-modification on a production host would need a real clone and a
# separate decision; this is not that.
#
# So: one ordinary repository, outside the deployment, that the worker may write
# to. It is the same mechanism a customer repository would use — `--origin
# NAME=PATH` — exercised on something that is nobody's production code.
set -euo pipefail

ORIGIN_ROOT="${QEVIK_ORIGIN_ROOT:-/srv/origins}"
NAME="${QEVIK_ORIGIN_NAME:-notes}"
REPO="$ORIGIN_ROOT/$NAME"
OWNER="${QEVIK_APP_USER:-qevik}"

say() { printf '%s\n' "$*"; }

if [ "${1:-}" = "--check" ]; then
  if [ -d "$REPO/.git" ]; then
    say "present: $REPO"
    say "owner:   $(stat -c '%U:%G' "$REPO")"
    say "commits: $(git -C "$REPO" rev-list --count HEAD 2>/dev/null || echo 0)"
    say "branch:  $(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo none)"
  else
    say "absent: $REPO"
    exit 1
  fi
  exit 0
fi

[ "$(id -u)" -eq 0 ] || { echo "run as root: it creates a directory under /srv" >&2; exit 1; }

# Never inside the deployment. An origin that resolved to Qevik's own tree would
# be refused at worker start-up anyway, and getting the refusal from a script
# that already made the directory is a worse way to learn it.
case "$REPO" in
  /opt/qevik/atlas*|/opt/qevik/atlas)
    echo "REFUSED: $REPO is inside the deployment" >&2; exit 2 ;;
esac

install -d -m 0755 -o "$OWNER" -g "$OWNER" "$ORIGIN_ROOT"

if [ -d "$REPO/.git" ]; then
  say "already a repository: $REPO"
else
  install -d -m 0755 -o "$OWNER" -g "$OWNER" "$REPO"
  # As the service account, so every object and ref is owned by the process that
  # will write here. A repository root-owned by accident fails at the first
  # commit with a permission error that reads like a code fault.
  sudo -u "$OWNER" git -C "$REPO" init -q -b main
  sudo -u "$OWNER" git -C "$REPO" config user.email "worker@qevik.local"
  sudo -u "$OWNER" git -C "$REPO" config user.name "Qevik worker"
  sudo -u "$OWNER" tee "$REPO/README.md" >/dev/null <<'DOC'
# notes

A working repository for the model-backed mission worker.

Nothing here is production code. It exists so a mission that asks for a file to
be written has somewhere to write it: a worker with no origin can only take
missions declaring `none`, which has no workspace, so a coding agent reports
success, changes nothing, and the worker refuses the claim.

Created by `infra/install_notes_origin.sh`.
DOC
  sudo -u "$OWNER" git -C "$REPO" add README.md
  sudo -u "$OWNER" git -C "$REPO" commit -q -m "the repository the worker may write to"
  say "created: $REPO"
fi

# A mission clones this and works in the clone; production stays read-only —
# `mission/scratch.py`. An empty repository cannot be cloned, which is why the
# commit above is not optional.
test -n "$(sudo -u "$OWNER" git -C "$REPO" rev-parse --verify HEAD 2>/dev/null)" || {
  echo "FAILED: $REPO has no commit, so nothing can clone it" >&2; exit 3; }

say ""
say "origin '$NAME' -> $REPO"
say "The worker unit already names it. Restart it to pick this up:"
say "  systemctl restart qevik-worker-llm"
