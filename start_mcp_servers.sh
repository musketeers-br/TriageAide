#!/bin/bash
TRIAGE_DIR=/home/irisowner/irisdev/python/triage

if [ ! -f "$TRIAGE_DIR/.env" ]; then
    echo "WARNING: $TRIAGE_DIR/.env not found. MCP servers will not start."
    exit 0
fi

export FHIR_BASE_URL=http://localhost:52773/fhir/r4
export FHIR_USER=_SYSTEM
export FHIR_PASS=SYS
export FHIR_MCP_URL=http://localhost:8000/mcp
export TRIAGE_MCP_URL=http://localhost:8001/mcp
export CR_MCP_URL=http://localhost:8002/mcp

OPENAI_KEY=$(grep OPENAI_API_KEY "$TRIAGE_DIR/.env" 2>/dev/null | cut -d= -f2-)
if [ -z "$OPENAI_KEY" ]; then
    echo "WARNING: OPENAI_API_KEY not found in .env. MCP servers will not start."
    exit 0
fi
export OPENAI_API_KEY="$OPENAI_KEY"

cd "$TRIAGE_DIR"

echo "Starting triage MCP servers..."

python3 fhir_server.py > /tmp/fhir_server.log 2>&1 &
python3 triage_server.py > /tmp/triage_server.log 2>&1 &
python3 clinical_reasoning_server.py > /tmp/cr_server.log 2>&1 &

for port in 8000 8001 8002; do
    for i in $(seq 1 30); do
        if python3 -c "import requests; r=requests.get('http://localhost:$port/mcp', headers={'Accept':'text/event-stream'}, timeout=2); exit(0 if r.status_code in [200,406] else 1)" 2>/dev/null; then
            echo "  MCP server on port $port ready"
            break
        fi
        sleep 1
    done
done

echo "Triage MCP servers started."

echo "Loading seed data (if not already loaded)..."
PATIENT_COUNT=$(python3 -c "import requests; r=requests.get('http://localhost:52773/fhir/r4/Patient', params={'_tag':'triage-seed','_count':1}, headers={'Accept':'application/fhir+json'}, auth=('_SYSTEM','SYS'), timeout=10); print(r.json().get('total',0))" 2>/dev/null || echo "0")
if [ "$PATIENT_COUNT" = "0" ]; then
cd "$TRIAGE_DIR"
FHIR_BASE_URL=http://localhost:52773/fhir/r4 FHIR_USER=_SYSTEM FHIR_PASS=SYS python3 seed_data.py load >> /tmp/mcp_startup.log 2>&1
echo "Seed data loaded."
else
echo "Seed data already exists ($PATIENT_COUNT patients). Skipping."
fi

echo "Starting Gradio UI on port 7860..."
cd "$TRIAGE_DIR"
python3 app.py >> /tmp/mcp_startup.log 2>&1 &
echo "Gradio UI started."
