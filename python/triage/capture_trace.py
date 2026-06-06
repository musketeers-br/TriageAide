import asyncio
import json
import time
import sys

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.callbacks import AsyncCallbackHandler

from agent import create_triage_agent, extract_ai_response
from logging_config import setup_logging

logger = setup_logging("capture_trace", "capture_trace.log")

_STEP_MAP = {
    "search_patients": 1,
    "get_patient": 1,
    "get_patient_conditions": 1,
    "get_patient_medications": 1,
    "get_patient_observations": 1,
    "get_patient_allergies": 1,
    "get_patient_encounters": 1,
    "get_next_triage_question": 2,
    "analyze_patient_response": 2,
    "build_questionnaire_response_data": 2,
    "check_red_flags": 3,
    "clinical_assessment": 4,
    "create_flag_and_task": 4,
    "create_questionnaire_response": 5,
    "create_encounter": 5,
    "create_observation": 5,
    "create_condition": 5,
}

_STEP_LABELS = {
    1: "STEP 1 — FHIR Query",
    2: "STEP 2 — Triage Questions",
    3: "STEP 3 — Red Flags Check",
    4: "STEP 4 — Clinical Reasoning",
    5: "STEP 5 — FHIR Update",
}


def summarize_tool_result(tool_name, output_str):
    try:
        data = json.loads(output_str)
        if tool_name == "search_patients":
            return f"{data.get('total', 0)} patient(s) found"
        if tool_name == "get_patient":
            return f"{data.get('name', '?')}, DOB {data.get('birthDate', '?')}"
        if tool_name.startswith("get_patient_"):
            total = data.get("total", 0)
            resource = tool_name.replace("get_patient_", "")
            return f"{total} {resource} retrieved"
        if tool_name == "analyze_patient_response":
            n = len(data.get("identified_symptoms", []))
            return f"{n} symptom(s), severity={data.get('overall_severity', '?')}"
        if tool_name == "check_red_flags":
            n = data.get("alert_count", 0)
            crit = data.get("has_critical_red_flag", False)
            return f"{n} alert(s)" + (" ** CRITICAL **" if crit else "")
        if tool_name == "clinical_assessment":
            risk = data.get("risk", {})
            pri = data.get("priority", {})
            return f"risk={risk.get('level','?')} (score {risk.get('score','?')}), priority={pri.get('level','?')}"
        if tool_name.startswith("create_"):
            rid = data.get("id", "?")
            rtype = data.get("resource", "?")
            return f"Created {rtype}/{rid}"
        if tool_name == "get_next_triage_question":
            q = data.get("question")
            if q is None:
                return "No more questions"
            return f'"{q[:60]}..." ({data.get("total_remaining", 0)} remaining)'
        if tool_name == "build_questionnaire_response_data":
            return f"{data.get('total', 0)} items structured"
        return "Done"
    except (json.JSONDecodeError, TypeError):
        text = output_str.strip()
        return text[:77] + "..." if len(text) > 80 else text or "Done"


def summarize_tool_input(tool_name, tool_input):
    if isinstance(tool_input, dict):
        if "patient_id" in tool_input:
            return f"patient_id={tool_input['patient_id']}"
        if "name" in tool_input:
            return f'name="{tool_input["name"]}"'
        items = list(tool_input.items())[:4]
        return ", ".join(f"{k}={v}" for k, v in items)
    return str(tool_input)[:60]


class CaptureTraceHandler(AsyncCallbackHandler):
    def __init__(self):
        self.events = []
        self._llm_num = 0
        self._tool_times = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._llm_num += 1
        self.events.append({
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
                        content_preview = (msg.content or "")[:500]
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tc_names.append(tc.get("name", "?"))
        except Exception:
            content_preview = str(response)[:300]
        self.events.append({
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
        self.events.append({
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
        self.events.append({
            "type": "tool_end",
            "tool_name": name,
            "run_id": rid,
            "output": output_str,
            "elapsed": elapsed,
        })


def format_trace(events):
    lines = []
    current_step = 0
    llm_num = 0
    open_llm_tools = []

    for event in events:
        etype = event["type"]

        if etype == "llm_start":
            llm_num = event["llm_num"]
            open_llm_tools = []
            lines.append(f"  LLM Reasoning #{llm_num} ...")

        elif etype == "llm_end":
            tc_names = event.get("tool_call_names", [])
            content_preview = event.get("content_preview", "")
            if tc_names:
                lines[-1] = f"  LLM #{llm_num} -> {', '.join(tc_names)}"
            else:
                lines[-1] = f"  LLM #{llm_num} . Generating response"
                if content_preview:
                    preview = content_preview[:200].replace('\n', ' ')
                    lines.append(f"    Thinking: {preview}...")

        elif etype == "tool_start":
            tool_name = event["tool_name"]
            tool_input = event.get("tool_input", {})
            step_num = _STEP_MAP.get(tool_name, 0)

            if step_num and step_num != current_step:
                current_step = step_num
                lines.append(f"\n  {_STEP_LABELS.get(step_num, f'Step {step_num}')}")

            input_summary = summarize_tool_input(tool_name, tool_input)
            args_json = json.dumps(tool_input, indent=2, default=str, ensure_ascii=False)[:600]
            lines.append(f"    -> {tool_name}({input_summary})")
            lines.append(f"       Args: {args_json}")

        elif etype == "tool_end":
            tool_name = event["tool_name"]
            output_str = event.get("output", "")
            elapsed = event.get("elapsed")
            summary = summarize_tool_result(tool_name, output_str)
            result_preview = output_str[:800]
            lines.append(f"    <- {tool_name} . {summary}" + (f" ({elapsed}s)" if elapsed else ""))
            lines.append(f"       Result: {result_preview}")

        elif etype == "tool_error":
            tool_name = event["tool_name"]
            err_str = event.get("error", "Unknown error")
            lines.append(f"    !! {tool_name} . Error: {err_str}")

    return "\n".join(lines)


async def run_scenario(patient_name, initial_message, follow_ups=None):
    logger.info("Creating triage agent for scenario: %s", patient_name)
    agent, client = await create_triage_agent(cache_namespace="capture")

    messages = []
    all_traces = {}

    all_messages_text = [initial_message] + (follow_ups or [])

    for i, user_msg in enumerate(all_messages_text):
        print(f"\n{'='*70}")
        print(f"  PATIENT MESSAGE #{i+1}: \"{user_msg}\"")
        print(f"{'='*70}")

        messages.append(HumanMessage(content=user_msg))

        handler = CaptureTraceHandler()
        t0 = time.time()

        try:
            result = await agent.ainvoke(
                {"messages": messages},
                config={"callbacks": [handler]},
            )

            elapsed = time.time() - t0
            response_messages = result.get("messages", [])
            ai_response = extract_ai_response(response_messages)

            messages = response_messages

            trace_text = format_trace(handler.events)
            all_traces[f"turn_{i+1}"] = {
                "user_message": user_msg,
                "agent_response": ai_response,
                "elapsed": round(elapsed, 1),
                "trace": trace_text,
                "events": handler.events,
            }

            print(f"\n  AGENT RESPONSE ({elapsed:.1f}s):")
            print(f"  {ai_response[:500] if ai_response else '[no text response]'}")
            print(f"\n  TRACE:")
            print(trace_text)

        except Exception as e:
            elapsed = time.time() - t0
            trace_text = format_trace(handler.events)
            all_traces[f"turn_{i+1}"] = {
                "user_message": user_msg,
                "agent_response": f"ERROR: {e}",
                "elapsed": round(elapsed, 1),
                "trace": trace_text,
                "events": handler.events,
            }
            print(f"\n  ERROR ({elapsed:.1f}s): {e}")
            print(f"\n  PARTIAL TRACE:")
            print(trace_text)

    return all_traces


async def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "joao"

    if scenario == "joao":
        print("=" * 70)
        print("  RUNNING SCENARIO: Joao Santos (Complex Cardiovascular)")
        print("  72M, HF+AF+CKD+DM2+HTN, Warfarin, reports breathing trouble")
        print("=" * 70)
        traces = await run_scenario(
            "Joao Santos",
            "Hi, I'm Joao Santos, I've been having trouble breathing at night and my legs are swollen",
            follow_ups=[
                "Yes, I've been noticing some bruising easily and my gums bleed when I brush my teeth",
                "I've also been feeling dizzy when I stand up, and I'm more tired than usual",
            ],
        )
        output_file = "trace_joao_santos.json"
    elif scenario == "ana":
        print("=" * 70)
        print("  RUNNING SCENARIO: Ana Costa (Low Risk)")
        print("  28F, healthy, reports mild sore throat")
        print("=" * 70)
        traces = await run_scenario(
            "Ana Costa",
            "Hi, I'm Ana Costa, I've had a sore throat for a couple of days and a mild fever",
            follow_ups=[
                "No, I don't have any difficulty breathing or swallowing. Just a scratchy throat and slight temperature.",
            ],
        )
        output_file = "trace_ana_costa.json"
    else:
        print(f"Unknown scenario: {scenario}")
        return

    with open(output_file, "w") as f:
        json.dump(traces, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n\nTrace data saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
