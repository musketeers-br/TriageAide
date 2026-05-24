#!/bin/bash
set -e

MCP_SCRIPT=/home/irisowner/irisdev/start_mcp_servers.sh

if [ -x "$MCP_SCRIPT" ]; then
    echo "Starting MCP servers in background..."
    nohup bash "$MCP_SCRIPT" > /tmp/mcp_startup.log 2>&1 &
fi

exec /docker-entrypoint.sh "$@"
