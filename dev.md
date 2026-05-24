# useful commands

## clean up docker
```bash
docker system prune -f
```

## build container with no cache
```bash
docker compose build --no-cache --progress=plain
```

## start container
```bash
docker compose up -d
```

## open terminal to docker
```bash
docker compose exec iris iris session iris -U FHIRServer
```

## FHIR Namespace setup

Do ##class(HS.Util.Installer.Foundation).Install(namespace)


## fhir server configuration setup
```bash
do ##class(HS.FHIRServer.ConsoleSetup).Setup()
```

## load fhir resources
```bash
zw ##class(HS.FHIRServer.Tools.DataLoader).SubmitResourceFiles("/irisdev/app/output/fhir/", "FHIRServer", "/fhir/r4")

kill ^%ISCLOG

kill ^ISCLOG

set ^%ISCLOG=3



http://localhost:32783/fhirUI/irisfhir.json
http://localhost:32783/fhirUI/irisfhir_swagger.json

---

## Triage App — Agente de Triagem Pre-Consulta

### Rebuild do container (apos mudancas em ObjectScript ou Dockerfile)
```bash
docker compose build --no-cache --progress=plain && docker compose up -d
```

### Verificar status dos MCP servers
```bash
docker compose exec iris bash -c 'cat /tmp/fhir_server.log | tail -5'
docker compose exec iris bash -c 'cat /tmp/triage_server.log | tail -5'
docker compose exec iris bash -c 'cat /tmp/cr_server.log | tail -5'
```

### Ver log completo de startup dos MCP servers
```bash
docker compose exec iris bash -c 'cat /tmp/mcp_startup.log'
```

### Reiniciar MCP servers manualmente
```bash
docker compose exec iris bash -c 'pkill -f fhir_server.py; pkill -f triage_server.py; pkill -f clinical_reasoning_server.py'
docker compose exec iris bash /home/irisowner/irisdev/start_mcp_servers.sh
```

### Recarregar dados de teste (seed data)
```bash
docker compose exec iris bash -c 'cd /home/irisowner/irisdev/python/triage && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py clean && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py load'
```

### Listar pacientes de teste
```bash
docker compose exec iris bash -c 'cd /home/irisowner/irisdev/python/triage && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py list'
```

### Acessar a UI do triage
```
http://localhost:7860
```

### Rodar agente CLI manualmente
```bash
docker compose exec iris bash
cd /home/irisowner/irisdev/python/triage
FHIR_BASE_URL=http://localhost:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 cli.py
```

### Rodar MCP servers + Gradio manualmente (debug)
```bash
docker compose exec iris bash
cd /home/irisowner/irisdev/python/triage
bash start_servers.sh
```

### Portas do triage app
| Porta | Servico |
|---|---|
| 8000 | FHIR MCP Server |
| 8001 | Triage MCP Server |
| 8002 | Clinical Reasoning MCP Server |
| 7860 | Gradio Web UI |

### FHIR API (verificar pacientes)
```bash
curl -u _SYSTEM:SYS http://localhost:32783/fhir/r4/Patient?_count=5 -H "Accept: application/fhir+json"
```

