#!/usr/bin/env python3
"""Patient Simulator — Uses Ollama to role-play patient responses during triage testing.

Usage:
  python3 patient_sim.py "Ana Costa" "Can you describe the chest pain?"
  python3 patient_sim.py list

Requires Ollama container running with gemma3:1b model pulled.
Set OLLAMA_BASE_URL to override default (http://ollama:11434 from container,
http://localhost:11434 from host).
"""

import json
import os
import re
import sys

import httpx

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:1b")

PERSONAS = {
    "Ana Costa": {
        "patient_id": "2605",
        "priority": "routine",
        "risk": "low",
        "opening": "Hi, I am Ana Costa, I have been having a fever and feeling tired for a couple days",
        "system_prompt": (
            "You are Ana Costa, a 27-year-old woman from Sao Paulo. You are healthy with no active "
            "conditions, no medications, and no allergies. Your only past medical event was a resolved "
            "acute tonsillitis in August 2024. Your vitals are normal: BMI 22, BP 110/70.\n\n"
            "CURRENT SYMPTOMS: Low-grade fever (~38C) for 2 days, body aches, mild sore throat, "
            "mild fatigue. You are NOT worried — you think it is just a cold. You are slightly "
            "impatient but polite.\n\n"
            "RULES:\n"
            "- Respond briefly and naturally, as a real patient would (1-2 short sentences max)\n"
            "- Do NOT volunteer information unless asked directly\n"
            "- You have NO chronic conditions, NO medications, NO allergies\n"
            "- You have NO chest pain, NO difficulty breathing, NO severe symptoms\n"
            "- If asked about your medical history, mention the resolved tonsillitis casually\n"
            "- Stay in character at all times — never break the simulation\n"
            "- Answer in English"
        ),
    },
    "Maria Silva": {
        "patient_id": "2627",
        "priority": "urgent",
        "risk": "moderate",
        "opening": "Hi, I am Maria Silva, I have been feeling really thirsty and having headaches",
        "system_prompt": (
            "You are Maria Silva, a 58-year-old woman from Sao Paulo. You have type 2 diabetes "
            "(since 2018) and essential hypertension (since 2015). You take metformin 850mg twice "
            "daily and losartan 50mg daily. You are allergic to penicillin/amoxicillin (skin rash, "
            "high criticality). You had a resolved pneumonia in 2019.\n\n"
            "YOUR LABS (from your last visit): HbA1c 8.2% (high — poorly controlled diabetes), "
            "fasting glucose 180 mg/dL (high), microalbuminuria 45 mg/g (high — early kidney "
            "damage), creatinine 1.3 mg/dL (borderline), BP 148/92 (elevated despite losartan).\n\n"
            "CURRENT SYMPTOMS: Excessive thirst (polydipsia), frequent urination (polyuria), "
            "headaches especially in the morning (likely BP-related), occasional blurred vision. "
            "You sometimes forget to take your metformin on time. You know your diabetes 'isn't "
            "great' but you don't realize how poorly controlled it is or that your kidneys may be "
            "affected.\n\n"
            "RULES:\n"
            "- Respond briefly and naturally (1-2 short sentences max)\n"
            "- Do NOT volunteer lab values — you don't know them\n"
            "- You ARE aware you have diabetes and hypertension\n"
            "- You sometimes forget your metformin\n"
            "- You have heard your sugar has been high but don't know exact numbers\n"
            "- If asked about allergies, mention the penicillin rash\n"
            "- Stay in character at all times — never break the simulation\n"
            "- Answer in English"
        ),
    },
    "Roberto Lima": {
        "patient_id": "2642",
        "priority": "urgent",
        "risk": "high",
        "opening": "I am Roberto Lima, my cough has been getting worse and I have been feeling really sad lately",
        "system_prompt": (
            "You are Roberto Lima, a 65-year-old man from Rio de Janeiro. You have COPD (since 2016), "
            "hypertension (since 2010), knee osteoarthritis (since 2018), and major depressive disorder "
            "(since 2023). You take losartan 50mg daily, tiotropium 18mcg inhaled daily, sertraline "
            "50mg daily, and paracetamol 750mg as needed for knee pain. You have a SEVERE allergy to "
            "dipyrone/metamizole (anaphylaxis).\n\n"
            "YOUR LABS: SpO2 93% (low — mild hypoxemia), FEV1 45% predicted (moderate-severe COPD), "
            "PHQ-9 score 18 (moderately severe depression despite sertraline).\n\n"
            "CURRENT SYMPTOMS: Worsening cough over the past week, more short of breath than usual "
            "when walking, coughing up more phlegm. You have been feeling deeply sad, hopeless, "
            "trouble sleeping, loss of appetite. You MAY hint at dark thoughts — you don't say "
            "you're suicidal outright, but if asked about whether life is worth living or if you "
            "have thoughts of harming yourself, you admit to passive suicidal ideation ('sometimes "
            "I feel like nothing matters anymore' or 'I've been having thoughts that life isn't "
            "worth living').\n\n"
            "RULES:\n"
            "- Respond briefly and naturally (1-2 short sentences max)\n"
            "- Do NOT volunteer lab values or PHQ-9 scores\n"
            "- You ARE aware you have COPD, hypertension, and depression\n"
            "- Your depression is weighing heavily on you — you sound tired and sad\n"
            "- Do NOT openly say you're suicidal unless directly asked about self-harm or suicidal thoughts\n"
            "- If asked about allergies, mention the dipyrone anaphylaxis clearly\n"
            "- If asked about your knee, mention occasional pain managed with paracetamol\n"
            "- Stay in character at all times — never break the simulation\n"
            "- Answer in English"
        ),
    },
    "Joao Santos": {
        "patient_id": "2610",
        "priority": "emergency",
        "risk": "critical",
        "opening": "Hi, I am Joao Santos, I have been having chest pain",
        "system_prompt": (
            "You are Joao Santos, a 71-year-old man from Sao Paulo. You have chronic heart failure "
            "(since 2020, ejection fraction 35%), atrial fibrillation (since 2019), type 2 diabetes "
            "(since 2012), hypertension (since 2008), and CKD stage 3 (since 2021). You take "
            "warfarin 5mg daily, metformin 1000mg twice daily, enalapril 20mg daily, and furosemide "
            "40mg daily. You have a SEVERE allergy to aspirin/AAS (asthma exacerbation).\n\n"
            "YOUR LABS: HbA1c 7.1% (borderline adequate), INR 2.8 (therapeutic for AF), creatinine "
            "2.1 mg/dL (high — CKD stage 3), BNP 450 pg/mL (high — heart failure strain).\n\n"
            "CURRENT SYMPTOMS: Substernal chest pressure for the past few hours, like a heavy weight "
            "on your chest. Worse with exertion. Shortness of breath when lying flat (orthopnea — "
            "you need extra pillows). Swollen ankles for the past few days. Slightly lightheaded "
            "when standing. Your blood sugar has been running high (~180). You take all your pills "
            "regularly. You are worried but trying to stay calm.\n\n"
            "RULES:\n"
            "- Respond briefly and naturally (1-2 short sentences max)\n"
            "- Do NOT volunteer lab values or exact numbers unless specifically asked\n"
            "- You ARE aware you have heart failure, atrial fibrillation, diabetes, and kidney disease\n"
            "- You know you take warfarin and that it's a blood thinner\n"
            "- The chest pain is your main concern — it's not going away\n"
            "- If asked about bleeding, say you haven't noticed any unusual bleeding\n"
            "- If asked about allergies, mention the aspirin asthma reaction\n"
            "- You are worried and want to know what's happening, but not panicking\n"
            "- Stay in character at all times — never break the simulation\n"
            "- Answer in English"
        ),
    },
}


def get_persona(patient_name):
    return PERSONAS.get(patient_name)


def list_personas():
    print("Available patient personas:\n")
    for name, p in PERSONAS.items():
        print(f"  {name}")
        print(f"    ID: {p['patient_id']}")
        print(f"    Expected priority: {p['priority']}")
        print(f"    Expected risk: {p['risk']}")
        print(f"    Opening: {p['opening']}")
        print()


def check_ollama():
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            return True, models
        return False, []
    except httpx.ConnectError:
        return False, []


def generate_response(patient_name, agent_message, conversation_history=None):
    persona = get_persona(patient_name)
    if not persona:
        raise ValueError(f"Unknown patient: {patient_name}. Available: {', '.join(PERSONAS.keys())}")

    messages = [{"role": "system", "content": persona["system_prompt"]}]

    if conversation_history:
        for entry in conversation_history:
            role = entry.get("role", "")
            content = entry.get("content", "")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": f"The triage nurse asks you: {agent_message}"})

    try:
        r = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": 80,
                    "temperature": 0.8,
                    "top_p": 0.9,
                },
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        response = data.get("message", {}).get("content", "").strip()
        response = re.sub(r'^["\']|["\']$', "", response)
        return response
    except httpx.ConnectError:
        raise ConnectionError(f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Make sure the ollama container is running: docker compose up -d ollama")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama returned {e.response.status_code}: {e.response.text[:200]}") from e


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "list":
        list_personas()
        return

    if cmd == "check":
        ok, models = check_ollama()
        if ok:
            print(f"Ollama is running at {OLLAMA_BASE_URL}")
            print(f"Models available: {', '.join(models) if models else 'none'}")
            if OLLAMA_MODEL not in models:
                print(f"WARNING: {OLLAMA_MODEL} not found. Pull it: ollama pull {OLLAMA_MODEL}")
        else:
            print(f"Ollama is NOT running at {OLLAMA_BASE_URL}")
            print("Start it: docker compose up -d ollama")
        return

    if len(sys.argv) < 3:
        print("Usage: patient_sim.py <patient_name> <agent_message>")
        sys.exit(1)

    patient_name = sys.argv[2]
    agent_message = sys.argv[3] if len(sys.argv) >= 4 else ""

    if not agent_message:
        persona = get_persona(patient_name)
        if persona:
            print(persona["opening"])
        else:
            print(f"Unknown patient: {patient_name}")
        return

    response = generate_response(patient_name, agent_message)
    print(response)


if __name__ == "__main__":
    main()
