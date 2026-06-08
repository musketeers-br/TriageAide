# Useful Commands

## Clean up Docker

```bash
docker system prune -f
```

## Build containers with no cache

```bash
docker compose build --no-cache --progress=plain
```

## Start containers

```bash
docker compose up -d
```

## Stop containers

```bash
docker compose down
```

## Open IRIS terminal

```bash
docker compose exec iris iris session iris -U FHIRServer
```

## FHIR Namespace setup

```
Do ##class(HS.Util.Installer.Foundation).Install(namespace)
```

## FHIR server configuration setup

```bash
do ##class(HS.FHIRServer.ConsoleSetup).Setup()
```

## Load FHIR resources

```bash
zw ##class(HS.FHIRServer.Tools.DataLoader).SubmitResourceFiles("/irisdev/app/output/fhir/", "FHIRServer", "/fhir/r4")
```

---

## Triage App — Pre-Consultation Triage Agent

### Rebuild containers (after changes in ObjectScript or Dockerfile)

```bash
docker compose build --no-cache --progress=plain && docker compose up -d
```

### Check MCP server status (triage container)

```bash
docker compose exec triage bash -c 'tail -5 /tmp/fhir_server.log'
docker compose exec triage bash -c 'tail -5 /tmp/triage_server.log'
docker compose exec triage bash -c 'tail -5 /tmp/cr_server.log'
```

### Live logs

```bash
# All modules (respects LOG_LEVEL in .env, default DEBUG)
docker compose logs triage -f

# DEBUG lines only
docker compose logs triage -f | grep DEBUG

# Per-module follow
docker compose exec triage tail -f /tmp/fhir_server.log
```

### Restart MCP servers manually

```bash
docker compose exec triage bash -c 'pkill -f fhir_server.py; pkill -f triage_server.py; pkill -f clinical_reasoning_server.py'
docker compose exec triage bash -c 'cd /app && bash start_servers.sh'
```

### Reload test data (seed data)

```bash
docker compose exec triage bash -c 'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py clean && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py load'
```

### List test patients

```bash
docker compose exec triage bash -c 'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 seed_data.py list'
```

### Access the triage UI

```
http://localhost:7860
```

### Run agent CLI manually

```bash
docker compose exec triage bash
cd /app
FHIR_BASE_URL=http://iris:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 cli.py
```

### Run MCP servers + Gradio manually (debug)

```bash
docker compose exec triage bash
cd /app
bash start_servers.sh
```

### Check triage container logs

```bash
docker compose logs triage
```

### Triage app ports

| Port | Service |
|---|---|
| 8000 | FHIR MCP Server |
| 8001 | Triage MCP Server |
| 8002 | Clinical Reasoning MCP Server |
| 7860 | Gradio Web UI |

### FHIR API (verify patients)

```bash
curl -u _SYSTEM:SYS http://localhost:32783/fhir/r4/Patient?_count=5 -H "Accept: application/fhir+json"
```

### Debug URLs

```
http://localhost:32783/fhirUI/irisfhir.json
http://localhost:32783/fhirUI/irisfhir_swagger.json
http://localhost:32783/fhir/r4/metadata
```
