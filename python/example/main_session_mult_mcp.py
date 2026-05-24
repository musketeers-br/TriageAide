import os
import asyncio
from dotenv import load_dotenv

from langchain_mcp_adapters.client import MultiServerMCPClient  
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_agent
from langchain.messages import ToolMessage

load_dotenv()

async def main():
    # Conectando nos dois servidores rodando em paralelo
    client = MultiServerMCPClient(
        {
            "project_manager": {
                "transport": "http",
                "url": "http://localhost:8000/mcp", # Servidor 1 (Tarefas)
            },
            "team_resource_manager": {
                "transport": "http",
                "url": "http://localhost:8001/mcp", # Servidor 2 (Recursos/Notas)
            },
        }
    )

    # Inicializa as sessões para ambos os servidores
    async with client.session("project_manager") as session_pm, client.session("team_resource_manager") as session_rm:
        
        # Carrega as ferramentas combinadas de ambos os servidores
        tools_pm = await load_mcp_tools(session_pm)
        tools_rm = await load_mcp_tools(session_rm)
        all_tools = tools_pm + tools_rm
        
        print(f"Total de ferramentas carregadas: {len(all_tools)}")
        
        agent = create_agent(
            "openai:gpt-4o-mini",
            all_tools  
        )
        
        # Exemplo de comando complexo que exige a colaboração dos dois servidores
        prompt = (
            "Quais são as minhas tarefas? Aproveite e crie uma nova tarefa chamada 'Ajustar Dockerfile'. "
            "Depois, verifique quem está na equipe e aloque essa nova tarefa (ID 3) para o José. "
            "Por fim, adicione uma nota de projeto dizendo que o José agora é o responsável pelo deploy."
        )
        
        print(f"\nUser: {prompt}")
        result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})

        print("\nResponse Logs / Tool Executions:")
        for message in result["messages"]:
            # Print de textos comuns vindos do agente ou das ferramentas
            if hasattr(message, "content") and message.content:
                print(f"[{type(message).__name__}]: {message.content}")
                
            # Extração de conteúdo estruturado se houver artefatos
            if isinstance(message, ToolMessage) and message.artifact:
                structured_content = message.artifact.get("structured_content")
                if structured_content:
                    print(f"[Artifact]: {structured_content}")

if __name__ == "__main__":
    asyncio.run(main())