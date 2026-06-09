import os
import asyncio
import time
import json
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.callbacks import AsyncCallbackHandler
import gradio as gr
from gradio import ChatMessage

from agent import create_triage_agent, extract_ai_response
from logging_config import setup_logging

load_dotenv(override=True)

_show_voice_ui = os.getenv("ENABLE_VOICE_UI", "false").lower() in ("1", "true", "yes")

logger = setup_logging("app", "app.log")

_agent_instance = None
_client = None
_session_messages = []

_STEP_MAP = {
    "search_patients": 1,
    "get_patient": 1,
    "get_patient_conditions": 1,
    "get_patient_medications": 1,
    "get_patient_observations": 1,
    "get_patient_allergies": 1,
    "get_patient_encounters": 1,
    "reset_triage_session": 2,
    "get_next_triage_question": 2,
    "parse_symptoms": 2,
    "analyze_patient_response": 2,
    "build_questionnaire_response_data": 2,
    "check_red_flags": 3,
    "assess_clinical_risk": 4,
    "suggest_priority": 4,
    "create_flag_and_task": 4,
    "create_questionnaire_response": 5,
    "create_encounter": 5,
    "create_observation": 5,
    "create_condition": 5,
    "generate_clinical_summary": 5,
    "identify_follow_up_tasks": 5,
}

_STEP_LABELS = {
    1: "📋 STEP 1 — FHIR Query",
    2: "💬 STEP 2 — Triage Questions",
    3: "🚩 STEP 3 — Red Flags Check",
    4: "⚕️ STEP 4 — Clinical Reasoning",
    5: "📝 STEP 5 — FHIR Update",
}

_TOOL_ICONS = {
    1: "🗂️",
    2: "💬",
    3: "🚩",
    4: "⚕️",
    5: "📝",
}


def _summarize_tool_result(tool_name, output_str):
    try:
        data = json.loads(output_str)
    except (json.JSONDecodeError, TypeError):
        text = output_str.strip()
        return text[:77] + "..." if len(text) > 80 else text or "Done"

    if tool_name == "search_patients":
        return f"{data.get('total', 0)} patient(s) found"
    if tool_name == "get_patient":
        return f"{data.get('name', '?')}, DOB {data.get('birthDate', '?')}"
    if tool_name.startswith("get_patient_"):
        total = data.get("total", 0)
        resource = tool_name.replace("get_patient_", "")
        return f"{total} {resource} retrieved"
    if tool_name == "parse_symptoms":
        n = len(data.get("identified_symptoms", []))
        return f"{n} symptom(s), {data.get('estimated_severity', '?')}"
    if tool_name == "check_red_flags":
        n = data.get("alert_count", 0)
        crit = data.get("has_critical_red_flag", False)
        return f"{n} alert(s)" + (" ⚠️ CRITICAL" if crit else "")
    if tool_name == "assess_clinical_risk":
        return f"{data.get('risk_level', '?').upper()} (score {data.get('risk_score', 0)})"
    if tool_name == "suggest_priority":
        return data.get("priority_label", "?")
    if tool_name == "generate_clinical_summary":
        return f"risk={data.get('risk_level', '?')}, priority={data.get('priority', '?')}"
    if tool_name == "identify_follow_up_tasks":
        return f"{data.get('total', 0)} task(s)"
    if tool_name.startswith("create_"):
        rid = data.get("resource", data.get("id", "?"))
        return f"Created {rid}" if isinstance(rid, str) else "Created"
    if tool_name == "reset_triage_session":
        return "Session reset"
    if tool_name == "get_next_triage_question":
        q = data.get("question")
        if q is None:
            return "No more questions"
        return f"1 question ({data.get('total_remaining', 0)} remaining)"
    if tool_name == "build_questionnaire_response_data":
        return f"{data.get('total', 0)} items structured"
    return "Done"


def _summarize_tool_input(tool_name, tool_input):
    if isinstance(tool_input, dict):
        if "patient_id" in tool_input:
            return f"patient_id={tool_input['patient_id']}"
        if "name" in tool_input:
            return f"name=\"{tool_input['name']}\""
        items = list(tool_input.items())[:3]
        return ", ".join(f"{k}={v}" for k, v in items)
    return str(tool_input)[:60]


def _format_args(tool_input):
    if isinstance(tool_input, dict):
        try:
            return json.dumps(tool_input, indent=2, default=str, ensure_ascii=False)[:800]
        except (TypeError, ValueError):
            pass
    return str(tool_input)[:800]


def _find_by_id(target_list, partial_id):
    for i in range(len(target_list) - 1, -1, -1):
        entry = target_list[i]
        if entry.metadata and entry.metadata.get("id", "").startswith(partial_id):
            return i
    return -1


def _find_by_tool(target_list, tool_name):
    for i in range(len(target_list) - 1, -1, -1):
        entry = target_list[i]
        if entry.metadata and tool_name in (entry.metadata.get("title") or ""):
            return i
    return -1


class TriageTraceHandler(AsyncCallbackHandler):
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self._llm_num = 0
        self._tool_times = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._llm_num += 1
        await self.queue.put({
            "type": "llm_start",
            "llm_num": self._llm_num,
            "run_id": str(run_id),
        })

    async def on_chat_model_end(self, response, *, run_id, **kwargs):
        content_preview = ""
        tc_names = []
        try:
            for gen_list in response.generations:
                for gen in gen_list:
                    msg = gen.message
                    if msg.content:
                        content_preview = (msg.content or "")[:300]
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tc_names.append(tc.get("name", "?"))
        except Exception:
            content_preview = str(response)[:300]
        await self.queue.put({
            "type": "llm_end",
            "run_id": str(run_id),
            "llm_num": self._llm_num,
            "content_preview": content_preview,
            "tool_call_names": tc_names,
        })

    async def on_tool_start(self, serialized, input_str, *, run_id, name, inputs=None, **kwargs):
        tool_input = inputs if isinstance(inputs, dict) else {}
        tool_name = name or (serialized.get("name") if isinstance(serialized, dict) else None) or "unknown"
        self._tool_times[str(run_id)] = time.time()
        logger.info("Tool start: %s | args=%s", tool_name, _summarize_tool_input(tool_name, tool_input))
        await self.queue.put({
            "type": "tool_start",
            "tool_name": tool_name,
            "run_id": str(run_id),
            "tool_input": tool_input,
        })

    async def on_tool_end(self, output, *, run_id, name, **kwargs):
        elapsed = None
        rid = str(run_id)
        if rid in self._tool_times:
            elapsed = round(time.time() - self._tool_times.pop(rid), 1)
        if isinstance(output, ToolMessage):
            content = output.content
            if isinstance(content, list):
                output_str = " ".join(
                    item.get("text", str(item)) if isinstance(item, dict) else str(item)
                    for item in content
                )
            else:
                output_str = str(content)
        else:
            output_str = str(output)
        logger.info("Tool end: %s | elapsed=%ss | result_summary=%s", name, elapsed, _summarize_tool_result(name, output_str))
        logger.debug("Tool end: %s | full_result: %.500s", name, output_str[:500])
        await self.queue.put({
            "type": "tool_end",
            "tool_name": name,
            "run_id": rid,
            "output": output_str,
            "elapsed": elapsed,
        })

    async def on_tool_error(self, error, *, run_id, **kwargs):
        tool_name = kwargs.get("name", "unknown")
        logger.error("Tool error: %s | %s: %s", tool_name, type(error).__name__, str(error)[:500])
        await self.queue.put({
            "type": "tool_error",
            "tool_name": tool_name,
            "run_id": str(run_id),
            "error": f"{type(error).__name__}: {str(error)[:500]}",
        })


async def _get_agent():
    global _agent_instance, _client
    if _agent_instance is not None:
        return _agent_instance
    logger.info("Initializing triage agent for Gradio UI...")
    max_retries = 6
    for attempt in range(1, max_retries + 1):
        try:
            agent, _client = await create_triage_agent(cache_namespace="gradio")
            _agent_instance = agent
            logger.info("Agent ready for Gradio UI")
            return agent
        except Exception as e:
            logger.warning("Agent init attempt %d/%d failed: %s", attempt, max_retries, str(e)[:300])
            if attempt == max_retries:
                logger.error("Agent init failed after %d attempts", max_retries)
                raise
            await asyncio.sleep(5)


class _TraceState:
    __slots__ = ("current_step", "llm_call_num", "open_llm_num", "open_llm_tools")

    def __init__(self):
        self.current_step = 0
        self.llm_call_num = 0
        self.open_llm_num = None
        self.open_llm_tools = []


def _close_pending_llm(target, st):
    if st.open_llm_num is None:
        return
    num = st.open_llm_num
    tools = st.open_llm_tools
    idx = _find_by_id(target, f"llm-{num}")
    if idx < 0:
        st.open_llm_num = None
        st.open_llm_tools = []
        return
    old = target[idx]
    if tools:
        summary = "→ " + ", ".join(tools)
        detail = f"**Decided to call:** {', '.join(tools)}"
    else:
        summary = "Generating response"
        detail = old.content or "Completed"
    meta = dict(old.metadata) if old.metadata else {}
    meta.update({
        "title": f"🧠 LLM #{num} · {summary}",
        "status": "done",
    })
    target[idx] = ChatMessage(
        role="assistant",
        content=detail,
        metadata=meta,
    )
    st.open_llm_num = None
    st.open_llm_tools = []


def _apply_trace_event(event, chat_history, trace_history, compact, st):
    etype = event["type"]
    target = chat_history if compact else trace_history

    if etype == "llm_start":
        _close_pending_llm(target, st)
        st.llm_call_num += 1
        num = st.llm_call_num
        st.open_llm_num = num
        st.open_llm_tools = []
        entry = ChatMessage(
            role="assistant",
            content="Analyzing context and deciding next action...",
            metadata={
                "title": f"🧠 LLM Reasoning #{num}",
                "status": "pending",
                "id": f"llm-{num}",
            },
        )
        target.append(entry)
        return

    if etype == "llm_end":
        num = event.get("llm_num", st.llm_call_num)
        tc_names = event.get("tool_call_names", [])
        content_preview = event.get("content_preview", "")

        idx = _find_by_id(target, f"llm-{num}")
        if idx >= 0:
            detail_parts = []
            if content_preview:
                detail_parts.append(f"**Thinking:**\n{content_preview}")
            if tc_names:
                detail_parts.append(f"**Decided to call:** {', '.join(tc_names)}")
            detail = "\n\n".join(detail_parts) if detail_parts else "Completed"
            summary = "→ " + ", ".join(tc_names) if tc_names else "Generating response"

            meta = dict(target[idx].metadata) if target[idx].metadata else {}
            meta.update({
                "title": f"🧠 LLM #{num} · {summary}",
                "status": "done",
            })
            target[idx] = ChatMessage(
                role="assistant",
                content=detail,
                metadata=meta,
            )
            st.open_llm_num = None
            st.open_llm_tools = []
        return

    if etype == "tool_start":
        tool_name = event["tool_name"]
        tool_input = event.get("tool_input", {})
        run_id = event.get("run_id", "")

        if st.open_llm_num is not None:
            st.open_llm_tools.append(tool_name)

        step_num = _STEP_MAP.get(tool_name, 0)

        if step_num and step_num != st.current_step:
            st.current_step = step_num
            step_entry = ChatMessage(
                role="assistant",
                content="",
                metadata={
                    "title": _STEP_LABELS.get(step_num, f"Step {step_num}"),
                    "status": "done",
                    "id": f"step-{step_num}",
                },
            )
            target.append(step_entry)

        icon = _TOOL_ICONS.get(step_num, "🔧") if step_num else "🔧"
        args_str = _format_args(tool_input)
        input_summary = _summarize_tool_input(tool_name, tool_input)

        entry = ChatMessage(
            role="assistant",
            content=f"**Arguments:**\n```json\n{args_str}\n```",
            metadata={
                "title": f"{icon} → {tool_name}",
                "status": "pending",
                "id": f"tool-{run_id}",
                "parent_id": f"step-{step_num}" if step_num else "",
                "log": input_summary,
            },
        )
        target.append(entry)
        return

    if etype == "tool_end":
        tool_name = event["tool_name"]
        run_id = event.get("run_id", "")
        output_str = event.get("output", "")
        elapsed = event.get("elapsed")
        summary = _summarize_tool_result(tool_name, output_str)
        step_num = _STEP_MAP.get(tool_name, 0)
        icon = _TOOL_ICONS.get(step_num, "✅") if step_num else "✅"

        result_preview = output_str[:1500]

        idx = _find_by_id(target, f"tool-{run_id}")
        if idx >= 0:
            old = target[idx]
            meta = dict(old.metadata) if old.metadata else {}
            meta["title"] = f"{icon} {tool_name} · {summary}"
            meta["status"] = "done"
            if elapsed is not None:
                meta["duration"] = elapsed
            target[idx] = ChatMessage(
                role="assistant",
                content=f"{old.content or ''}\n\n**Result:**\n```json\n{result_preview}\n```",
                metadata=meta,
            )
        else:
            target.append(ChatMessage(
                role="assistant",
                content=f"**Result:**\n```json\n{result_preview}\n```",
                metadata={
                    "title": f"{icon} {tool_name} · {summary}",
                    "status": "done",
                    "parent_id": f"step-{step_num}" if step_num else "",
                    "duration": elapsed,
                },
            ))
        return

    if etype == "tool_error":
        tool_name = event["tool_name"]
        err_str = event.get("error", "Unknown error")

        idx = _find_by_tool(target, tool_name)
        if idx >= 0:
            old = target[idx]
            meta = dict(old.metadata) if old.metadata else {}
            meta["title"] = f"💥 {tool_name} · Error"
            meta["status"] = "done"
            target[idx] = ChatMessage(
                role="assistant",
                content=f"{old.content or ''}\n\n**Error:**\n```\n{err_str}\n```",
                metadata=meta,
            )
        else:
            target.append(ChatMessage(
                role="assistant",
                content=f"```\n{err_str}\n```",
                metadata={"title": f"💥 {tool_name} · Error", "status": "done"},
            ))
        return


async def _run_with_trace(message, chat_history, trace_history, view_mode):
    global _session_messages
    agent = await _get_agent()
    logger.info("Chat submission | message=%.100s | mode=%s", message[:100], view_mode)

    if not chat_history:
        _session_messages = []

    chat_history = list(chat_history) if chat_history else []
    trace_history = list(trace_history) if trace_history else []
    compact = view_mode == "Compact"

    chat_history.append(ChatMessage(role="user", content=message))

    trace_history.append(ChatMessage(
        role="assistant",
        content=f'User: "{message[:100]}"',
        metadata={"title": "📥 Input Received", "status": "done"},
    ))
    if compact:
        yield chat_history
    else:
        yield chat_history, trace_history

    messages = list(_session_messages)
    messages.append(HumanMessage(content=message))

    t0_total = time.time()
    st = _TraceState()

    queue = asyncio.Queue()
    handler = TriageTraceHandler(queue)

    invoke_task = asyncio.create_task(
        agent.ainvoke(
            {"messages": messages},
            config={"callbacks": [handler]},
        )
    )

    try:
        while not invoke_task.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.3)
            except asyncio.TimeoutError:
                if invoke_task.done():
                    break
                continue

            _apply_trace_event(event, chat_history, trace_history, compact, st)

            if compact:
                yield chat_history
            else:
                yield chat_history, trace_history

        result = await invoke_task
        _session_messages = result.get("messages", [])

        target = chat_history if compact else trace_history
        _close_pending_llm(target, st)

        if compact:
            yield chat_history
        else:
            yield chat_history, trace_history

    except BaseException as e:
        elapsed = time.time() - t0_total
        err = e.exceptions[0] if isinstance(e, BaseExceptionGroup) else e
        err_msg = f"Error ({elapsed:.1f}s): {type(err).__name__}: {str(err)}"
        logger.error("Agent invocation failed: %s", err_msg)
        chat_history.append(ChatMessage(role="assistant", content=err_msg))
        if not compact:
            trace_history.append(ChatMessage(
                role="assistant",
                content=err_msg,
                metadata={"title": "💥 Error", "status": "done"},
            ))
            yield chat_history, trace_history
        else:
            yield chat_history
        return

    ai_response = extract_ai_response(_session_messages)
    elapsed = time.time() - t0_total
    logger.info("Agent response ready | elapsed=%.1fs | response_len=%d", elapsed, len(ai_response) if ai_response else 0)

    chat_history.append(ChatMessage(
        role="assistant",
        content=(ai_response or "[No textual response from agent]") + f"\n\n---\n⏱ {elapsed:.1f}s",
    ))

    if not compact:
        trace_history.append(ChatMessage(
            role="assistant",
            content=f"Workflow completed in {elapsed:.1f}s",
            metadata={"title": "✅ Workflow Complete", "status": "done", "duration": round(elapsed, 1)},
        ))
        yield chat_history, trace_history
    else:
        yield chat_history


async def on_submit(message, chat_hist, trace_hist, mode):
    if not message or not message.strip():
        if mode == "Side-by-side":
            yield chat_hist, trace_hist, ""
        else:
            yield chat_hist, [], ""
        return

    if mode == "Side-by-side":
        async for update in _run_with_trace(message, chat_hist, trace_hist, mode):
            if isinstance(update, tuple) and len(update) == 2:
                yield update[0], update[1], ""
            else:
                yield update, trace_hist, ""
    else:
        async for update in _run_with_trace(message, chat_hist, [], mode):
            if isinstance(update, list):
                yield update, [], ""
            else:
                yield update, [], ""


CSS = """
#trace-panel .message-row { padding: 2px 0 !important; }
#trace-panel .message-content { font-size: 0.85em; }
"""


def main():
    _el_head = (
        '<script src="https://unpkg.com/@elevenlabs/convai-widget-embed"'
        ' async type="text/javascript"></script>'
    ) if _show_voice_ui else ""

    with gr.Blocks(
        fill_height=True,
        title="TriageAide — FHIR-First Pre-Consultation Triage",
    ) as demo:
        gr.Markdown("# 🏥 TriageAide — FHIR-First Pre-Consultation Triage")

        with gr.Tabs():
            with gr.Tab("💬 Chat"):
                view_mode = gr.State("Side-by-side")

                with gr.Row():
                    view_toggle = gr.Radio(
                        choices=["Side-by-side", "Compact"],
                        value="Side-by-side",
                        label="View Mode",
                        interactive=True,
                        scale=2,
                    )
                    clear_all = gr.Button("🗑️ Clear All", variant="secondary", scale=1)

                with gr.Row(equal_height=True):
                    with gr.Column(scale=3) as chat_col:
                        chatbot = gr.Chatbot(
                            label="Patient Chat",
                            height=650,
                            layout="panel",
                            placeholder="<strong>Enter a patient ID or name to begin triage</strong>",
                        )
                        with gr.Row():
                            msg_input = gr.Textbox(
                                placeholder="Type your message and press Enter...",
                                show_label=False,
                                scale=4,
                                autofocus=True,
                            )
                            send_btn = gr.Button("Send", variant="primary", scale=1)
                        with gr.Row():
                            gr.Examples(
                                examples=[
                                    "Hi, I'm Maria Silva and I've been feeling really thirsty lately",
                                    "I'm Maria Silva, I've been having headaches and blurred vision",
                                    "Hi, I'm Joao Santos, I've been having chest pain",
                                    "I'm Joao Santos, I've been short of breath and my legs are swollen",
                                    "I'm Roberto Lima, my cough has been getting worse",
                                    "I'm Roberto Lima, I've been feeling sad and having trouble sleeping",
                                    "Hi, I'm Ana Costa, I've been having a fever and feeling tired",
                                    "I'm Ana Costa, I've had a cough for the past week",
                                    "Oi, sou a Maria Silva, ando com muita sede e visão embaçada",
                                    "Olá, sou o Roberto Lima, minha tosse está piorando",
                                ],
                                inputs=msg_input,
                            )

                    with gr.Column(scale=2) as trace_col:
                        trace = gr.Chatbot(
                            label="Agent Trace",
                            elem_id="trace-panel",
                            height=650,
                            layout="panel",
                            group_consecutive_messages=False,
                        )
                        clear_trace = gr.Button("Clear Trace", size="sm")

        if _show_voice_ui:
            with gr.Tab("🎙️ Voice (ElevenLabs)"):
                gr.Markdown("## Voice-Enabled Triage / Triagem por Voz")
                gr.Markdown(
                    "Speak with the triage agent in **English** or **Português (Brasil)**. "
                    "The agent responds in the language you use.\n\n"
                    "Fale com o agente de triagem em **inglês** ou **Português (Brasil)**. "
                    "O agente responde no idioma que você usar."
                )

                _el_agent_id = os.getenv("ELEVENLABS_WIDGET_ID", "") or os.getenv("ELEVENLABS_AGENT_ID", "")
                _bridge_url = os.getenv("VOICE_BRIDGE_URL", "http://localhost:8003")

                def _widget_html(agent_id: str) -> str:
                    agent_id = (agent_id or "").strip()
                    if not agent_id:
                        return (
                            '<div style="padding:32px;text-align:center;color:#6b7280;">'
                            '<p style="font-size:15px;">Enter your ElevenLabs Agent ID above and click '
                            '<strong>Load Widget</strong>.<br>'
                            'Digite o ID do agente ElevenLabs acima e clique em '
                            '<strong>Carregar Widget</strong>.</p>'
                            '</div>'
                        )
                    local_bridge = "http://localhost:8003"
                    iframe_url = f"{local_bridge}/widget?agent_id={agent_id}"
                    return (
                        '<div style="display:flex;flex-direction:column;align-items:center;gap:16px;padding:16px;">'
                        f'<elevenlabs-convai agent-id="{agent_id}" '
                        'style="width:100%;max-width:560px;min-height:420px;"></elevenlabs-convai>'
                        '<details style="width:100%;max-width:560px;">'
                        '<summary style="cursor:pointer;color:#6b7280;font-size:13px;padding:4px 0;">'
                        '🔄 Widget not showing? Try the standalone version / Widget não apareceu? Tente a versão standalone'
                        '</summary>'
                        f'<iframe src="{iframe_url}" width="100%" height="480" '
                        'style="border:1px solid #e5e7eb;border-radius:12px;margin-top:8px;" '
                        'allow="microphone; camera; autoplay; clipboard-write" allowfullscreen>'
                        '</iframe>'
                        '</details>'
                        '</div>'
                    )

                with gr.Row():
                    agent_id_box = gr.Textbox(
                        value=_el_agent_id,
                        placeholder="agent_XXXXXXXXXXXXXXXXXXXXXXXX",
                        label="ElevenLabs Agent ID",
                        scale=5,
                        interactive=True,
                    )
                    load_widget_btn = gr.Button("🎙️ Load Widget / Carregar Widget", variant="primary", scale=2)

                voice_widget = gr.HTML(value=_widget_html(_el_agent_id))

                load_widget_btn.click(fn=_widget_html, inputs=[agent_id_box], outputs=[voice_widget])
                agent_id_box.submit(fn=_widget_html, inputs=[agent_id_box], outputs=[voice_widget])

                with gr.Accordion("⚙️ Setup Instructions / Instruções de Configuração", open=not bool(_el_agent_id)):
                    gr.Markdown(f"""
                    **English — Custom LLM setup:**
                    1. In ElevenLabs dashboard → **Configure → Agent** → set **LLM** to *Custom LLM*
                    2. Set **LLM URL**: `{_bridge_url}/v1/chat/completions`
                    3. Set **Authorization**: `Bearer <VOICE_BRIDGE_SECRET>`
                    4. Select a Brazilian Portuguese voice
                    5. Copy the Agent ID from the URL and paste it in the field above

                    **Português — Configuração do Custom LLM:**
                    1. No dashboard ElevenLabs → **Configure → Agent** → defina **LLM** como *Custom LLM*
                    2. Configure **LLM URL**: `{_bridge_url}/v1/chat/completions`
                    3. Configure **Authorization**: `Bearer <VOICE_BRIDGE_SECRET>`
                    4. Selecione uma voz em Português do Brasil
                    5. Copie o Agent ID da URL e cole no campo acima
                    """)

                with gr.Row():
                    gr.Markdown(
                        f"**Voice Bridge:** `{_bridge_url}/v1/chat/completions` &nbsp;|&nbsp; "
                        f"**Health:** `{_bridge_url}/health`"
                    )

        trace_state = gr.State([])

        def switch_mode(mode):
            if mode == "Side-by-side":
                return gr.update(visible=True), gr.update(visible=True), mode
            else:
                return gr.update(visible=True), gr.update(visible=False), mode

        view_toggle.change(
            fn=switch_mode,
            inputs=[view_toggle],
            outputs=[chat_col, trace_col, view_mode],
        )

        msg_input.submit(
            fn=on_submit,
            inputs=[msg_input, chatbot, trace_state, view_mode],
            outputs=[chatbot, trace, msg_input],
        )

        send_btn.click(
            fn=on_submit,
            inputs=[msg_input, chatbot, trace_state, view_mode],
            outputs=[chatbot, trace, msg_input],
        )

        clear_trace.click(
            fn=lambda: ([],),
            inputs=[],
            outputs=[trace],
        )

        def clear_everything():
            global _session_messages
            _session_messages = []
            return [], [], ""

        clear_all.click(
            fn=clear_everything,
            inputs=[],
            outputs=[chatbot, trace, msg_input],
        )

    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        css=CSS,
        theme=gr.themes.Soft(),
        head=_el_head,
    )
    logger.info("Gradio UI launched on port 7860")


if __name__ == "__main__":
    main()
