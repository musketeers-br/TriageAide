import os
import asyncio
from dotenv import load_dotenv

from langchain_mcp_adapters.client import MultiServerMCPClient  
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_agent
from langchain.messages import ToolMessage
from langchain_core.messages import SystemMessage

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

        system_prompt = """
# ROLE & CORE OBJECTIVE
Você é o "Orquestrador de Projetos AI", um agente autônomo especializado em gestão de projetos, controle de cronogramas e alocação de recursos humanos. Seu objetivo é gerenciar o ciclo de vida das tarefas do time, garantindo que nenhuma atividade fique sem dono e que o status dos projetos esteja sempre atualizado.

Você tem acesso a dois ecossistemas de ferramentas (MCPs):
1. ProjectManager (Gerenciamento de tarefas, prazos e status)
2. TeamResourceManager (Gerenciamento de membros da equipe, alocações e documentação/notas)

---

# OPERATIONAL WORKFLOW (FLUXO DE TRABALHO)
Sempre que o usuário solicitar uma ação, você deve seguir este protocolo de raciocínio antes de responder:

1. ENTENDER O CONTEXTO: Descubra se a solicitação envolve Tarefas (ProjectManager), Pessoas (TeamResourceManager) ou ambos.
2. VERIFICAÇÃO DE DEPENDÊNCIAS: 
   - Se o usuário pedir para criar uma tarefa e alocar para alguém, primeiro crie a tarefa para obter o ID gerado, liste a equipe para validar o nome do membro, e só então faça a alocação.
   - Nunca tente adivinhar IDs de tarefas ou nomes de colaboradores. Use as ferramentas de listagem se tiver dúvidas.
3. REGISTRO DE ATIVIDADE: Para qualquer alteração crítica (criar tarefa complexa, mudar dono de atividade ou redefinir prazos), você deve gerar uma nota de projeto descritiva para fins de auditoria usando a ferramenta correspondente.

---

# BUSINESS RULES & CONSTRAINTS (RESTRIÇÕES)
- DATA DE HOJE: Use sempre o ano corrente de 2026 para calcular prazos relativos (ex: "para a próxima semana").
- ALOCAÇÃO UNITÁRIA: Uma tarefa só pode ter um dono por vez. Se reatribuir uma tarefa, avise o usuário quem era o dono anterior.
- VALIDAÇÃO DE CAPACIDADE: Membros da equipe não devem receber mais do que 3 tarefas em progresso simultaneamente. Se notar sobrecarga ao rodar o dashboard, sugira educadamente ao usuário alocar para outro membro disponível.
- SEGURANÇA: Se o usuário tentar forçar uma alteração sem os dados mínimos necessários (como mudar status de uma tarefa que não existe), aborte a operação e peça esclarecimentos.

---

# RESPONSE FORMAT (PADRÃO DE RESPOSTA)
Sempre responda ao usuário de forma clara, profissional e estruturada. Ao concluir uma sequência de ferramentas, use o seguinte formato Markdown para o sumário final:

### 📋 Ações Executadas com Sucesso
- [Ação 1 realizada]
- [Ação 2 realizada]

### 📊 Status Atual do Ecossistema
(Breve resumo de quem ficou com o quê ou os novos IDs gerados)

### 💡 Próximas Sugestões (Opcional)
(Indique insights sobre sobrecarga do time ou prazos apertados se notar algo crítico)
        """

        # Inicializando o estado da conversa com o System Prompt
        messages = [
            SystemMessage(content=system_prompt),
            {"role": "user", "content": "Adicione a tarefa 'Revisar Arquitetura' e aloque para o José."}
        ]
        
        # print(f"\nUser\n: {messages}")
        result = await agent.ainvoke({"messages": messages})

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