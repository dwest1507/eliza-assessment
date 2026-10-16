#!/usr/bin/env sh
# Ask the running chat API one question and print its stream as it arrives.
#
#   make api                      # in another terminal
#   backend/scripts/chat.sh       # asks the brief's first example question
#   backend/scripts/chat.sh "How has NVIDIA's revenue changed over the last two years?"
#
# API_URL overrides the server (default http://localhost:8000). The response is the
# Vercel AI SDK UI message stream: the Query Scope and Sources as data parts, then the
# answer as text-delta parts.
set -eu

API_URL="${API_URL:-http://localhost:8000}"
QUESTION="${1:-What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?}"

# Escape backslashes and double quotes for the JSON string.
ESCAPED=$(printf '%s' "$QUESTION" | sed 's/\\/\\\\/g; s/"/\\"/g')

curl --no-buffer --silent --show-error --fail-with-body \
  -X POST "$API_URL/api/chat" \
  -H 'Content-Type: application/json' \
  -d "{\"messages\": [{\"role\": \"user\", \"content\": \"$ESCAPED\"}]}"
echo
