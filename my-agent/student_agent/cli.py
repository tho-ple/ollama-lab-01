"""Command-line entry point. Run from my-agent: python3 -m student_agent ..."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from .agent import run_agent
from .model import OllamaModel
from .runtime import Runtime, TOOL_ARGUMENTS


def build_parser():
    parser = argparse.ArgumentParser(description='Run the Week 1 Ollama coding agent')
    parser.add_argument('--root', required=True, help='target-service directory')
    parser.add_argument('--mode', choices=('read-only', 'edit'), default='read-only')
    parser.add_argument('--tools', help='comma-separated allowed tool names (default: all)')
    parser.add_argument('--model', default=os.environ.get('OLLAMA_MODEL', 'qwen2.5-coder:7b'))
    parser.add_argument('--offline', action='store_true', help='use labelled local documentation fixture')
    parser.add_argument('--offline-fixture', choices=('decimal-offline.txt', 'web-injected.txt'),
                        default='decimal-offline.txt')
    parser.add_argument('--task', required=True)
    parser.add_argument('--max-turns', type=int, default=15)
    parser.add_argument('--trace', help='JSONL output path outside the target')
    return parser


def confirm(command, cwd):
    print(f'\nComplete command: {command}\nResolved working directory: {cwd}')
    try:
        response = input('Approve this command only? Type yes: ')
    except EOFError:
        return False
    return response == 'yes'


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_turns not in range(1, 16):
        parser.error('--max-turns must be between 1 and 15')
    if args.offline_fixture != 'decimal-offline.txt' and not args.offline:
        parser.error('--offline-fixture requires --offline')
    enabled = None if args.tools is None else set(args.tools.split(','))
    if enabled is not None and (not all(enabled) or enabled - TOOL_ARGUMENTS.keys()):
        parser.error('--tools contains empty or unknown names')
    try:
        runtime = Runtime(args.root, mode=args.mode, enabled=enabled, approve=confirm,
                          offline=args.offline, offline_fixture=args.offline_fixture)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    base = Path(__file__).resolve().parent.parent  # my-agent, never target-service
    if args.trace:
        trace = Path(args.trace).expanduser().resolve()
        if trace == runtime.root or runtime.root in trace.parents:
            parser.error('trace must be stored outside target-service')
    else:
        trace = base / 'traces' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.jsonl')
    trace.parent.mkdir(parents=True, exist_ok=True)
    print(f'Running {args.model} in {args.mode} mode; allowed tools: {", ".join(runtime.available_tools)}')
    print(f'Trace (outside target): {trace}')

    def emit(event):
        with trace.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False, default=str) + '\n')
        if event.get('event') == 'request':
            print(f'Turn {event["turn"]} request: {str(event["request"])[:300]}')
        if event.get('event') == 'result':
            print(f'Turn {event["turn"]} tool result: {json.dumps(event["result"], ensure_ascii=False)[:400]}')
    result = run_agent(OllamaModel(args.model), runtime, args.task,
                       max_turns=args.max_turns, emit=emit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['termination'] == 'final' else 1


if __name__ == '__main__':
    sys.exit(main())
