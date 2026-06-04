import os
import asyncio
import time
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage
import gradio as gr

from agent import create_triage_agent, extract_ai_response

load_dotenv(override=True)

_agent_instance = None
_client = None
_session_messages = []


async def _get_agent():
    global _agent_instance, _client
    if _agent_instance is not None:
        return _agent_instance

    agent, _client = await create_triage_agent()
    _agent_instance = agent
    return agent


async def chat_fn(message, history):
    global _session_messages
    agent = await _get_agent()

    if not history:
        _session_messages = []

    messages = list(_session_messages)
    messages.append(HumanMessage(content=message))

    t0 = time.time()
    try:
        result = await agent.ainvoke({"messages": messages})
        elapsed = time.time() - t0

        _session_messages = result.get("messages", [])

        ai_response = extract_ai_response(result.get("messages", []))
        suffix = f"\n\n---\n⏱ {elapsed:.1f}s"
        return (ai_response or "[No textual response from agent]") + suffix

    except BaseException as e:
        elapsed = time.time() - t0
        err = e.exceptions[0] if isinstance(e, BaseExceptionGroup) else e
        return f"Error ({elapsed:.1f}s): {type(err).__name__}: {str(err)}"


def main():
    demo = gr.ChatInterface(
        fn=chat_fn,
        title="TriageAide — FHIR-First Pre-Consultation Triage",
        description="AI agent that queries the patient's FHIR medical record, conducts intelligent contextual triage, and updates the clinical record. Enter the patient ID to start.",
        examples=[
            "Hi, I'm Maria Silva and I've been feeling really thirsty lately",
            "I'm Maria Silva, I've been having headaches and blurred vision",
            "Hi, I'm Joao Santos, I've been having chest pain",
            "I'm Joao Santos, I've been short of breath and my legs are swollen",
            "I'm Roberto Lima, my cough has been getting worse",
            "I'm Roberto Lima, I've been feeling sad and having trouble sleeping",
            "Hi, I'm Ana Costa, I've been having a fever and feeling tired",
            "I'm Ana Costa, I've had a cough for the past week",
            "Oi, sou a Maria Silva, ando com muita sede e visão embaçada",
            "Olá, sou o Roberto Lima, minha tosse está piorando",
        ],
    )
    demo.launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":
    main()
