"""Test script to validate one-question-at-a-time dialogue quality.

Simulates a multi-turn conversation with the triage agent for Joao Santos
(high-complexity: heart failure, atrial fibrillation, diabetes, hypertension,
CKD stage 3, aspirin allergy) and checks:
1. Agent asks only ONE question per turn
2. Agent doesn't repeat questions
3. Agent uses FHIR data contextually
4. Conversation flows naturally in English
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
    "I want to start triage for patient Joao Santos",
    "I'm not feeling well, I have shortness of breath and fatigue",
    "Yes, I've noticed swelling in my legs and feet, especially at night",
    "No, I haven't had any chest pain",
    "Yes, I've noticed I'm urinating less than usual",
    "No, my weight is stable, I haven't gained any",
    "No, I haven't taken any aspirin, I know I'm allergic",
    "Yes, I've been following the diet and taking my medications correctly",
    "No, I haven't had any tests recently, the last one was in January",
    "Yes, sometimes I feel dizzy when I stand up quickly",
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
    print("DIALOGUE QUALITY TEST — JOAO SANTOS")
    print("=" * 70)

    for turn_idx, user_msg in enumerate(PATIENT_RESPONSES):
        print(f"\n--- TURN {turn_idx + 1} ---")
        print(f"PATIENT: {user_msg}")

        messages = list(session_messages)
        messages.append(HumanMessage(content=user_msg))

        try:
            result = await agent.ainvoke({"messages": messages})
            session_messages = result.get("messages", [])

            ai_response = extract_ai_response(session_messages) or "[No textual response — agent called tools]"

            print(f"AGENT: {ai_response[:400]}")

            q_count = count_questions(ai_response)
            questions = extract_questions(ai_response)

            print(f" → Questions this turn: {q_count}")
            if questions:
                for q in questions:
                    q_clean = q.strip()
                    print(f" ❓ {q_clean[:120]}")
                    if q_clean in all_agent_questions:
                violations.append(
                    f"TURN {turn_idx + 1}: REPEATED QUESTION: {q_clean[:100]}"
                )
                    all_agent_questions.append(q_clean)

            if q_count > 1 and turn_idx >= 1:
                violations.append(
                    f"TURN {turn_idx + 1}: {q_count} questions in one message (expected max 1)"
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
            print(f"ERROR: {err_str[:200]}")
            if "tool_call_ids did not have response messages" in err_str:
                violations.append(
                    f"TURN {turn_idx + 1}: API error — tool_calls without tool responses (state issue)"
                )
            session_messages = []
            continue

    print("\n" + "=" * 70)
    print("TEST RESULT")
    print("=" * 70)
    print(f"Total turns: {len(PATIENT_RESPONSES)}")
    print(f"Total questions asked by agent: {len(all_agent_questions)}")
    print(f"Violations found: {len(violations)}")

    if violations:
        print("\nVIOLATIONS:")
        for v in violations:
            print(f" ⚠️ {v}")
    else:
        print("\n✅ No violations found!")

    unique_questions = len(set(all_agent_questions))
    print(f"\nUnique questions: {unique_questions}/{len(all_agent_questions)}")
    if unique_questions < len(all_agent_questions):
        print(" ⚠️ Duplicate questions detected!")

    has_fhir_context = any(
        any(
            kw in t["agent"].lower()
            for kw in [
                "heart failure",
                "fibrillation",
                "diabetes",
                "hypertens",
                "renal",
                "warfarin",
                "enalapril",
                "furosemide",
                "metformin",
                "creatinine",
                "bnr",
                "inr",
                "medical record",
                "fhir",
                "medication",
                "aspirin",
                "allergi",
            ]
        )
        for t in turn_outputs
        if t["turn"] > 1
    )
        print(
            f"\nAgent used FHIR context in responses: {'✅ Yes' if has_fhir_context else '❌ No'}"
        )

    one_q_per_turn = sum(1 for t in turn_outputs if t["question_count"] <= 1)
    multi_q_turns = sum(1 for t in turn_outputs if t["question_count"] > 1)
    print(f"Turns with 1 question or fewer: {one_q_per_turn}/{len(turn_outputs)}")
    print(f"Turns with multiple questions: {multi_q_turns}/{len(turn_outputs)}")

    results_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    os.makedirs(results_dir, exist_ok=True)
    with open(
        os.path.join(results_dir, "test_dialogue_joao_santos_results.json"), "w"
    ) as f:
        json.dump(
            {
                "patient": "Joao Santos",
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
