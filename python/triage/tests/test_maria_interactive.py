"""
Interactive test script — you play Maria Silva talking to the triage agent.
No automation — you type every answer yourself.

Maria Silva profile:
- 57-year-old female
- Type 2 diabetes, Essential hypertension (active)
- Metformin 850mg, Losartan 50mg (active)
- Abnormal labs: HbA1c 8.2% (H), Glucose 180 mg/dL (H), Microalbuminuria 45 mg/g (H)
- Allergy: Penicillin (high criticality — rash)
- Last visit: 2025-09-20

Example answers (use your own words):

  "I've been feeling tired and my blood sugar seems high."
  "Not really, it's been running high even with the medication."
  "Yes, very thirsty and urinating a lot this past week."
  "A little blurry in the mornings."
  "I think so, but sometimes I get headaches."
  "Some headaches and mild dizziness when I stand up fast."
  "No, no swelling."
  "A bit of stomach upset now and then."
  "Yes, I know — I avoid penicillin."
  "More tired than usual and my home sugar readings are higher."

Usage:
    docker compose exec triage bash -c \
        'cd /app && FHIR_BASE_URL=http://iris:52773/fhir/r4 python3 tests/test_maria_interactive.py'
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, AIMessage
from agent import create_triage_agent, extract_ai_response

PATIENT_NAME = "Maria Silva"


async def run_interactive():
    print()
    print("=" * 70)
    print(f"  Pre-Consultation Triage — {PATIENT_NAME}")
    print("=" * 70)
    print()
    print("  You are Maria Silva. Answer the agent's questions naturally.")
    print("  Type your answer and press Enter. Type 'exit' to quit.")
    print()
    print("  Example answers you could give:")
    print()
    print('    "I\'ve been feeling tired and my blood sugar seems high."')
    print('    "Not really, it\'s been running high even with the medication."')
    print('    "Yes, very thirsty and urinating a lot this past week."')
    print('    "A little blurry in the mornings."')
    print('    "I think so, but sometimes I get headaches."')
    print('    "Some headaches and mild dizziness when I stand up fast."')
    print('    "No, no swelling."')
    print('    "A bit of stomach upset now and then."')
    print('    "Yes, I know — I avoid penicillin."')
    print('    "More tired than usual and my home sugar readings are higher."')
    print()
    print("-" * 70)
    print()

    agent, client = await create_triage_agent()
    messages = []

    initial = f"I'm {PATIENT_NAME} and I'm here for my appointment."
    messages.append(HumanMessage(content=initial))
    print(f"  Maria: {initial}\n")

    while True:
        try:
            result = await agent.ainvoke({"messages": messages})
        except Exception as e:
            print(f"\n  Error: {e}\n")
            messages.pop()
            continue

        response_messages = result.get("messages", [])
        ai_response = extract_ai_response(response_messages)

        if ai_response:
            print(f"\n  Agent: {ai_response}\n")
        else:
            print("\n  Agent: [processing...]\n")

        messages = response_messages

        user_input = input("  Maria: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("\n  Session ended.")
            break

        messages.append(HumanMessage(content=user_input))


if __name__ == "__main__":
    asyncio.run(run_interactive())
