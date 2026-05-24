# Progresso — Agente de Triagem Pre-Consulta

## Historico de Progresso

### Fase 1: Conceito e Planejamento

- Definido o cenario FHIR-First: agente consulta historico ANTES de conversar com o paciente
- Documentado em `doc/scenario1.md` (fluxo das 5 etapas) e `doc/app-description.md` (conceito)
- Decisao arquitetural: 3 MCP servers (FHIR, Triage, Clinical Reasoning) + agente LangChain + Gradio UI
- Decisao de stack: FastMCP (streamable-http), langchain-mcp-adapters, OpenAI gpt-4o-mini, Gradio
- Decisao de idioma: agente responde em portugues brasileiro
- Decisao de deployment: MCP servers rodam dentro do container Docker (nao externamente)
- Criado `python/triage/PLAN.md` com especificacao completa de ferramentas e cenarios de teste

### Fase 2: Implementacao dos MCP Servers

- **fhir_server.py** (porta 8000): 11 ferramentas CRUD FHIR implementadas
  - 6 ferramentas de leitura: get_patient, get_patient_conditions, get_patient_medications, get_patient_observations, get_patient_allergies, get_patient_encounters
  - 5 ferramentas de escrita: create_observation, create_condition, create_questionnaire_response, create_encounter, create_flag_and_task
  - Descoberta critica: IRIS FHIR Server retorna HTTP 201 com body vazio em POSTs. O ID do recurso criado vem no header `Location` no formato `http://host/fhir/r4/ResourceType/ID/_history/1`. Fix implementado em `_fhir_post()`.
- **triage_server.py** (porta 8001): 4 ferramentas implementadas
  - `build_contextual_questions`: gera perguntas baseadas no historico FHIR (nao genericas)
  - `parse_symptoms`: extrai sintomas, duracao, severidade do texto do paciente
  - `check_red_flags`: cruza sintomas com condicoes existentes para identificar sinais de alerta
  - `build_questionnaire_response_data`: monta QuestionnaireResponse FHIR estruturado
- **clinical_reasoning_server.py** (porta 8002): 4 ferramentas implementadas
  - `assess_clinical_risk`: scoring com pesos por condicao cronica, sintoma e observacao anormal
  - `suggest_priority`: mapeia score para routine/urgent/emergency
  - `generate_clinical_summary`: resumo clinico para o medico
  - `identify_follow_up_tasks`: tarefas de follow-up baseadas em risco e gaps de cuidado

### Fase 3: Agente Orquestrador

- **agent.py**: Core do agente (SYSTEM_PROMPT, create_triage_agent(), extract_ai_response())
- **cli.py**: Interface CLI interativa (importa de agent.py)
- **app.py**: Gradio ChatInterface web (importa de agent.py)
  - Descoberta: Gradio 6.x removeu o parametro `type="messages"`. History passado como `list[dict]` com `role`/`content`.
  - Descoberta: `asyncio.run()` nao pode ser chamado dentro de loop async existente (Gradio). Usado `asyncio.get_event_loop().run_until_complete()` ou abordagem equivalente.
- System prompt detalhado com as 5 etapas obrigatorias, regras de idioma e formato de saida

### Fase 4: Dados de Teste (seed_data.py)

- Criados 4 bundles FHIR JSON completos em `seed_data/`:
  - **Maria Silva**: DM2 + HAS + HbA1c 8.2% + Metformina + Losartana + Alergia Penicilina
  - **Joao Santos**: IC + FA + DM2 + HAS + DRC estagio 3 + Warfarina + Alergia AAS
  - **Ana Costa**: Sem condicoes ativas, sem medicamentos
  - **Roberto Lima**: DPOC + HAS + Artrose + Depressao + SpO2 93% + Alergia Dipirona (anafilaxia)
- **Descoberta critica**: Bundles FHIR com `urn:uuid:` references nao funcionam com POSTs individuais no IRIS FHIR Server. Rewrite do seed_data.py para: (1) criar Patient primeiro, (2) resolver todas as `urn:uuid:` references para `Patient/{actual_id}`, (3) criar recursos dependentes.
- Funcionalidades: `load` (carrega pacientes), `clean` (remove pacientes com tag `triage-seed`), `list` (lista pacientes carregados)
- Pacientes marcados com tag `triage-seed` para facilitar identificacao e limpeza

### Fase 5: Infraestrutura Docker

- **Dockerfile**: adicionada linha `pip3 install requests python-dotenv fastmcp langchain langchain-mcp-adapters langchain-openai gradio`
- **docker-compose.yml**: portas adicionadas 8000, 8001, 8002, 7860; entrypoint customizado
- **custom-entrypoint.sh**: wrapper que inicia MCP servers em background antes do entrypoint IRIS
- **start_mcp_servers.sh**: script que (1) le OPENAI_API_KEY do .env, (2) starta 3 MCP servers, (3) aguarda readiness, (4) carrega seed data automaticamente se nao existir
- **start_servers.sh** (dentro de python/triage): versao manual para debug, start MCP servers + Gradio em foreground

### Fase 6: Teste End-to-End

- Teste completo com Maria Silva: agente consultou FHIR, gerou perguntas contextuais, analisou sintomas, avaliou risco (moderate), criou Encounter resource de volta no FHIR

### Fase 7: Bugfixes Criticos

- **Bug: Gradio nao iniciava no boot do container** — `start_mcp_servers.sh` so iniciava os 3 MCP servers, nao o `app.py`. Adicionadas linhas para start do Gradio em background.
- **Bug: MCP sessions fechavam apos `_get_agent()`** — O padrao `async with _client.session(...)` carregava as ferramentas dentro de um context manager que fechava as sessoes MCP ao retornar. Quando o agente tentava chamar uma ferramenta, a sessao ja estava fechada. Solucao: usar `_client.get_tools()` que cria sessoes por chamada, em vez de `load_mcp_tools(session)` dentro de context manager.
- **Bug: Agente chamava `get_patient("Maria Silva")` em vez do ID** — O LLM nao sabia que precisava do ID numerico. Solucao: adicionada ferramenta `search_patients(name)` ao fhir_server.py com busca multi-estrategia (family, given, name).
- **Bug: IRIS FHIR `name` param nao suporta nome completo** — `?name=Maria Silva` retorna 0 resultados. `?family=Silva` ou `?given=Maria` funciona. Solucao: `search_patients` tenta multiplas estrategias (family, given, name parcial).
- Validacao do fluxo completo das 5 etapas

---

## Descobertas Tecnicas (Lessons Learned)

### 1. IRIS FHIR Server: POST retorna body vazio (HTTP 201)

O InterSystems IRIS for Health FHIR Server retorna HTTP 201 Created com **body vazio** ao criar recursos via POST. O ID do recurso criado esta no header `Location`:

```
Location: http://host/fhir/r4/Patient/123/_history/1
```

**Impacto**: Qualquer codigo que faca `resp.json()` apos um POST vai falhar com JSONDecodeError.

**Solucao**: `_fhir_post()` extrai o ID do header Location via regex e retorna `{"id": extracted_id}` em vez de `resp.json()`.

### 2. Referencias `urn:uuid:` nao funcionam com POSTs individuais

Bundles FHIR transacionais com `urn:uuid:` references pressupoem que o servidor resolve as referencias no contexto do bundle. O IRIS FHIR Server (via POSTs individuais fora de transaction) nao resolve essas referencias.

**Solucao**: Rewrite do `seed_data.py` para criar o Patient primeiro, extrair o ID real, e substituir todas as ocorrencias de `urn:uuid:` pelo `Patient/{actual_id}` antes de criar os recursos dependentes.

### 3. `load_dotenv()` NAO sobrescreve variaveis de ambiente existentes

Se uma variavel de ambiente ja esta definida no shell (via `export`), `load_dotenv()` nao a sobrescreve. Isso causa confusao quando `start_servers.sh` faz `export FHIR_BASE_URL=http://localhost:52773/fhir/r4` (porta interna do container) mas o `.env` tem `http://localhost:32783/fhir/r4` (porta do host).

**Solucao**: `start_servers.sh` e `start_mcp_servers.sh` exportam `FHIR_BASE_URL` com a porta interna (52773) explicitamente antes de rodar os servidores. O `.env` fica com a porta do host (32783) para uso quando rodando fora do container.

### 4. Pip installs em container rodando sao perdidos no restart

Qualquer `pip install` feito manualmente dentro do container e perdido quando o container e recriado.

**Solucao**: Todas as dependencias do triage foram adicionadas ao Dockerfile na linha `pip3 install ...`. Para novas dependencias, atualizar Dockerfile + requirements.txt e rebuild.

### 5. Gradio 6.x: API changes

- `gr.ChatInterface` nao aceita mais o parametro `type="messages"`
- History e passado como `list[dict]` com chaves `role` e `content`
- Nao e possivel chamar `asyncio.run()` dentro de um event loop existente (Gradio roda async internamente)

**Solucao**: Removido `type="messages"`, ajustado formato do history, usado gerenciamento adequado de event loop async.

### 6. `create_agent()` suporta `system_prompt`

A funcao `create_agent()` do `langchain.agents` aceita o parametro `system_prompt`. Isso e melhor do que pre-prepender `SystemMessage` manualmente na lista de mensagens, pois o framework gerencia o system prompt de forma mais robusta.

### 7. MCP sessions via `async with` fecham apos o context manager

Usar `async with _client.session("server")` para carregar ferramentas e perigoso: as sessoes MCP sao fechadas quando o bloco `async with` termina. O agente entao nao consegue chamar as ferramentas porque as sessoes estao mortas.

**Solucao**: Usar `_client.get_tools()` que carrega ferramentas criando sessoes por chamada (cada tool call abre e fecha sua propria sessao). Nao usar `load_mcp_tools(session)` dentro de context manager para criar o agente.

### 8. IRIS FHIR `name` search param nao suporta nome completo

O parametro `?name=Maria Silva` retorna 0 resultados no IRIS FHIR Server. A busca funciona apenas com partes do nome: `?family=Silva` ou `?given=Maria`.

**Solucao**: `search_patients()` tenta multiplas estrategias: (1) `family` + `given` separados, (2) `name` com cada parte individualmente. Para na primeira que retorna resultados.

---

## Decisoes Arquiteturais

| Decisao | Alternativa Considerada | Justificativa |
|---|---|---|
| 3 MCP servers separados | 1 MCP server monolitico | Separacao de responsabilidades: FHIR (dados), Triage (logica de triagem), Clinical Reasoning (raciocinio). Facilita manutencao e extensao. |
| FastMCP streamable-http | stdio transport | Streamable-http permite que os servicos rodem em portas separadas e sejam acessiveis via HTTP, compativel com containerizacao. |
| gpt-4o-mini | gpt-4o, gpt-3.5-turbo | Custo-beneficio: gpt-4o-mini e barato e competente para triagem. gpt-4o seria overkill para o escopo. |
| MCP servers dentro do container | MCP servers fora do container | Simplifica deployment: tudo sobe junto com `docker compose up`. Nao requer configuracao de rede externa para os MCP servers. |
| LangChain + langchain-mcp-adapters | MCP client customizado | langchain-mcp-adapters ja resolve a integracao MCP → LangChain tools. Evita reinventar a roda. |
| Gradio | Streamlit, Flask | Gradio ChatInterface e o mais simples para prototipar um chat. Streamlit exigiria mais codigo para o mesmo resultado. |
| seed_data.py com tag `triage-seed` | Remocao manual de recursos | Tag permite `clean` automatico: remove todos os recursos com a tag, sem precisar trackear IDs. |
| System prompt embutido no codigo | Prompt externo em arquivo | Simplifica deployment (1 arquivo a menos). Se precisar tornar configuravel, extrair para arquivo depois. |

---

## Status Atual

### Concluido

- [x] 3 MCP servers (FHIR, Triage, Clinical Reasoning) implementados e rodando
- [x] Core do agente (`agent.py`), CLI (`cli.py`) e Web UI (`app.py`) funcionais
- [x] 4 pacientes de teste com bundles FHIR completos
- [x] Seed data com load/clean/list
- [x] Infraestrutura Docker completa (Dockerfile, docker-compose, entrypoint customizado)
- [x] Auto-startup dos MCP servers + seed data no container
- [x] Teste end-to-end com Maria Silva
- [x] Documentacao (README, PROGRESS, PLAN atualizado)
- [x] Testar Gradio UI externamente (porta 7860 do host)
- [x] Testar com todos os 4 pacientes (Joao, Ana, Roberto)

### Pendente / Precisa Atencao

- [ ] Agente nem sempre cria todos os recursos FHIR esperados (Flag, Task, QuestionnaireResponse) — depende da decisao do LLM; pode precisar ajuste de prompt
- [ ] Adicionar ferramenta para buscar pacientes por nome (atualmente so funciona por ID)
- [ ] Container restart test para validar pipeline completo de auto-startup

### Trabalho Futuro / Nice-to-have

- [ ] Interacao por voz (mencionado em `doc/app-description.md`, nao implementado)
- [ ] Prompt refinement para garantir criacao consistente de QuestionnaireResponse e Tasks
- [ ] Preparacao para submissao ao concurso
- [ ] Testes automatizados (atualmente so testes manuais via curl/Gradio)
- [ ] Logging estruturado dos MCP servers
- [ ] Health check endpoints nos MCP servers
