"""Command-line entry point for the student agent."""

import argparse
import json
import os
import time
from pathlib import Path

from .agent import run_agent
from .model import OllamaModel
from .runtime import Runtime

DEFAULT_TRACE = os.environ.get("AGENT_TRACE", "agent-events.jsonl")


def build_parser():
    parser = argparse.ArgumentParser(description="Run the Week 1 coding agent")
    parser.add_argument("--root", required=True, help="target workspace")
    parser.add_argument(
        "--mode",
        choices=("read-only", "edit"),
        default="read-only",
    )
    parser.add_argument("--tools", help="comma-separated enabled tools")
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--task", required=True)
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--trace", default=DEFAULT_TRACE, help="JSONL event log outside the target")
    return parser


def ask_approval(command, cwd):
    print("Approve this command only? Type yes:")
    print(f"  cwd: {cwd}")
    print(f"  command: {command}")
    try:
        answer = input("> ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer == "yes"


def main():
    args = build_parser().parse_args()
    enabled = None
    if args.tools:
        enabled = [name.strip() for name in args.tools.split(",") if name.strip()]
    runtime = Runtime(
        args.root,
        mode=args.mode,
        enabled=enabled,
        approve=ask_approval,
        offline=args.offline,
    )
    model = OllamaModel(args.model)
    trace = Path(args.trace)

    def emit(event):
        stamped = {"ts": time.time(), **event}
        with trace.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(stamped) + "\n")

    result = run_agent(model, runtime, args.task, max_turns=args.max_turns, emit=emit)
    emit({"type": "termination", **result})
    print(f"termination: {result['termination']}")
    if result.get("error"):
        print(f"error: {result['error']}")
    if result.get("final"):
        print(result["final"])
    print(f"events appended to {trace}")


if __name__ == "__main__":
    main()
