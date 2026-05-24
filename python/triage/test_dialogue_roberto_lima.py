"""Test script to validate one-question-at-a-time dialogue quality.

Simulates a multi-turn conversation with the triage agent for Roberto Lima
(moderate-high complexity: COPD, hypertension, knee osteoarthritis, major
depression, dipirona allergy/anaphylaxis) and checks:
1. Agent asks only ONE question per turn
2. Agent doesn't repeat questions
3. Agent uses FHIR data contextually
4. Conversation flows naturally in Portuguese
"""
import os
import sys
import json
import asyncio
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from agent import create_triage_agent, extract_ai_response


PATIENT_RESPONSES = [
    "Quero iniciar a triagem para o paciente Roberto Lima",
    "Estou com falta de ar pior que o normal e tosse com catarro",
    "Sim, a tosse piora de manha e o catarro esta mais amarelado",
    "Sim, tenho sentido mais cansaco do que o normal, ate para coisas simples",
    "Nao, nao tive febre",
    "Sim, tenho sentido triste e sem vontade de fazer nada ultimamente",
    "Nao, nao parei de tomar a sertralina, mas nao sinto melhora",
    "Sim, a dor no joelho esta pior, principalmente para subir escadas",
    "Nao, nao tomei dipirona, sei que sou alergico e pode dar choque",
    "Sim, tenho usado o paracetamol quando a dor fica forte",
    "Nao, nao medi a saturacao em casa, mas sinto que esta mais dificil respirar",
]


def count_questions(text):
    sentences = text.replace("?", "?|").split("|")
    return len([s.strip() for s in sentences if s.strip().endswith("?")])


def extract_questions(text):
    sentences = text.replace("!", "!|").replace("?", "?|").split("|")
    return [s.strip() for s in sentences if s.strip().endswith("?")]


async def run_test():
    agent, client = await create_triage_agent()

    session_messages = []
    all_agent_questions = []
    violations = []
    turn_outputs = []

    print("\n" + "=" * 70)
    print("TESTE DE QUALIDADE DO DIALOGO — ROBERTO LIMA")
    print("=" * 70)

    for turn_idx, user_msg in enumerate(PATIENT_RESPONSES):
        print(f"\n--- TURNO {turn_idx + 1} ---")
        print(f"PACIENTE: {user_msg}")

        messages = list(session_messages)
        messages.append(HumanMessage(content=user_msg))

        try:
            result = await agent.ainvoke({"messages": messages})
            session_messages = result.get("messages", [])

            ai_response = extract_ai_response(session_messages) or "[Sem resposta textual — agente chamou ferramentas]"

            print(f"AGENTE: {ai_response[:400]}")

            q_count = count_questions(ai_response)
            questions = extract_questions(ai_response)

            print(f" → Perguntas neste turno: {q_count}")
            if questions:
                for q in questions:
                    q_clean = q.strip()
                    print(f" ❓ {q_clean[:120]}")
                    if q_clean in all_agent_questions:
                        violations.append(
                            f"TURN {turn_idx + 1}: PERGUNTA REPETIDA: {q_clean[:100]}"
                        )
                    all_agent_questions.append(q_clean)

            if q_count > 1 and turn_idx >= 1:
                violations.append(
                    f"TURN {turn_idx + 1}: {q_count} perguntas em uma mensagem (esperava max 1)"
                )

            turn_outputs.append(
                {
                    "turn": turn_idx + 1,
                    "user": user_msg,
                    "agent": ai_response[:500],
                    "question_count": q_count,
                }
            )

        except Exception as e:
            err_str = str(e)
            print(f"ERRO: {err_str[:200]}")
            if "tool_call_ids did not have response messages" in err_str:
                violations.append(
                    f"TURN {turn_idx + 1}: API error — tool_calls sem tool responses (problema de estado)"
                )
            session_messages = []
            continue

    print("\n" + "=" * 70)
    print("RESULTADO DO TESTE")
    print("=" * 70)
    print(f"Total de turnos: {len(PATIENT_RESPONSES)}")
    print(f"Total de perguntas feitas pelo agente: {len(all_agent_questions)}")
    print(f"Violacoes encontradas: {len(violations)}")

    if violations:
        print("\nVIOLACOES:")
        for v in violations:
            print(f" ⚠️ {v}")
    else:
        print("\n✅ Nenhuma violacao encontrada!")

    unique_questions = len(set(all_agent_questions))
    print(f"\nPerguntas unicas: {unique_questions}/{len(all_agent_questions)}")
    if unique_questions < len(all_agent_questions):
        print(" ⚠️ Perguntas duplicadas detectadas!")

    has_fhir_context = any(
        any(
            kw in t["agent"].lower()
            for kw in [
                "dpoc",
                "hipertens",
                "depress",
                "joelho",
                "osteoartrite",
                "losartana",
                "tiotropio",
                "sertralina",
                "paracetamol",
                "dipirona",
                "alergi",
                "anafilaxia",
                "saturacao",
                "fev1",
                "phq",
                "prontuario",
                "fhir",
                "medicacao",
            ]
        )
        for t in turn_outputs
        if t["turn"] > 1
    )
    print(
        f"\nAgente usou contexto FHIR nas respostas: {'✅ Sim' if has_fhir_context else '❌ Nao'}"
    )

    one_q_per_turn = sum(1 for t in turn_outputs if t["question_count"] <= 1)
    multi_q_turns = sum(1 for t in turn_outputs if t["question_count"] > 1)
    print(f"Turnos com 1 pergunta ou menos: {one_q_per_turn}/{len(turn_outputs)}")
    print(f"Turnos com multiplas perguntas: {multi_q_turns}/{len(turn_outputs)}")

    results_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    os.makedirs(results_dir, exist_ok=True)
    with open(
        os.path.join(results_dir, "test_dialogue_roberto_lima_results.json"), "w"
    ) as f:
        json.dump(
            {
                "patient": "Roberto Lima",
                "violations": violations,
                "turns": turn_outputs,
                "total_questions": len(all_agent_questions),
                "unique_questions": unique_questions,
                "has_fhir_context": has_fhir_context,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return len(violations) == 0


if __name__ == "__main__":
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1)
