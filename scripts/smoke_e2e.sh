#!/usr/bin/env bash
# End-to-end smoke test: sign up -> log in -> chat with all three agents.
#
# Usage:
#   ./scripts/smoke_e2e.sh [username] [password]
#
# Reads your Gurobi Intelligence Hub credentials from .env
# (GRB_INTELLIGENCE_ACCESS_ID / GRB_INTELLIGENCE_SECRET) and talks to a running
# server (default http://127.0.0.1:8000; override with BASE_URL).
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
USERNAME="${1:-smoke}"
PASSWORD="${2:-smokepass123}"
PY="${PY:-.venv/bin/python}"

AID=$(grep -E '^GRB_INTELLIGENCE_ACCESS_ID=' .env | cut -d= -f2-)
SEC=$(grep -E '^GRB_INTELLIGENCE_SECRET=' .env | cut -d= -f2-)
if [ -z "${AID:-}" ] || [ -z "${SEC:-}" ]; then
  echo "ERROR: GRB_INTELLIGENCE_ACCESS_ID / GRB_INTELLIGENCE_SECRET not set in .env" >&2
  exit 1
fi

echo "== 1. SIGN UP (username=$USERNAME) =="
REG=$(printf '{"username":"%s","password":"%s","grb_access_id":"%s","grb_secret":"%s"}' \
  "$USERNAME" "$PASSWORD" "$AID" "$SEC")
code=$(curl -s -o /tmp/smoke_reg.json -w '%{http_code}' \
  -X POST "$BASE_URL/auth/register" -H 'content-type: application/json' -d "$REG")
case "$code" in
  201) echo "   registered (201)";;
  409) echo "   already registered (409) — continuing";;
  *)   echo "   FAILED ($code):"; cat /tmp/smoke_reg.json; echo; exit 1;;
esac

echo "== 2. LOG IN =="
LOGIN=$(printf '{"username":"%s","password":"%s"}' "$USERNAME" "$PASSWORD")
TOKEN=$(curl -s -X POST "$BASE_URL/auth/login" -H 'content-type: application/json' -d "$LOGIN" \
  | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
if [ -z "$TOKEN" ]; then echo "   login failed" >&2; exit 1; fi
echo "   got token (${#TOKEN} chars)"

chat() {
  local agent="$1" conv="$2" msg="$3"
  echo "-- agent: $agent (conversation: $conv) --"
  local body
  body=$(printf '{"conversation_id":"%s","agent":"%s","message":"%s"}' "$conv" "$agent" "$msg")
  curl -s -X POST "$BASE_URL/chat" \
    -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d "$body" \
    | "$PY" -c "import sys,json; d=json.load(sys.stdin); print('   reply:', (d.get('text') or ('ERROR: '+str(d)))[:400])"
}

echo "== 3. CHAT WITH EACH AGENT =="
chat gurobot   c-gurobot   "In one sentence, what is Gurobi?"
chat explainer c-explainer "In one sentence, what do you help with?"
chat modeler   c-modeler   "In one sentence, what do you help with?"

echo "== DONE =="
