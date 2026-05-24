
# todo: auth

from fastmcp import FastMCP
from datetime import datetime, timedelta

mcp = FastMCP("ProjectManager")

# Banco de dados temporário em memória
tasks = [
    {"id": 1, "task": "Configurar ambiente MCP", "status": "Concluído", "due": "2024-05-20"},
    {"id": 2, "task": "Desenvolver ferramentas coesas", "status": "Em progresso", "due": "2024-05-22"},
]

@mcp.tool()
async def list_tasks(status: str = None) -> str:
    """Lista todas as tarefas, podendo filtrar por status (Pendente, Em progresso, Concluído)."""
    filtered = [t for t in tasks if status is None or t["status"].lower() == status.lower()]
    if not filtered:
        return "Nenhuma tarefa encontrada."
    
    output = "📋 Lista de Tarefas:\n"
    for t in filtered:
        output += f"- [{t['id']}] {t['task']} | Status: {t['status']} | Prazo: {t['due']}\n"
    return output

@mcp.tool()
async def add_task(description: str, days_to_complete: int = 7) -> str:
    """Adiciona uma nova tarefa ao projeto com um prazo automático."""
    new_id = len(tasks) + 1
    due_date = (datetime.now() + timedelta(days=days_to_complete)).strftime("%Y-%m-%d")
    
    new_task = {
        "id": new_id,
        "task": description,
        "status": "Pendente",
        "due": due_date
    }
    tasks.append(new_task)
    return f"✅ Tarefa '{description}' criada com ID {new_id}. Prazo: {due_date}"

@mcp.tool()
async def update_task_status(task_id: int, new_status: str) -> str:
    """Atualiza o status de uma tarefa existente pelo seu ID."""
    for t in tasks:
        if t["id"] == task_id:
            old_status = t["status"]
            t["status"] = new_status
            return f"🔄 Tarefa {task_id} atualizada: de '{old_status}' para '{new_status}'."
    return f"❌ Erro: Tarefa com ID {task_id} não encontrada."

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
