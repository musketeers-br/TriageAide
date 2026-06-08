import asyncio

from agent import create_triage_agent


async def main():
    print("Creating triage agent...")
    agent, client = await create_triage_agent()

    drawable = agent.get_graph()

    drawable.draw_mermaid_png(output_file_path="graph.png")
    print("Saved graph.png")

    try:
        print("\n=== ASCII Graph ===\n")
        print(drawable.draw_ascii())
    except ImportError as e:
        print(f"ASCII graph unavailable: {e}")

    print("\n=== Mermaid Diagram ===\n")
    print(drawable.draw_mermaid())


asyncio.run(main())
