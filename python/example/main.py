import os
from dotenv import load_dotenv

import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient  
from langchain.agents import create_agent

load_dotenv()

async def main():
    client = MultiServerMCPClient(
        {
            # "math": {
            #     "transport": "stdio",  # Local subprocess communication
            #     "command": "python",
            #     # Absolute path to your math_server.py file
            #     "args": ["./math_server.py"],
            # },
            # "weather": {
            #     "transport": "http",  # HTTP-based remote server
            #     # Ensure you start your weather server on port 8000
            #     "url": "http://localhost:8000/mcp",
            # },
            "project_manager": {
                "transport": "http",  # HTTP-based remote server
                # Ensure you start your weather server on port 8000
                "url": "http://localhost:8000/mcp",
            },
        }
    )

    tools = await client.get_tools()
    print(f"Tools: \n{tools}")
    agent = create_agent(
        # "google_genai:gemini-2.5-flash-lite",
        "openai:gpt-4o-mini",
        tools  
    )
    # math_response = await agent.ainvoke(
    #     {"messages": [{"role": "user", "content": "what's (3 + 5) x 12?"}]}
    # )
    # weather_response = await agent.ainvoke(
    #     {"messages": [{"role": "user", "content": "what is the weather in nyc?"}]}
    # )
    project_manager_response = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "Quais são as minhas tarefas e adicione 'Estudar MCP' na lista"}]}
    )
    # print(math_response)
    # print(weather_response)
    print(project_manager_response)

if __name__ == "__main__":
    asyncio.run(main())