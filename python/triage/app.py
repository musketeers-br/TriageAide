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
        return (ai_response or "[Sem resposta textual do agente]") + suffix

    except Exception as e:
        elapsed = time.time() - t0
        return f"Erro ({elapsed:.1f}s): {str(e)}"


def main():
    demo = gr.ChatInterface(
        fn=chat_fn,
        title="TriageAide — Triagem Pre-Consulta FHIR-First",
        description="Agente de IA que consulta o prontuario FHIR do paciente, realiza triagem contextual inteligente e atualiza o registro clinico. Informe o ID do paciente para iniciar.",
        examples=[
            "Iniciar triagem para a paciente Maria Silva",
            "Triagem do paciente Joao Santos",
            "Historico da paciente Ana Costa",
            "Triagem do paciente Roberto Lima",
        ],
    )
    demo.launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":
    main()
