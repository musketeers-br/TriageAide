import asyncio

from langchain_core.messages import HumanMessage, AIMessage

from agent import create_triage_agent, extract_ai_response


async def run_interactive():
    agent, client = await create_triage_agent()

    messages = []

    print("\n" + "=" * 60)
    print("Pre-Consultation Triage Agent — FHIR-First Agentic AI")
    print("=" * 60)
    print("Enter the patient ID to start triage.")
    print("Test patient examples: use 'list' to see available ones")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Shutting down...")
            break

        messages.append(HumanMessage(content=user_input))

        try:
            result = await agent.ainvoke({"messages": messages})
            response_messages = result.get("messages", [])

            ai_response = extract_ai_response(response_messages)

        if ai_response:
            print(f"\nAgent: {ai_response}\n")
            messages.append(AIMessage(content=ai_response))
        else:
            print("\nAgent: [processed without textual response]\n")

            messages = response_messages

        except Exception as e:
            print(f"\nError: {e}\n")
            messages.pop()


def main():
    asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
