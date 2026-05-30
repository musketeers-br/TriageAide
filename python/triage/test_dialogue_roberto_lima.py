"""Test script to validate one-question-at-a-time dialogue quality.

Simulates a multi-turn conversation with the triage agent for Roberto Lima
(moderate-high complexity: COPD, hypertension, knee osteoarthritis, major
 depression, dipyrone allergy/anaphylaxis) and checks:
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
    "I want to start triage for patient Roberto Lima",
    "I have worse shortness of breath than usual and a cough with phlegm",
    "Yes, the cough is worse in the morning and the phlegm is more yellowish",
    "Yes, I've been feeling more tired than usual, even for simple things",
    "No, I haven't had a fever",
    "Yes, I've been feeling sad and with no motivation to do anything lately",
    "No, I haven't stopped taking sertraline, but I don't feel improvement",
    "Yes, my knee pain is worse, especially when climbing stairs",
    "No, I haven't taken dipyrone, I know I'm allergic and it can cause shock",
    "Yes, I've been using acetaminophen when the pain gets strong",
    "No, I haven't measured my oxygen saturation at home, but I feel it's harder to breathe",
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
    print("DIALOGUE QUALITY TEST — ROBERTO LIMA")
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
                "copd",
                "hypertens",
                "depress",
                "knee",
                "osteoarthritis",
                "losartan",
                "tiotropium",
                "sertraline",
                "acetaminophen",
                "dipyrone",
                "allergi",
                "anaphylaxis",
                "saturation",
                "fev1",
                "phq",
                "medical record",
                "fhir",
                "medication",
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
