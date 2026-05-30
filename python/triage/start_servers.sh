#!/bin/bash
set -e

cd /home/irisowner/irisdev/python/triage

export FHIR_BASE_URL=http://localhost:52773/fhir/r4
export FHIR_USER=_SYSTEM
export FHIR_PASS=SYS
export FHIR_MCP_URL=http://localhost:8000/mcp
export TRIAGE_MCP_URL=http://localhost:8001/mcp
export CR_MCP_URL=http://localhost:8002/mcp

if [ -n "$LANGSMITH_API_KEY" ]; then
  export LANGSMITH_TRACING=true
  export LANGSMITH_PROJECT=${LANGSMITH_PROJECT:-triage-aide}
  echo "LangSmith tracing enabled (project: $LANGSMITH_PROJECT)"
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY not set"
    exit 1
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
        if python3 -c "import requests; r=requests.get('http://localhost:$port/mcp', headers={'Accept':'text/event-stream'}); exit(0 if r.status_code in [200,406] else 1)" 2>/dev/null; then
            echo "  Port $port ready"
            break
        fi
        sleep 1
    done
done

echo "Starting Gradio UI on port 7860..."
python3 app.py

kill $FHIR_PID $TRIAGE_PID $CR_PID 2>/dev/null
