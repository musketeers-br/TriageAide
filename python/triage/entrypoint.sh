#!/bin/bash
set -e

export FHIR_BASE_URL="${FHIR_BASE_URL:-http://iris:52773/fhir/r4}"
export FHIR_USER="${FHIR_USER:-_SYSTEM}"
export FHIR_PASS="${FHIR_PASS:-SYS}"
export FHIR_MCP_URL="http://localhost:8000/mcp"
export TRIAGE_MCP_URL="http://localhost:8001/mcp"
export CR_MCP_URL="http://localhost:8002/mcp"

if [ -n "$LANGSMITH_API_KEY" ]; then
  export LANGSMITH_TRACING="${LANGSMITH_TRACING:-true}"
  export LANGSMITH_PROJECT="${LANGSMITH_PROJECT:-triage-aide}"
  echo "LangSmith tracing enabled (project: $LANGSMITH_PROJECT)"
fi

echo "Waiting for FHIR server at $FHIR_BASE_URL ..."
for i in $(seq 1 120); do
  if python3 -c "import requests; r=requests.get('${FHIR_BASE_URL}/metadata', headers={'Accept':'application/fhir+json'}, auth=('${FHIR_USER}','${FHIR_PASS}'), timeout=5); exit(0 if r.status_code==200 else 1)" 2>/dev/null; then
    echo "FHIR server ready."
    break
  fi
  if [ "$i" -eq 120 ]; then
    echo "ERROR: FHIR server not ready after 120s"
    exit 1
  fi
  sleep 1
done

echo "Loading seed data (if not already loaded)..."
PATIENT_COUNT=$(python3 -c "import requests; r=requests.get('${FHIR_BASE_URL}/Patient', params={'_tag':'triage-seed','_count':1}, headers={'Accept':'application/fhir+json'}, auth=('${FHIR_USER}','${FHIR_PASS}'), timeout=10); print(r.json().get('total',0))" 2>/dev/null || echo "0")
if [ "$PATIENT_COUNT" = "0" ]; then
  python3 seed_data.py load
  echo "Seed data loaded."
else
  echo "Seed data already exists ($PATIENT_COUNT patients). Skipping."
fi

echo "Starting FHIR MCP Server on port 8000..."
python3 fhir_server.py > /tmp/fhir_server.log 2>&1 &
FHIR_PID=$!

echo "Starting Triage MCP Server on port 8001..."
python3 triage_server.py > /tmp/triage_server.log 2>&1 &
TRIAGE_PID=$!

echo "Starting Clinical Reasoning MCP Server on port 8002..."
python3 clinical_reasoning_server.py > /tmp/cr_server.log 2>&1 &
CR_PID=$!

echo "Waiting for MCP servers to be ready..."
for port in 8000 8001 8002; do
  for i in $(seq 1 30); do
    if python3 -c "import requests; r=requests.get('http://localhost:$port/mcp', timeout=2); exit(0 if r.status_code in [200,405,406] else 1)" 2>/dev/null; then
      echo " Port $port ready"
      break
    fi
    if [ "$i" -eq 30 ]; then
      echo "WARNING: MCP server on port $port not ready after 30s"
    fi
    sleep 1
  done
done

echo "Starting Voice Bridge on port 8003..."
uvicorn voice_bridge:app --host 0.0.0.0 --port 8003 --log-level info --no-access-log > /tmp/voice_bridge.log 2>&1 &
VOICE_PID=$!

cleanup() {
  echo "Shutting down services..."
  kill $FHIR_PID $TRIAGE_PID $CR_PID $VOICE_PID 2>/dev/null
  wait $FHIR_PID $TRIAGE_PID $CR_PID $VOICE_PID 2>/dev/null
  echo "Done."
}
trap cleanup EXIT INT TERM

echo "Starting Gradio UI on port 7860..."
exec python3 app.py
