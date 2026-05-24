# 🩺 Cenário Refinado — Agente de Triagem Pré-Consulta (FHIR-First)

## 🎯 Ideia central corrigida

O agente NÃO começa perguntando tudo do zero.

Ele primeiro:

✅ consulta o **FHIR Server**
✅ entende o histórico do paciente
✅ depois conduz uma triagem inteligente personalizada

Isso mostra:

* interoperabilidade real
* uso correto do FHIR
* inteligência contextual do agente

👉 Pontua MUITO mais no concurso.

---

# 🧠 Novo Fluxo do Cenário

## 👩 Paciente

Maria Silva — 58 anos
Consulta marcada para amanhã.

---

## 🔎 Etapa 1 — AI Agent consulta FHIR (ANTES da conversa)

O agente acessa o **InterSystems IRIS for Health FHIR Server**.

Busca automaticamente:

### Recursos FHIR recuperados

* `Patient`
* `Condition`
* `MedicationRequest`
* `Observation`
* `AllergyIntolerance`
* `Encounter` anteriores

Exemplo encontrado:

* Diabetes tipo 2
* Hipertensão
* HbA1c elevada
* Uso de Metformina
* Última consulta há 8 meses

---

## ⭐ O insight importante

Agora o agente **já conhece o paciente**.

Ele não faz perguntas genéricas.

Ele faz perguntas clínicas inteligentes.

---

## 🎤 Etapa 2 — Triagem Contextual Inteligente

Em vez de:

> “Você tem alguma doença?”

O agente pergunta:

✅ “Maria, notei que você tem diabetes. Seu açúcar anda controlado?”
✅ “Você teve falta de ar recentemente?”
✅ “Mudou alguma medicação?”

Isso demonstra:

👉 **AI Agent operando SOBRE FHIR**, não apenas usando IA.

---

## 🧬 Etapa 3 — Atualização FHIR (Bidirectional)

Após a conversa:

O agente **não cria tudo do zero**.

Ele:

* complementa histórico existente
* adiciona novas observações

### Recursos atualizados

* `Observation` → fadiga recente
* `QuestionnaireResponse` → triagem
* `ClinicalImpression` → avaliação pré-consulta
* `Encounter` → preparado para atendimento

FHIR vira **memória clínica viva**.

---

## ⚠️ Etapa 4 — Clinical Risk Reasoning

O agente cruza:

FHIR histórico + sintomas novos

```
Diabetes + dispneia recente + ausência de acompanhamento
→ risco cardiovascular elevado
```

Cria:

* `Flag`
* `Task`
* prioridade alta de atendimento

---

## 👨‍⚕️ Etapa 5 — Médico abre o prontuário

O médico vê:

✅ histórico já consolidado
✅ novos sintomas destacados
✅ resumo clínico automático
✅ prioridade sugerida

---

# 🏗️ Arquitetura correta para o concurso

```
FHIR Server (IRIS for Health)
        ↑
FHIR Query Agent   ← ⭐ começa aqui
        ↓
Triage Conversation Agent
        ↓
Clinical Reasoning Agent
        ↓
FHIR Update Agent
        ↓
Clinical Summary
```

---

# 🏆 Por que essa versão é MUITO melhor

Você passa de:

❌ chatbot que gera FHIR

para:

✅ **AI Agent interoperável que raciocina sobre dados clínicos existentes**

Isso é exatamente o futuro que a InterSystems promove.

---

# 💡 Frase perfeita para o submission

Use algo assim:

> “The agent first retrieves patient history from a FHIR server, builds contextual clinical understanding, and performs an adaptive pre-consultation triage that enriches and updates the longitudinal patient record.”

Juiz lê isso → entende maturidade técnica imediatamente.

---

# ⭐ Upgrade que quase ninguém vai fazer (mas você deveria)

Adicionar:

## 🧠 Longitudinal Patient Understanding

O agente mostra:

> “Last visit 8 months ago — follow-up overdue.”

🔥 Isso demonstra:

* continuidade do cuidado
* valor clínico real
* uso avançado de FHIR timeline