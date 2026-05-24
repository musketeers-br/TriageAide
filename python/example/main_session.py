import os
from dotenv import load_dotenv

import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient  
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_agent
from langchain.messages import ToolMessage

load_dotenv()

async def main():
    client = MultiServerMCPClient(
        {
            "project_manager": {
                "transport": "http",  # HTTP-based remote server
                # Ensure you start your weather server on port 8000
                "url": "http://localhost:8000/mcp",
            },
        }
    )

    async with client.session("project_manager") as session:
        # tools = await client.get_tools()
        tools = await load_mcp_tools(session)
        print(f"Tools: \n{tools}")
        agent = create_agent(
            # "google_genai:gemini-2.5-flash-lite",
            "openai:gpt-4o-mini",
            tools  
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "Quais são as minhas tarefas e adicione 'Estudar MCP' na lista"}]}
        )

        # Extract structured content from tool messages
        print()
        print("Response:")
        for message in result["messages"]:
            if isinstance(message, ToolMessage) and message.artifact:
                structured_content = message.artifact["structured_content"]
                print(structured_content)

if __name__ == "__main__":
    asyncio.run(main())