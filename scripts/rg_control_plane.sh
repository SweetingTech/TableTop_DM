#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

create_campaign_payload='{"name":"RG Control Campaign","slug":"rg-control-campaign","status":"ACTIVE","mode":"EXPLORATION"}'
CAMPAIGN_JSON=$(curl -sS -X POST "$BASE_URL/api/campaigns" -H 'Content-Type: application/json' -d "$create_campaign_payload")
CAMPAIGN_ID=$(echo "$CAMPAIGN_JSON" | python -c 'import json,sys;print(json.load(sys.stdin)["id"])')

echo "Campaign: $CAMPAIGN_ID"

SESSION_JSON=$(curl -sS -X POST "$BASE_URL/api/campaigns/$CAMPAIGN_ID/sessions")
SESSION_ID=$(echo "$SESSION_JSON" | python -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "Session: $SESSION_ID"

curl -sS -X POST "$BASE_URL/api/campaigns/$CAMPAIGN_ID/entities" -H 'Content-Type: application/json' -d '{"name":"RG Hero","entity_type":"PC","public_sheet":{"class":"Fighter"}}' >/dev/null

curl -sS -X PUT "$BASE_URL/api/campaigns/$CAMPAIGN_ID/ai_config" -H 'Content-Type: application/json' -d '{"llm_provider":"ollama","llm_base_url":"http://localhost:11434/v1/","dm_model":"llama3","npc_model":"llama3","embedding_model":"embeddinggemma"}' >/dev/null

echo 'Tiny lore text for rg control plane query.' > /tmp/rg_control_doc.txt
curl -sS -X POST "$BASE_URL/api/campaigns/$CAMPAIGN_ID/rag/upload" -F "file=@/tmp/rg_control_doc.txt" >/dev/null
curl -sS -X POST "$BASE_URL/api/campaigns/$CAMPAIGN_ID/rag/query" -H 'Content-Type: application/json' -d '{"query":"lore text","top_k":3}'

echo "RG control plane complete"
