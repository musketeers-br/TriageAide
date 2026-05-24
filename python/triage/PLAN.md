# Plano: Agente de Triagem Pre-Consulta — FHIR-First Agentic AI

## Objetivo

Construir uma aplicacao Python que implementa o cenario descrito em `doc/scenario1.md` — um **Agente de Triagem Pre-Consulta** que primeiro consulta o FHIR Server (InterSystems IRIS for Health), entende o historico do paciente, e depois conduz uma triagem inteligente personalizada, atualizando o prontuario FHIR de volta.

## Arquitetura

``` 
FHIR Server (IRIS for Health :32783)
|
fhir_server.py (MCP :8000) — 12 ferramentas CRUD FHIR
|
triage_server.py (MCP :8001) — 4 ferramentas de triagem contextual
|
clinical_reasoning_server.py (MCP :8002) — 4 ferramentas de raciocinio clinico
|
 agent.py (LangChain + OpenAI gpt-4o-mini) — core do agente (factory, system prompt)
 |
 cli.py — interface CLI interativa (importa de agent.py)
 app.py (Gradio) — UI web com chat para demo (:7860)
```

## Fluxo do Agente (5 etapas do scenario1.md)

1. **FHIR Query** — Agente consulta Patient, Condition, MedicationRequest, Observation, AllergyIntolerance, Encounter
2. **Triagem Contextual** — Com historico em maos, gera perguntas inteligentes (nao genericas)
3. **Conversa Interativa** — Loop de chat onde o paciente responde, agente aprofunda
4. **Clinical Reasoning** — Cruza historico FHIR + sintomas novos → avalia risco, sugere prioridade
5. **FHIR Update** — Cria Observation, QuestionnaireResponse, Flag, Task, Encounter de volta no servidor

## Dados de Teste (4 pacientes FHIR)

### Paciente 1: Maria Silva (cenario principal)
- Feminino, 58 anos | Diabetes tipo 2 + Hipertensao | HbA1c 8.2% | Metformina + Losartana
- Alergia a Penicilina | Ultima consulta ha 8 meses
- **Esperado:** agente identifica diabetes descompensada, pergunta contextualmente, risco cardiovascular elevado

### Paciente 2: Joao Santos (cardiovascular complexo)
- Masculino, 72 anos | IC + FA + DM2 + HAS + DRC estagio 3
- Warfarina + Metformina + Enalapril + Furosemida | Alergia AAS
- **Esperado:** polifarmacia, interacoes medicamentosas, risco alto

### Paciente 3: Ana Costa (jovem, baixo risco)
- Feminino, 28 anos | Nenhuma condicao ativa | Sem medicamentos
- **Esperado:** perguntas genericas, sem red flags, prioridade routine

### Paciente 4: Roberto Lima (polipatologia + sinais de alerta)
- Masculino, 65 anos | DPOC + HAS + Osteoartrite + Depressao
- SpO2 93% | Alergia Dipirona (anafilaxia)
- **Esperado:** red flags respiratorias + alergia grave, prioridade urgent/emergency

## Estrutura de Arquivos

```
python/triage/
  .env                        # FHIR_BASE_URL, OPENAI_API_KEY — NAO tracked no git
  .env.example                # Template sem credenciais
  requirements.txt            # Dependencias Python
  seed_data.py                # Script para carregar/limpar/listar pacientes de teste
  seed_data/                  # Bundles FHIR JSON para carga
    patient_maria_silva.json
    patient_joao_santos.json
    patient_ana_costa.json
    patient_roberto_lima.json
  fhir_server.py              # MCP Server 1 — FHIR CRUD (porta 8000)
  triage_server.py            # MCP Server 2 — triagem contextual (porta 8001)
  clinical_reasoning_server.py # MCP Server 3 — raciocinio clinico (porta 8002)
 agent.py # Core do agente (SYSTEM_PROMPT, create_triage_agent, extract_ai_response)
 cli.py # Interface CLI interativa
 app.py # UI Gradio chat — Web (:7860)
  start_servers.sh            # Script para start dos 3 MCP servers + Gradio (manual)
  PLAN.md                     # Este arquivo — plano de arquitetura
  PROGRESS.md                 # Historico de progresso, descobertas e decisoes
  README.md                   # Instrucoes de uso
```
python/triage/
  .env                    # FHIR_BASE_URL, OPENAI_API_KEY
  requirements.txt        # dependencias
  seed_data.py            # script para carregar pacientes de teste no FHIR
  seed_data/              # bundles FHIR JSON para carga
    patient_maria_silva.json
    patient_joao_santos.json
    patient_ana_costa.json
    patient_roberto_lima.json
  fhir_server.py          # MCP Server 1 — FHIR CRUD (porta 8000)
  triage_server.py        # MCP Server 2 — triagem contextual (porta 8001)
  clinical_reasoning_server.py  # MCP Server 3 — raciocinio clinico (porta 8002)
 agent.py # core do agente (factory, system prompt)
 cli.py # interface CLI interativa
 app.py # UI Gradio chat
  README.md               # instrucoes de uso
```

## MCP Servers — Ferramentas

### fhir_server.py (porta 8000) — 12 ferramentas

| Ferramenta | Metodo FHIR | Descricao |
|---|---|---|
| `search_patients(name)` | GET /Patient?name={name} | Busca pacientes por nome (parcial) |
| `get_patient(patient_id)` | GET /Patient/{id} | Demograficos |
| `get_patient_conditions(patient_id)` | GET /Condition?patient={id} | Condicoes |
| `get_patient_medications(patient_id)` | GET /MedicationRequest?patient={id} | Medicacoes |
| `get_patient_observations(patient_id, code, _count)` | GET /Observation?patient={id} | Observacoes |
| `get_patient_allergies(patient_id)` | GET /AllergyIntolerance?patient={id} | Alergias |
| `get_patient_encounters(patient_id, _count)` | GET /Encounter?patient={id} | Encontros |
| `create_observation(patient_id, code, display, value, unit, effective_date)` | POST /Observation | Nova observacao |
| `create_condition(patient_id, code, display, clinical_status)` | POST /Condition | Nova condicao |
| `create_questionnaire_response(patient_id, questions_responses)` | POST /QuestionnaireResponse | Triagem estruturada |
| `create_encounter(patient_id, reason, priority)` | POST /Encounter | Encontro pre-consulta |
| `create_flag_and_task(patient_id, flag_detail, task_detail, priority)` | POST /Flag + POST /Task | Alerta + follow-up |

### triage_server.py (porta 8001) — 4 ferramentas

| Ferramenta | Descricao |
|---|---|
| `build_contextual_questions(patient_context)` | Gera perguntas contextuais baseadas no historico FHIR |
| `parse_symptoms(patient_response)` | Extrai sintomas, duracao, severidade |
| `check_red_flags(symptoms, conditions)` | Verifica sinais de alerta |
| `build_questionnaire_response_data(patient_id, questions, answers)` | Monta QuestionnaireResponse FHIR |

### clinical_reasoning_server.py (porta 8002) — 4 ferramentas

| Ferramenta | Descricao |
|---|---|
| `assess_clinical_risk(conditions, new_symptoms, observations, medications)` | Score de risco com justificativa |
| `suggest_priority(risk_assessment)` | Prioridade de atendimento |
| `generate_clinical_summary(patient_data, triage_data, risk_data)` | Resumo para o medico |
| `identify_follow_up_tasks(risk, conditions, gaps_in_care)` | Tarefas de follow-up |

## Tecnicas

- **FHIR Client**: requests com Basic Auth (_SYSTEM:SYS) contra http://localhost:32783/fhir/r4 (host) ou http://localhost:52773/fhir/r4 (container)
- **LLM**: OpenAI gpt-4o-mini via langchain-openai
- **MCP**: fastmcp com transport="streamable-http"
- **Agente**: langchain-mcp-adapters + MultiServerMCPClient + load_mcp_tools + create_agent (com `system_prompt`)
- **UI**: Gradio gr.ChatInterface (6.x, sem `type="messages"`)
- **Deploy**: Docker com custom-entrypoint.sh que auto-starta MCP servers + seed data

## Descobertas & Challenges

> Detalhes completos em [PROGRESS.md](./PROGRESS.md#descobertas-tecnicas-lessons-learned)

| # | Descoberta | Impacto | Solucao |
|---|---|---|---|
| 1 | IRIS FHIR POST retorna body vazio (HTTP 201) | `resp.json()` falha com JSONDecodeError | Extrair ID do header `Location` via regex |
| 2 | `urn:uuid:` references nao resolvem com POSTs individuais | Bundles com referencias cross-resource falham | Criar Patient primeiro, resolver refs para `Patient/{id}`, depois criar dependentes |
| 3 | `load_dotenv()` nao sobrescreve env vars existentes | `FHIR_BASE_URL` errado quando rodando via script | Scripts exportam a URL correta (porta 52773) antes de rodar |
| 4 | Pip installs em container rodando sao perdidos no restart | Dependencias desaparecem | Adicionar ao Dockerfile + requirements.txt |
| 5 | Gradio 6.x removeu `type="messages"` | ChatInterface falha com parametro obsoleto | Remover parametro, usar formato `list[dict]` com `role`/`content` |
| 6 | `create_agent()` suporta `system_prompt` | SystemMessage manual e fragil | Usar parametro nativo do framework |
| 7 | MCP sessions via `async with` fecham apos context manager | Agente perde acesso as ferramentas MCP | Usar `_client.get_tools()` (sessao por chamada) em vez de `load_mcp_tools(session)` |
| 8 | IRIS FHIR `name` param nao suporta nome completo | `?name=Maria Silva` retorna 0 | `search_patients` tenta family, given e name parcial |

## Status

### Concluido

- [x] 3 MCP servers implementados e rodando
- [x] Core do agente (`agent.py`), CLI (`cli.py`) e Web UI (`app.py`) funcionais
- [x] 4 pacientes de teste com bundles FHIR completos
- [x] Seed data com load/clean/list + tag `triage-seed`
- [x] Infraestrutura Docker completa (auto-startup MCP + seed data)
- [x] Teste end-to-end com Maria Silva

### Pendente

- [ ] Testar Gradio UI externamente (porta 7860 do host)
- [ ] Testar com Joao Santos, Ana Costa, Roberto Lima
- [ ] Ajustar prompt para criacao consistente de Flag/Task/QuestionnaireResponse
- [ ] Adicionar busca de pacientes por nome
- [ ] Container restart test

### Trabalho Futuro

- [ ] Interacao por voz
- [ ] Testes automatizados
- [ ] Preparacao para submissao ao concurso
- [ ] Logging estruturado e health checks nos MCP servers

## Validacao

### Via Docker (recomendado)

```bash
# Build e start
docker compose build --no-cache --progress=plain
docker compose up -d

# Verificar MCP servers
docker compose exec iris bash -c 'cat /tmp/fhir_server.log'
docker compose exec iris bash -c 'cat /tmp/triage_server.log'
docker compose exec iris bash -c 'cat /tmp/cr_server.log'

# Verificar seed data
docker compose exec iris bash -c 'cd /home/irisowner/irisdev/python/triage && FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py list'

# Acessar Gradio UI
# http://localhost:7860

# Acessar FHIR API (verificar pacientes)
# http://localhost:32783/fhir/r4/Patient
```

### Manual (dentro do container)

```bash
docker compose exec iris bash
cd /home/irisowner/irisdev/python/triage

# 1. Carregar pacientes
FHIR_BASE_URL=http://localhost:52773/fhir/r4 python3 seed_data.py load

# 2. Start MCP servers + Gradio
bash start_servers.sh

# 3. Testar cada paciente e validar comportamento esperado
```

### Cenarios de Teste por Paciente

| Paciente | Acao | Resultado Esperado |
|---|---|---|
| Maria Silva | Informar nome, responder perguntas sobre diabetes | Risco cardiovascular moderado/alto, Flag + Task criados |
| Joao Santos | Informar nome, relatar sangramento | Red flag por warfarina, risco alto, prioridade urgent |
| Ana Costa | Informar nome, relatar sintoma leve | Risco baixo, prioridade routine, perguntas genericas |
| Roberto Lima | Informar nome, relatar falta de ar | Red flag respiratoria (DPOC + SpO2 93%), prioridade urgent/emergency |
