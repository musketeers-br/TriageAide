# todo: auth
from fastmcp import FastMCP

# Criamos o segundo servidor MCP
mcp = FastMCP("TeamResourceManager")

# Banco de dados temporário em memória
team = [
    {"name": "José", "role": "Tech Lead", "skills": ["Python", "Docker", "IRIS"]},
    {"name": "Ana", "role": "Developer", "skills": ["React", "TypeScript", "UI"]},
]

allocations = [
    {"task_id": 1, "assignee": "José"},
    {"task_id": 2, "assignee": "Ana"},
]

notes = []

@mcp.tool()
async def list_team_members() -> str:
    """Lista todos os membros da equipe, seus cargos e habilidades."""
    if not team:
        return "Nenhum membro na equipe."
    
    output = "👥 Membros da Equipe:\n"
    for member in team:
        skills = ", ".join(member["skills"])
        output += f"- {member['name']} ({member['role']}) | Skills: {skills}\n"
    return output

@mcp.tool()
async def assign_task_to_member(task_id: int, member_name: str) -> str:
    """Aloca uma tarefa específica do projeto para um membro da equipe."""
    # Verifica se o membro existe na nossa base
    member_exists = any(m["name"].lower() == member_name.lower() for m in team)
    if not member_exists:
        return f"❌ Erro: Membro '{member_name}' não encontrado na equipe."
    
    # Atualiza ou adiciona alocação
    for alloc in allocations:
        if alloc["task_id"] == task_id:
            old_assignee = alloc["assignee"]
            alloc["assignee"] = member_name
            return f"🔄 Tarefa {task_id} reatribuída: de {old_assignee} para {member_name}."
            
    allocations.append({"task_id": task_id, "assignee": member_name})
    return f"📌 Tarefa {task_id} alocada com sucesso para {member_name}."

@mcp.tool()
async def add_project_note(title: str, content: str) -> str:
    """Adiciona uma nota importante, insight ou ata de reunião sobre o projeto."""
    note_id = len(notes) + 1
    notes.append({"id": note_id, "title": title, "content": content})
    return f"📝 Nota '{title}' salva com sucesso (ID {note_id})."

@mcp.tool()
async def get_project_dashboard() -> str:
    """Exibe um resumo rápido das alocações e notas do projeto."""
    output = "📊 Dashboard de Recursos e Notas:\n\n"
    
    output += "🔹 Alocações Atuais:\n"
    for a in allocations:
        output += f"  - Tarefa ID {a['task_id']} ➜ Responsável: {a['assignee']}\n"
        
    output += "\n🔹 Notas Recentes:\n"
    if not notes:
        output += "  - Nenhuma nota registrada ainda.\n"
    for n in notes:
        output += f"  - [{n['id']}] {n['title']}: {n['content']}\n"
        
    return output

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)