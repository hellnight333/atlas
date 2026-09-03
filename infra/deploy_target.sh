# Resolve "which host, which key" for every deploy script. Sourced, not run.
#
#     . "$(dirname "$0")/deploy_target.sh"
#     qevik_resolve_target "$SPEC"      # sets QEVIK_TARGET_{NAME,HOST,KEY}
#
# The rules, in one place because three scripts used to each carry their own
# copy of a hard-coded host and a hard-coded key:
#
#   1. A registry name (`old-prod`, `new-prod`) resolves to that entry.
#   2. A raw `user@host` resolves only when QEVIK_DEPLOY_KEY names the identity
#      to use. An approved identity is never guessed.
#   3. Nothing given — no argument, no QEVIK_DEPLOY_TARGET — is a refusal.
#   4. An unknown name is a refusal. There is no fallback: falling back on a
#      typo is how a deploy lands on the host nobody meant.
#
# Refusals exit 2, print the valid names, and touch nothing.
#
# A resolved target is exported, so a script that calls another (console →
# public) hands over the same host and identity rather than re-deriving them.

QEVIK_TARGETS_FILE="${QEVIK_TARGETS_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy_targets.conf}"

qevik__target_names() {
  [ -r "$QEVIK_TARGETS_FILE" ] || return 0
  grep -vE '^[[:space:]]*(#|$)' "$QEVIK_TARGETS_FILE" | cut -d'|' -f1 | tr '\n' ' '
}

qevik__target_line() {
  [ -r "$QEVIK_TARGETS_FILE" ] || return 1
  grep -vE '^[[:space:]]*(#|$)' "$QEVIK_TARGETS_FILE" | awk -F'|' -v n="$1" '$1 == n {print; found=1} END {exit !found}'
}

qevik__refuse() {
  echo "REFUSED: $1" >&2
  echo "  known targets: $(qevik__target_names)" >&2
  echo "  usage: --target <name>   (or QEVIK_DEPLOY_TARGET=<name>)" >&2
  echo "  ad-hoc: pass user@host together with QEVIK_DEPLOY_KEY=<identity file>" >&2
  echo "  registry: $QEVIK_TARGETS_FILE" >&2
  exit 2
}

qevik_resolve_target() {
  local spec="${1:-}" line key

  # Already resolved by a parent script: reuse it rather than re-deriving, so a
  # console deploy and the public deploy it calls cannot disagree about where
  # they are.
  if [ "${QEVIK_TARGET_RESOLVED:-}" = 1 ] && [ -n "${QEVIK_TARGET_HOST:-}" ]; then
    return 0
  fi

  [ -n "$spec" ] || spec="${QEVIK_DEPLOY_TARGET:-}"
  [ -n "$spec" ] || qevik__refuse "no target given. This tooling has no default host."

  case "$spec" in
    *@*)
      # Ad-hoc destination. The identity must be stated, and must exist: an
      # unreadable key produces a confusing "Permission denied" from the far
      # end, minutes into a deploy, instead of a refusal now.
      [ -n "${QEVIK_DEPLOY_KEY:-}" ] || qevik__refuse "'$spec' is a raw host and QEVIK_DEPLOY_KEY is not set."
      key="${QEVIK_DEPLOY_KEY/#\~\//$HOME/}"
      [ -f "$key" ] || qevik__refuse "identity file '$key' does not exist."
      QEVIK_TARGET_NAME="explicit"
      QEVIK_TARGET_HOST="$spec"
      QEVIK_TARGET_KEY="$key"
      ;;
    *)
      line="$(qevik__target_line "$spec")" || qevik__refuse "unknown target '$spec'."
      QEVIK_TARGET_NAME="$spec"
      QEVIK_TARGET_HOST="$(printf '%s' "$line" | cut -d'|' -f2)"
      key="$(printf '%s' "$line" | cut -d'|' -f3)"
      key="${key/#\~\//$HOME/}"
      if [ "$key" = "-" ]; then
        # The entry defers to ~/.ssh/config. Allowed for ad-hoc entries only;
        # the production rows name their key so a review can see it.
        QEVIK_TARGET_KEY=""
      else
        [ -f "$key" ] || qevik__refuse "target '$spec' needs identity '$key', which does not exist on this machine."
        QEVIK_TARGET_KEY="$key"
      fi
      ;;
  esac

  QEVIK_TARGET_RESOLVED=1
  export QEVIK_TARGET_NAME QEVIK_TARGET_HOST QEVIK_TARGET_KEY QEVIK_TARGET_RESOLVED
}

# The `-i <key>` argument list for ssh/scp/rsync, empty when the entry defers to
# ssh_config. Printed as words, so callers expand it unquoted on purpose.
qevik_target_identity_args() {
  [ -n "${QEVIK_TARGET_KEY:-}" ] && printf '%s' "-i ${QEVIK_TARGET_KEY} -o IdentitiesOnly=yes"
}
