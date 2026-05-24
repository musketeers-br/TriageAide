## Agente de Triagem Pre-Consulta

**Objetivo:** preparar o atendimento *antes* do paciente falar com o profissional.

### Como funciona

1. **FHIR Query First** — O agente consulta o historico do paciente no FHIR Server (InterSystems IRIS for Health) ANTES de iniciar a conversa
2. **Triagem Contextual** — Com o historico em maos, gera perguntas inteligentes e personalizadas (nao genericas)
3. **Conversa com o Paciente** — Coleta sintomas, historico recente e sinais de alerta via chat
4. **Raciocinio Clinico** — Cruza historico FHIR + sintomas novos para avaliar risco e prioridade
5. **Atualizacao FHIR Bidirecional** — Cria novos recursos FHIR no servidor (Observation, Encounter, Flag, Task, QuestionnaireResponse)

### Frase-chave

> "The agent first retrieves patient history from a FHIR server, builds contextual clinical understanding, and performs an adaptive pre-consultation triage that enriches and updates the longitudinal patient record."

### Stack Tecnologica

| Componente | Tecnologia |
|---|---|
| FHIR Server | InterSystems IRIS for Health Community Edition |
| MCP Servers | FastMCP (streamable-http) — 3 servers, 19 ferramentas |
| Agente | LangChain + langchain-mcp-adapters + OpenAI gpt-4o-mini |
| UI | Gradio ChatInterface |
| Deploy | Docker (auto-startup MCP servers + seed data) |

### Arquitetura

```
FHIR Server (IRIS for Health)
    |
    +-- fhir_server.py (MCP :8000) — 11 ferramentas CRUD FHIR
    |       get_patient, get_conditions, get_medications, get_observations,
    |       get_allergies, get_encounters,
    |       create_observation, create_condition, create_questionnaire_response,
    |       create_encounter, create_flag_and_task
    |
    +-- triage_server.py (MCP :8001) — 4 ferramentas de triagem
    |       build_contextual_questions, parse_symptoms,
    |       check_red_flags, build_questionnaire_response_data
    |
    +-- clinical_reasoning_server.py (MCP :8002) — 4 ferramentas de raciocinio
    |       assess_clinical_risk, suggest_priority,
    |       generate_clinical_summary, identify_follow_up_tasks
    |
    +-- LangChain Agent (agent.py / cli.py / app.py)
            system_prompt com 5 etapas obrigatorias
            responde em portugues brasileiro
```

### Recursos FHIR usados

**Leitura (historico do paciente):**
- Patient — dados demograficos
- Condition — condicoes/_diagnosticos
- MedicationRequest — medicacoes em uso
- Observation — resultados laboratoriais e sinais vitais
- AllergyIntolerance — alergias
- Encounter — encontros anteriores

**Escrita (triagem pre-consulta):**
- Observation — novos sintomas relatados
- QuestionnaireResponse — triagem estruturada
- Encounter — encontro de pre-consulta preparado
- Flag — alertas clinicos (red flags)
- Task — tarefas de follow-up para o medico
- Condition — novas condicoes identificadas (se aplicavel)

### Pacientes de Teste

| Paciente | Idade | Cenario | Prioridade Esperada |
|---|---|---|---|
| Maria Silva | 58, F | DM2 + HAS descompensada | Urgente |
| Joao Santos | 72, M | Polifarmacia + IC + FA | Urgente/Emergencia |
| Ana Costa | 28, F | Sem condicoes ativas | Rotina |
| Roberto Lima | 65, M | DPOC + SpO2 93% + red flags | Emergencia |

### Resultado

O medico recebe:

- resumo clinico automatico com historico + novos sintomas
- prioridade de atendimento sugerida (routine/urgent/emergency)
- alertas de red flags (Flag resource)
- tarefas de follow-up (Task resource)
- QuestionnaireResponse com toda a triagem estruturada

Tudo registrado como recursos FHIR no prontuario — FHIR vira **memoria clinica viva**.

### Diferencial para o Concurso

O agente NAO e um chatbot generico que cria FHIR do zero. Ele e um **AI Agent interoperavel que raciocina sobre dados clinicos existentes**:

1. **FHIR-First**: consulta historico ANTES de interagir com o paciente
2. **Triagem Contextual**: perguntas inteligentes baseadas no historico real
3. **Bidirecional**: le E escreve no FHIR Server
4. **MCP Architecture**: 3 servers especializados com 19 ferramentas
5. **Longitudinal**: entende continuidade do cuidado (ex: "ultima consulta ha 8 meses")

### Interacao

- **Web UI**: Gradio ChatInterface em http://localhost:7860
- **CLI**: Loop interativo via `python cli.py`
- **Idioma**: Portugues brasileiro
- **Futuro**: Interacao por voz (planejado)