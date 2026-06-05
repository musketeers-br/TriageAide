"""E2E test: agent auto-detects and mirrors the user's language.

Sends prompts in multiple languages (Portuguese, Spanish, English) and
verifies the agent responds in the matching language — not always English.
"""
import os
import re
import sys
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from agent import create_triage_agent, extract_ai_response

load_dotenv()

_PORTUGUESE_WORDS = re.compile(
    r"\b(voc|est|como|sintoma|consulta|triagem|medicamento|press|diabete|sa|senhora|senhor|bom|dia|ol)\b",
    re.IGNORECASE,
)
_SPANISH_WORDS = re.compile(
    r"\b(usted|est|como|s|ntoma|consulta|triaje|medicamento|presi|diabete|buena|d|se|ora|hola)\b",
    re.IGNORECASE,
)
_ENGLISH_WORDS = re.compile(
    r"\b(you|are|how|symptom|consult|triage|medication|pressur|diabet|good|hello|morning|ms|mrs)\b",
    re.IGNORECASE,
)


def _detect_language(text):
    pt_score = len(_PORTUGUESE_WORDS.findall(text))
    es_score = len(_SPANISH_WORDS.findall(text))
    en_score = len(_ENGLISH_WORDS.findall(text))

    if pt_score > en_score and pt_score >= es_score:
        return "pt"
    if es_score > en_score and es_score > pt_score:
        return "es"
    if en_score >= pt_score and en_score >= es_score:
        return "en"
    return "unknown"


LANG_PROBES = [
    {
        "language": "pt",
        "label": "Portuguese",
        "messages": [
            "Ol, eu sou a Maria Silva e estou aqui para minha consulta",
        ],
    },
    {
        "language": "es",
        "label": "Spanish",
        "messages": [
            "Hola, soy Roberto Lima y estoy aqu para mi consulta",
        ],
    },
    {
        "language": "en",
        "label": "English",
        "messages": [
            "Hello, I'm Maria Silva and I'm here for my appointment",
        ],
    },
]


async def _probe_language(agent, user_message, session_messages=None):
    messages = list(session_messages or [])
    messages.append(HumanMessage(content=user_message))
    result = await agent.ainvoke({"messages": messages})
    updated = result.get("messages", [])
    ai_response = extract_ai_response(updated) or ""
    return ai_response, updated


async def run_test():
    print("\n" + "=" * 70)
    print("E2E TEST — LANGUAGE AUTO-DETECTION")
    print("=" * 70)

    agent, client = await create_triage_agent()

    results = []
    failures = []

    for probe in LANG_PROBES:
        expected = probe["language"]
        label = probe["label"]
        print(f"\n--- Probe: {label} (expected={expected}) ---")

        for msg in probe["messages"]:
            print(f"  PATIENT: {msg}")
            response, _ = await _probe_language(agent, msg)
            print(f"  AGENT: {response[:300]}")

            detected = _detect_language(response)
            match = detected == expected
            print(f"  Detected language: {detected} — {'PASS' if match else 'FAIL'}")

            results.append(
                {
                    "probe": label,
                    "expected": expected,
                    "detected": detected,
                    "match": match,
                    "user_message": msg,
                    "agent_response": response[:500],
                }
            )

            if not match:
                failures.append(
                    f"{label}: expected={expected}, detected={detected}"
                )

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    passed = sum(1 for r in results if r["match"])
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  ✗ {f}")
    else:
        print("\n✅ All language probes passed!")

    results_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test_results"
    )
    os.makedirs(results_dir, exist_ok=True)
    with open(
        os.path.join(results_dir, "test_language_autodetect_results.json"), "w"
    ) as f:
        json.dump(
            {"passed": passed, "total": total, "failures": failures, "probes": results},
            f,
            ensure_ascii=False,
            indent=2,
        )

    return len(failures) == 0


if __name__ == "__main__":
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1)
