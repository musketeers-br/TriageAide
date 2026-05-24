import asyncio

from langchain_core.messages import HumanMessage, AIMessage

from agent import create_triage_agent, extract_ai_response


async def run_interactive():
    agent, client = await create_triage_agent()

    messages = []

    print("\n" + "=" * 60)
    print("Agente de Triagem Pre-Consulta — FHIR-First Agentic AI")
    print("=" * 60)
    print("Digite o ID do paciente para iniciar a triagem.")
    print("Exemplos de pacientes de teste: use 'list' para ver os disponiveis")
    print("Digite 'sair' para encerrar.\n")

    while True:
        user_input = input("Voce: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "sair":
            print("Encerrando...")
            break

        messages.append(HumanMessage(content=user_input))

        try:
            result = await agent.ainvoke({"messages": messages})
            response_messages = result.get("messages", [])

            ai_response = extract_ai_response(response_messages)

            if ai_response:
                print(f"\nAgente: {ai_response}\n")
                messages.append(AIMessage(content=ai_response))
            else:
                print("\nAgente: [processou sem resposta textual]\n")

            messages = response_messages

        except Exception as e:
            print(f"\nErro: {e}\n")
            messages.pop()


def main():
    asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
