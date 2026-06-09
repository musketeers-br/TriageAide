#!/usr/bin/env python3
"""Priority Test Harness — Turn-by-turn agent interaction for priority testing.

Usage:
  python3 test_priority.py start "Ana Costa" "Hi, I'm Ana Costa, I've been having a fever"
  python3 test_priority.py reply "It started two days ago, just a low fever"
  python3 test_priority.py status
  python3 test_priority.py reset
  python3 test_priority.py runs

Session state is persisted to /tmp/triage_test_session.json between calls.
Each invocation creates a fresh agent and replays the message history.
Run logs (full turn-by-turn JSON) are auto-saved to test-runs/ on every call.
Set LLM_CACHE=off to ensure fresh (non-cached) LLM responses.
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

load_dotenv(override=True)

from agent import create_triage_agent, extract_ai_response
from logging_config import setup_logging

logger = setup_logging("test_priority")

SESSION_FILE = Path("/tmp/triage_test_session.json")
TEST_RUNS_DIR = Path(__file__).parent / "test-runs"

EXPECTED = {
    "Ana Costa": {"priority": "routine", "risk": "low", "patient_id": "2605"},
    "Maria Silva": {"priority": "urgent", "risk": "moderate", "patient_id": "2627"},
    "Roberto Lima": {"priority": "urgent", "risk": "high", "patient_id": "2642"},
    "Joao Santos": {"priority": "emergency", "risk": "critical", "patient_id": "2610"},
}


def _load_session():
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return None


def _save_session(session):
    SESSION_FILE.write_text(json.dumps(session, indent=2, default=str, ensure_ascii=False))


def _serialize_message(msg):
    from langchain_core.messages import ToolMessage
    data = {"type": msg.__class__.__name__.lower().replace("message", "")}
    if isinstance(msg, HumanMessage):
        data["type"] = "human"
        data["content"] = msg.content
    elif isinstance(msg, AIMessage):
        data["type"] = "ai"
        data["content"] = msg.content
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            data["tool_calls"] = msg.tool_calls
        if msg.id:
            data["id"] = msg.id
    elif isinstance(msg, ToolMessage):
        data["type"] = "tool"
        data["content"] = msg.content
        data["tool_call_id"] = msg.tool_call_id
        data["name"] = msg.name
    return data


def _deserialize_message(m):
    from langchain_core.messages import ToolMessage
    mtype = m.get("type", "")
    if mtype == "human":
        return HumanMessage(content=m["content"])
    elif mtype == "ai":
        kwargs = {"content": m.get("content", "")}
        if "tool_calls" in m:
            kwargs["tool_calls"] = m["tool_calls"]
        if "id" in m:
            kwargs["id"] = m["id"]
        return AIMessage(**kwargs)
    elif mtype == "tool":
        return ToolMessage(
            content=m.get("content", ""),
            tool_call_id=m.get("tool_call_id", ""),
            name=m.get("name", ""),
        )
    return None


def _messages_from_session(session):
    msgs = []
    for m in session["messages"]:
        msg = _deserialize_message(m)
        if msg is not None:
            msgs.append(msg)
    return msgs


def _messages_to_session(result_messages):
    msgs = []
    for m in result_messages:
        data = _serialize_message(m)
        if data:
            msgs.append(data)
    return msgs


def _extract_priority(text):
    if not text:
        return None
    p = re.search(r'\*\*Priority:\*\*\s*(routine|urgent|emergency)', text, re.IGNORECASE)
    if p:
        return p.group(1).lower()
    p = re.search(r'\bPriority\b[:\s-]*(routine|urgent|emergency)', text, re.IGNORECASE)
    if p:
        return p.group(1).lower()
    return None


def _extract_risk(text):
    if not text:
        return None
    p = re.search(r'\*\*Risk:\*\*\s*(low|moderate|high|critical)', text, re.IGNORECASE)
    if p:
        return p.group(1).lower()
    p = re.search(r'\bRisk\b[:\s-]*(low|moderate|high|critical)', text, re.IGNORECASE)
    if p:
        return p.group(1).lower()
    return None


def _extract_tool_calls_from_messages(result_messages):
    tool_calls = []
    tool_results = {}

    for msg in result_messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "name": tc.get("name", tc.get("function", {}).get("name", "")),
                    "args": tc.get("args", tc.get("function", {}).get("arguments", {})),
                })
        elif isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, str) and len(content) > 300:
                summary = content[:300] + "..."
            elif isinstance(content, list):
                summary = str(content)[:300] + "..."
            else:
                summary = str(content)
            tool_results[msg.tool_call_id] = {
                "tool_name": msg.name,
                "result_summary": summary,
            }

    for tc in tool_calls:
        tc_name = tc["name"]
        tc["result_summary"] = None
        for tr in tool_results.values():
            if tr["tool_name"] == tc_name:
                tc["result_summary"] = tr["result_summary"]
                break

    return tool_calls


def _extract_patient_id_from_messages(result_messages):
    for msg in result_messages:
        if isinstance(msg, ToolMessage) and msg.name in ("search_patients", "get_patient"):
            content = msg.content
            if isinstance(content, str):
                m = re.search(r'"id"\s*:\s*"(\d+)"', content)
                if m:
                    return m.group(1)
                m = re.search(r'Patient/(\d+)', content)
                if m:
                    return m.group(1)
    return None


def _compute_pass_fail(actual_priority, actual_risk, expected_priority, expected_risk):
    if not actual_priority:
        return "incomplete"
    if actual_priority == expected_priority:
        if actual_risk == expected_risk:
            return "pass"
        if actual_risk and expected_risk:
            risk_order = ["low", "moderate", "high", "critical"]
            ai = risk_order.index(actual_risk) if actual_risk in risk_order else -1
            ei = risk_order.index(expected_risk) if expected_risk in risk_order else -1
            if abs(ai - ei) <= 1:
                return "pass"
            return "partial"
        return "pass"
    if actual_risk and expected_risk:
        risk_order = ["low", "moderate", "high", "critical"]
        ai = risk_order.index(actual_risk) if actual_risk in risk_order else -1
        ei = risk_order.index(expected_risk) if expected_risk in risk_order else -1
        if actual_priority in ("urgent", "emergency") and expected_priority in ("urgent", "emergency") and ai >= ei:
            return "partial"
    if expected_priority == "routine" and actual_priority in ("urgent", "emergency"):
        return "fail"
    if expected_priority == "emergency" and actual_priority != "emergency":
        return "fail"
    return "partial"


def _sanitize_name(name):
    return name.lower().replace(" ", "-").replace("'", "")


def _run_log_path(run_id):
    TEST_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return TEST_RUNS_DIR / f"run_{run_id}.json"


def _load_run_log(run_id):
    path = _run_log_path(run_id)
    if path.exists():
        return json.loads(path.read_text())
    return None


def _save_run_log(run_log):
    path = _run_log_path(run_log["run_id"])
    path.write_text(json.dumps(run_log, indent=2, default=str, ensure_ascii=False))


def _save_run_log_from_session(session, result_messages, elapsed, error=None):
    run_id = session.get("run_id")
    if not run_id:
        return

    run_log = _load_run_log(run_id)
    if not run_log:
        return

    turn_count = session.get("turn_count", 0)
    ai_response = session.get("last_response", "")

    patient_msg = session.get("_current_patient_msg", "")
    session.pop("_current_patient_msg", None)

    tool_calls = _extract_tool_calls_from_messages(result_messages) if result_messages else []

    patient_id = run_log.get("patient_id") or session.get("patient_id")
    if not patient_id and result_messages:
        patient_id = _extract_patient_id_from_messages(result_messages)
    if patient_id:
        run_log["patient_id"] = patient_id

    turn_data = {
        "turn": turn_count,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "patient_message": patient_msg,
        "agent_response": ai_response or "",
        "elapsed_sec": round(elapsed, 1),
        "tool_calls": tool_calls,
        "priority_detected": _extract_priority(ai_response),
        "risk_detected": _extract_risk(ai_response),
    }
    if error:
        turn_data["error"] = f"{type(error).__name__}: {error}"

    run_log["turns"].append(turn_data)
    run_log["total_turns"] = len(run_log["turns"])
    run_log["total_elapsed_sec"] = round(
        sum(t.get("elapsed_sec", 0) for t in run_log["turns"]), 1
    )

    priority = session.get("priority")
    risk = session.get("risk")
    if priority:
        run_log["final_priority"] = priority
    if risk:
        run_log["final_risk"] = risk

    expected = EXPECTED.get(run_log.get("patient_name", ""), {})
    run_log["expected_priority"] = expected.get("priority")
    run_log["expected_risk"] = expected.get("risk")
    run_log["pass_fail"] = _compute_pass_fail(
        run_log.get("final_priority"),
        run_log.get("final_risk"),
        run_log.get("expected_priority"),
        run_log.get("expected_risk"),
    )

    if run_log["turns"] and run_log["turns"][-1].get("error"):
        if "errors" not in run_log:
            run_log["errors"] = []
        run_log["errors"].append(run_log["turns"][-1]["error"])

    _save_run_log(run_log)


async def _invoke_agent(session):
    agent, client = await create_triage_agent(cache_namespace="test_priority")
    messages = _messages_from_session(session)

    t0 = time.time()
    result_messages = []
    error = None
    try:
        result = await agent.ainvoke({"messages": messages})
        result_messages = result.get("messages", [])
    except Exception as e:
        error = e
        logger.error("Agent error: %s: %s", type(e).__name__, e)
        print(f"\nERROR: {type(e).__name__}: {e}\n")

    elapsed = time.time() - t0
    ai_response = extract_ai_response(result_messages) if result_messages else None

    session["messages"] = _messages_to_session(result_messages) if result_messages else session["messages"]
    session["turn_count"] = session.get("turn_count", 0) + 1
    session["last_response"] = ai_response
    session["last_elapsed"] = round(elapsed, 1)

    priority = _extract_priority(ai_response)
    risk = _extract_risk(ai_response)
    if priority:
        session["priority"] = priority
    if risk:
        session["risk"] = risk

    _save_session(session)

    _save_run_log_from_session(session, result_messages, elapsed, error)

    print(f"\n{'='*60}")
    print(f"AGENT [turn {session['turn_count']}] ({elapsed:.1f}s):")
    print(f"{'='*60}")
    print(ai_response or "[No textual response]")
    print(f"{'='*60}")

    if priority:
        print(f"\n>>> PRIORITY DETECTED: {priority.upper()} <<<")
    if risk:
        print(f">>> RISK DETECTED: {risk.upper()} <<<")
    if priority or risk:
        print(">>> TRIAGE COMPLETE <<<\n")

    return session


async def cmd_start(patient_name, opening_message):
    existing = _load_session()
    if existing:
        print(f"Existing session found for: {existing.get('patient_name', '?')}")
        print("Use 'reset' first, then 'start'.")
        return

    timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    run_id = f"{timestamp}_{_sanitize_name(patient_name)}"

    expected = EXPECTED.get(patient_name, {})

    session = {
        "patient_name": patient_name,
        "opening_message": opening_message,
        "messages": [{"type": "human", "content": opening_message}],
        "turn_count": 0,
        "priority": None,
        "risk": None,
        "last_response": None,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run_id": run_id,
        "_current_patient_msg": opening_message,
    }

    run_log = {
        "run_id": run_id,
        "patient_name": patient_name,
        "patient_id": expected.get("patient_id"),
        "started_at": session["started_at"],
        "completed_at": None,
        "final_priority": None,
        "final_risk": None,
        "expected_priority": expected.get("priority"),
        "expected_risk": expected.get("risk"),
        "pass_fail": "incomplete",
        "total_turns": 0,
        "total_elapsed_sec": 0,
        "turns": [],
        "errors": [],
        "evaluation_notes": "",
    }
    _save_run_log(run_log)

    _save_session(session)
    print(f"Session started: patient={patient_name}")
    print(f"Run log: {_run_log_path(run_id)}")
    print(f"Opening: {opening_message}\n")

    await _invoke_agent(session)


async def cmd_reply(answer):
    session = _load_session()
    if not session:
        print("No active session. Use 'start' first.")
        return

    if session.get("priority"):
        print(f"Triage already complete. Priority={session['priority'].upper()}, Risk={session.get('risk','?').upper()}")
        print("Use 'reset' to start a new patient.")
        return

    session["messages"].append({"type": "human", "content": answer})
    session["_current_patient_msg"] = answer
    _save_session(session)
    print(f"Patient: {answer}\n")

    await _invoke_agent(session)


def cmd_status():
    session = _load_session()
    if not session:
        print("No active session.")
        return
    print(f"Patient: {session.get('patient_name', '?')}")
    print(f"Run ID: {session.get('run_id', '?')}")
    print(f"Started at: {session.get('started_at', '?')}")
    print(f"Turns: {session.get('turn_count', 0)}")
    print(f"Priority: {session.get('priority') or '(not determined yet)'}")
    print(f"Risk: {session.get('risk') or '(not determined yet)'}")
    lr = session.get('last_response') or ''
    print(f"Last response: {lr[:200]}{'...' if len(lr) > 200 else ''}")


def cmd_reset():
    session = _load_session()
    if session:
        run_id = session.get("run_id")
        if run_id:
            run_log = _load_run_log(run_id)
            if run_log:
                run_log["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                if not run_log.get("final_priority"):
                    run_log["pass_fail"] = "incomplete"
                _save_run_log(run_log)
                print(f"Run log saved: {_run_log_path(run_id)}")

    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        print("Session cleared.")
    else:
        print("No session to clear.")


def cmd_runs():
    if not TEST_RUNS_DIR.exists():
        print("No test runs found. Run 'start' to begin a test.")
        return

    run_files = sorted(TEST_RUNS_DIR.glob("run_*.json"))
    if not run_files:
        print("No test runs found.")
        return

    print(f"\nPast test runs in {TEST_RUNS_DIR}/:\n")
    print(f"{'DATE':<22} {'PATIENT':<18} {'PRIORITY':<12} {'RISK':<12} {'RESULT':<10}")
    print("-" * 74)

    for rf in run_files:
        try:
            data = json.loads(rf.read_text())
        except json.JSONDecodeError:
            continue
        date = data.get("started_at", "?")[:19]
        patient = data.get("patient_name", "?")
        priority = data.get("final_priority") or "-"
        risk = data.get("final_risk") or "-"
        result = data.get("pass_fail", "?")
        print(f"{date:<22} {patient:<18} {priority:<12} {risk:<12} {result:<10}")

    print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "start":
        if len(sys.argv) < 4:
            print("Usage: test_priority.py start <patient_name> <opening_message>")
            sys.exit(1)
        patient_name = sys.argv[2]
        opening_message = sys.argv[3]
        asyncio.run(cmd_start(patient_name, opening_message))

    elif cmd == "reply":
        if len(sys.argv) < 3:
            print("Usage: test_priority.py reply <patient_answer>")
            sys.exit(1)
        answer = sys.argv[2]
        asyncio.run(cmd_reply(answer))

    elif cmd == "status":
        cmd_status()

    elif cmd == "reset":
        cmd_reset()

    elif cmd == "runs":
        cmd_runs()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
