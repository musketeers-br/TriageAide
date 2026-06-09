#!/usr/bin/env python3
"""Priority Test Harness — Turn-by-turn agent interaction for priority testing.

Usage:
  python3 test_priority.py start "Ana Costa" "Hi, I'm Ana Costa, I've been having a fever"
  python3 test_priority.py reply "It started two days ago, just a low fever"
  python3 test_priority.py status
  python3 test_priority.py reset

Session state is persisted to /tmp/triage_test_session.json between calls.
Each invocation creates a fresh agent and replays the message history.
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


async def _invoke_agent(session):
    agent, client = await create_triage_agent(cache_namespace="test_priority")
    messages = _messages_from_session(session)

    t0 = time.time()
    try:
        result = await agent.ainvoke({"messages": messages})
    except Exception as e:
        logger.error("Agent error: %s: %s", type(e).__name__, e)
        print(f"\nERROR: {type(e).__name__}: {e}\n")
        return session

    elapsed = time.time() - t0
    result_messages = result.get("messages", [])
    ai_response = extract_ai_response(result_messages)

    session["messages"] = _messages_to_session(result_messages)
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

    session = {
        "patient_name": patient_name,
        "opening_message": opening_message,
        "messages": [{"type": "human", "content": opening_message}],
        "turn_count": 0,
        "priority": None,
        "risk": None,
        "last_response": None,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save_session(session)
    print(f"Session started: patient={patient_name}")
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
    _save_session(session)
    print(f"Patient: {answer}\n")

    await _invoke_agent(session)


def cmd_status():
    session = _load_session()
    if not session:
        print("No active session.")
        return
    print(f"Patient:          {session.get('patient_name', '?')}")
    print(f"Started at:       {session.get('started_at', '?')}")
    print(f"Turns:            {session.get('turn_count', 0)}")
    print(f"Priority:         {session.get('priority') or '(not determined yet)'}")
    print(f"Risk:             {session.get('risk') or '(not determined yet)'}")
    lr = session.get('last_response') or ''
    print(f"Last response:    {lr[:200]}{'...' if len(lr) > 200 else ''}")


def cmd_reset():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        print("Session cleared.")
    else:
        print("No session to clear.")


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

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
