# Agente de Triagem Pre-Consulta — FHIR-First Agentic AI

Agente autonomo de triagem clinica que opera SOBRE dados FHIR. Primeiro consulta o historico do paciente no InterSystems IRIS for Health, depois conduz uma triagem inteligente personalizada, e por fim atualiza o prontuario FHIR de volta com recursos criados durante a consulta.

## Arquitetura

```
FHIR Server (IRIS for Health :52773/:32783)
    |
fhir_server.py (MCP :8000) — 11 ferramentas CRUD FHIR
    |
triage_server.py (MCP :8001) — 4 ferramentas de triagem contextual
    |
clinical_reasoning_server.py (MCP :8002) — 4 ferramentas de raciocinio clinico
    |
 agent.py (LangChain + OpenAI gpt-4o-mini) — core do agente (factory, system prompt)
 cli.py — interface CLI interativa (importa de agent.py)
 app.py (Gradio :7860) — UI web com chat para demo
```

## Fluxo do Agente (5 etapas obrigatorias)

1. **FHIR Query** — Consulta Patient, Condition, MedicationRequest, Observation, AllergyIntolerance, Encounter
2. **Triagem Contextual** — Com historico em maos, gera perguntas inteligentes (nao genericas)
3. **Conversa Interativa** — Loop de chat onde o paciente responde, agente aprofunda
4. **Clinical Reasoning** — Cruza historico FHIR + sintomas novos → avalia risco, sugere prioridade
5. **FHIR Update** — Cria Observation, QuestionnaireResponse, Flag, Task, Encounter de volta no servidor

## Prerequisitos

- Docker + Docker Compose
- OpenAI API Key (modelo gpt-4o-mini)

## Como Rodar via Docker

1. Copie `.env.example` para `.env` e preencha sua `OPENAI_API_KEY`:

```bash
cd python/triage
cp .env.example .env
# edite .env e coloque sua chave real
```

2. Build e start do container:

```bash
docker compose build --no-cache --progress=plain
docker compose up -d
```

3. Acesse a UI Gradio: **http://localhost:7860**

Os MCP servers iniciam automaticamente junto com o container via `custom-entrypoint.sh` → `start_mcp_servers.sh`. Os dados de teste (4 pacientes) sao carregados automaticamente na primeira vez que o container sobe.

## Como Rodar Manualmente (dentro do container)

Se precisar rodar os servidores manualmente para debug:

```bash
# Entre no container
docker compose exec iris bash

# Va para o diretorio do triage
cd /home/irisowner/irisdev/python/triage

# Start os 3 MCP servers + Gradio
bash start_servers.sh
```

Ou rode cada componente separadamente:

```bash
# Terminal 1: FHIR MCP Server
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 fhir_server.py

# Terminal 2: Triage MCP Server
python3 triage_server.py

# Terminal 3: Clinical Reasoning MCP Server
python3 clinical_reasoning_server.py

# Terminal 4: Gradio UI (ou cli.py para CLI)
FHIR_BASE_URL=http://localhost:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 app.py
```

## Portas

| Porta (host) | Porta (container) | Servico |
|---|---|---|
| 32782 | 1972 | IRIS SuperServer |
| 32783 | 52773 | IRIS Web/REST (FHIR API) |
| 32784 | 53773 | IRIS adicional |
| 8000 | 8000 | FHIR MCP Server |
| 8001 | 8001 | Triage MCP Server |
| 8002 | 8002 | Clinical Reasoning MCP Server |
| 7860 | 7860 | Gradio Web UI |

## Pacientes de Teste

O script `seed_data.py` carrega 4 pacientes FHIR com cenarios clinicos distintos:

| Paciente | Idade | Condicoes | Cenario Esperado |
|---|---|---|---|
| **Maria Silva** | 58, F | DM2 + HAS | Diabetes descompensada, risco cardiovascular elevado |
| **Joao Santos** | 72, M | IC + FA + DM2 + HAS + DRC | Polifarmacia, interacoes medicamentosas, risco alto |
| **Ana Costa** | 28, F | Nenhuma condicao ativa | Perguntas genericas, sem red flags, prioridade routine |
| **Roberto Lima** | 65, M | DPOC + HAS + Artrose + Depressao | Red flags respiratorias, alergia grave, prioridade urgent |

Para recarregar os dados de teste (dentro do container):

```bash
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py clean
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py load
```

Para listar pacientes carregados:

```bash
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py list
```

**Nota:** Os IDs dos pacientes mudam a cada reload. Use o nome do paciente na conversa com o agente.

## Uso

### Gradio UI (http://localhost:7860)

1. Abra o navegador em `http://localhost:7860`
2. Digite o nome do paciente (ex: "Maria Silva") para iniciar a triagem
3. O agente consulta o FHIR, faz perguntas contextuais, analisa risco e atualiza o prontuario

### CLI (cli.py)

```bash
# Dentro do container
cd /home/irisowner/irisdev/python/triage
FHIR_BASE_URL=http://localhost:52773/fhir/r4 OPENAI_API_KEY=sk-... python3 cli.py
```

Interacao por texto no terminal. Digite `sair` para encerrar.

## Estrutura de Arquivos

```
python/triage/
  .env                  # Configuracao (FHIR_BASE_URL, OPENAI_API_KEY) — NAO tracked no git
  .env.example          # Template sem credenciais
  requirements.txt      # Dependencias Python
  seed_data.py          # Script para carregar/limpar/listar pacientes de teste
  seed_data/            # Bundles FHIR JSON para carga
    patient_maria_silva.json
    patient_joao_santos.json
    patient_ana_costa.json
    patient_roberto_lima.json
  fhir_server.py        # MCP Server 1 — FHIR CRUD (porta 8000)
  triage_server.py      # MCP Server 2 — triagem contextual (porta 8001)
  clinical_reasoning_server.py  # MCP Server 3 — raciocinio clinico (porta 8002)
 agent.py # Core do agente (SYSTEM_PROMPT, create_triage_agent, extract_ai_response)
 cli.py # Interface CLI interativa
 app.py # UI Gradio chat — Web
  start_servers.sh      # Script para start dos 3 MCP servers + Gradio
  PLAN.md               # Plano de arquitetura e ferramentas
  PROGRESS.md           # Historico de progresso, descobertas e decisoes
  README.md             # Este arquivo
```

## MCP Servers — Ferramentas

### fhir_server.py (porta 8000) — 11 ferramentas

| Ferramenta | Metodo FHIR | Descricao |
|---|---|---|
| `get_patient` | GET /Patient/{id} | Demograficos |
| `get_patient_conditions` | GET /Condition?patient={id} | Condicoes |
| `get_patient_medications` | GET /MedicationRequest?patient={id} | Medicacoes |
| `get_patient_observations` | GET /Observation?patient={id} | Observacoes |
| `get_patient_allergies` | GET /AllergyIntolerance?patient={id} | Alergias |
| `get_patient_encounters` | GET /Encounter?patient={id} | Encontros |
| `create_observation` | POST /Observation | Nova observacao |
| `create_condition` | POST /Condition | Nova condicao |
| `create_questionnaire_response` | POST /QuestionnaireResponse | Triagem estruturada |
| `create_encounter` | POST /Encounter | Encontro pre-consulta |
| `create_flag_and_task` | POST /Flag + POST /Task | Alerta + follow-up |

### triage_server.py (porta 8001) — 4 ferramentas

| Ferramenta | Descricao |
|---|---|
| `build_contextual_questions` | Gera perguntas contextuais baseadas no historico FHIR |
| `parse_symptoms` | Extrai sintomas, duracao, severidade |
| `check_red_flags` | Verifica sinais de alerta |
| `build_questionnaire_response_data` | Monta QuestionnaireResponse FHIR |

### clinical_reasoning_server.py (porta 8002) — 4 ferramentas

| Ferramenta | Descricao |
|---|---|
| `assess_clinical_risk` | Score de risco com justificativa |
| `suggest_priority` | Prioridade de atendimento |
| `generate_clinical_summary` | Resumo para o medico |
| `identify_follow_up_tasks` | Tarefas de follow-up |

## Troubleshooting

### Verificar se os MCP servers estao rodando

```bash
docker compose exec iris bash -c 'cat /tmp/fhir_server.log'
docker compose exec iris bash -c 'cat /tmp/triage_server.log'
docker compose exec iris bash -c 'cat /tmp/cr_server.log'
```

### Reiniciar os MCP servers manualmente

```bash
docker compose exec iris bash -c 'pkill -f fhir_server.py; pkill -f triage_server.py; pkill -f clinical_reasoning_server.py'
docker compose exec iris bash /home/irisowner/irisdev/start_mcp_servers.sh
```

### Recarregar dados de teste

```bash
docker compose exec iris bash -c 'cd /home/irisowner/irisdev/python/triage && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py clean && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py load'
```

### Erro "OPENAI_API_KEY not set"

Verifique se o arquivo `python/triage/.env` existe e contem a variavel `OPENAI_API_KEY` com uma chave valida.

### Porta 7860 nao acessivel

1. Verifique se o container esta rodando: `docker compose ps`
2. Verifique se a porta esta mapeada no `docker-compose.yml` (`7860:7860`)
3. Verifique o log do Gradio: `docker compose exec iris bash -c 'cat /tmp/mcp_startup.log'`

### Pip installs se perdem ao reiniciar o container

As dependencias do triage sao instaladas no Dockerfile (linha `pip3 install ...`). Se voce instalou algo extra manualmente com pip dentro do container, sera perdido no restart. Adicione novas dependencias ao `Dockerfile` e ao `requirements.txt` para persistencia.

## Stack Tecnologica

- **FHIR Server**: InterSystems IRIS for Health Community Edition
- **MCP**: FastMCP com transport streamable-http
- **Agente**: LangChain + langchain-mcp-adapters + OpenAI gpt-4o-mini
- **UI**: Gradio ChatInterface
- **Linguagem**: Python 3
