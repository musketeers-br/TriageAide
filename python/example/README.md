Fonte: https://docs.langchain.com/oss/python/langchain/mcp

Instalação:

```bash
pip install -r requirements.txt
```

No IRIS:

```bash
pip install -r requirements.txt --target /usr/irissys/mgr/python/
```

Como testar:

Abra um terminal e suba o MCP server:

```bash
python3 project_manager.py
python3 team_resource_manager.py
```

No container IRIS:

```bash
docker exec -it fhir-template python3 /home/irisowner/irisdev/python/example/project_manager.py
docker exec -it fhir-template python3 /home/irisowner/irisdev/python/example/team_resource_manager.py
``` 

Em outro terminal execute o agente:

```bash
python3 main_session_mult_mcp.py
```

No container IRIS:

```bash
docker exec -it fhir-template python3 /home/irisowner/irisdev/python/example/main_session_mult_mcp.py
``` 