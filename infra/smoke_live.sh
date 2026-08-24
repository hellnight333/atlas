#!/usr/bin/env bash
# Verify app.qevik.ai end to end, as a signed-in operator.
#
#   QEVIK_USER=admin QEVIK_PASS='...' ./infra/smoke_live.sh
#
# The password is read from the environment and never written anywhere. Run it
# from a shell where history is off, or export it in a subshell:
#
#   ( read -rs QEVIK_PASS; export QEVIK_PASS QEVIK_USER=admin; ./infra/smoke_live.sh )
#
# It checks what a person actually does: sign in, read every surface, start a
# conversation, and confirm the durable history is there. It does not approve a
# plan — that queues real work, and a smoke test should not.
set -euo pipefail

BASE="${QEVIK_BASE:-https://app.qevik.ai}"
USER="${QEVIK_USER:-admin}"
: "${QEVIK_PASS:?set QEVIK_PASS (it is never stored)}"

pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
          else echo "  FAIL  $1 — got $2, expected $3"; fail=$((fail+1)); fi; }

echo "=== $BASE ==="
echo
echo "1. Before signing in"
check "the console loads" \
  "$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' "$BASE/")" 200
check "/api/missions refuses" \
  "$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' "$BASE/api/missions")" 401
check "and refuses with JSON, never HTML" \
  "$(curl -sS --max-time 20 -o /dev/null -w '%{content_type}' "$BASE/api/missions" | cut -d';' -f1)" \
  "application/json"

echo
echo "2. Signing in"
TOKEN=$(curl -sS --max-time 20 -X POST "$BASE/auth/login" \
  -H 'Content-Type: application/json' \
  -d "$(printf '{"username":"%s","password":"%s"}' "$USER" "$QEVIK_PASS")" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null || true)
if [ -z "$TOKEN" ]; then echo "  FAIL  no session token — check the credentials"; exit 1; fi
echo "  PASS  a session token was issued"; pass=$((pass+1))

auth() { curl -sS --max-time 20 -H "Authorization: Bearer $TOKEN" "$@"; }
code() { auth -o /dev/null -w '%{http_code}' "$BASE$1"; }

echo
echo "3. Every surface answers"
for path in /api/missions /api/chat /api/credentials /api/models \
            /api/models/selection /api/missions/actions /api/missions/blockers \
            /api/missions/costs /api/customer/actions /api/health; do
  check "$path" "$(code "$path")" 200
done

echo
echo "4. The Credential Centre"
CRED=$(auth "$BASE/api/credentials")
COUNT=$(echo "$CRED" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("credentials",[])))')
check "every integration is listed" "$([ "$COUNT" -ge 16 ] && echo ok)" ok
SEALED=$(echo "$CRED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["vault"]["sealed"])')
echo "  INFO  vault sealed: $SEALED  (false means keys can be stored)"

echo
echo "5. Chat, without approving anything"
CID=$(auth -X POST "$BASE/api/chat" -H 'Content-Type: application/json' \
  -d '{"text":"Smoke test: confirm the control plane is reachable."}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("conversation_id",""))')
check "a conversation is created" "$([ -n "$CID" ] && echo ok)" ok
check "it is readable again" "$(code "/api/chat/$CID")" 200
check "and appears in the history" \
  "$(auth "$BASE/api/chat" | python3 -c "import json,sys; print('ok' if any(c['conversation_id']=='$CID' for c in json.load(sys.stdin)['conversations']) else 'no')")" ok

echo
echo "=================================================="
echo "  $pass passed, $fail failed"
echo "=================================================="
[ "$fail" -eq 0 ]
