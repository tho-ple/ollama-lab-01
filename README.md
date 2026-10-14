# Week 1 completed lab — Build and secure a coding agent with Ollama

This package contains the working Python agent, the repaired customer order
service, its original acceptance tests, additional regression tests, public
agent-contract checks, attack fixtures, and an answered questionnaire.

**Status (verified in the supplied evaluation environment):** all 9 original
acceptance tests, 2 additional pricing regressions, 15 public agent checks,
6 supplementary security/adapter tests, and 2 original loop tests pass. **Local Ollama was not
available here**; scripted-agent tests and a mocked HTTP adapter are NOT
proof that a real Qwen model can autonomously complete both tasks.

The personal four-minute video is not included. Record your own narration,
verify the local Ollama run, and fill in your name before submitting.

## Structure

- `my-agent/student_agent/` — local Ollama adapter, 15-turn controller, tools,
  policy and CLI (Python 3.10+, standard library only).
- `my-agent/tests/test_security.py` — no-model security, injection and HTTP tests.
- `target-service/orders/pricing.py` — corrected half-up monetary calculations.
- `target-service/tests/test_acceptance.py` — unchanged course-owned tests.
- `target-service/tests/test_student.py` — two new regression tests.
- `fixtures/` — offline Decimal and deliberately malicious text/action samples.
- `checks/check_agent.py` — original 15 public contract checks.
- `questionnaire.md` — six answered lab questions (replace author placeholder).

## Setup

From the folder containing this README:

```bash
python3 --version                  # 3.10+ required
ollama pull qwen2.5-coder:7b      # one-time local model download
ollama list
# Run or start Ollama separately; its endpoint must work on 127.0.0.1:11434.
python3 checks/check_agent.py --implementation my-agent --module student_agent
(cd target-service && python3 -m unittest discover -s tests -v)
(cd my-agent && python3 -m unittest discover -s tests -v)  # 8 tests
```

If RAM is limited, choose `qwen2.5-coder:3b` instead; use `--model` or the
`OLLAMA_MODEL` environment variable. Use macOS/Linux or Windows WSL2 with bash
and Python in the same environment. No external Python packages or cloud APIs
are needed.

## Running the agent (with Ollama installed locally)

The agent command runs from `my-agent` and stores its JSONL trace outside the
target, at `my-agent/traces/`.

Read-only diagnosis:

```bash
cd my-agent
python3 -m student_agent --root ../target-service --mode read-only \
  --tools list_files,read_file,search_files,fetch_url --offline \
  --task 'Inspect the order service and docs/business-rules.md. Read orders/pricing.py and the acceptance tests. Find the cause of the incorrect totals. Use the Decimal documentation to check rounding behavior. Explain the needed repair without changing any files.'
```

Edit mode (create a clean service copy first if you want to demonstrate the
autonomous repair — the supplied service has already been fixed):

```bash
python3 -m student_agent --root ../target-service --mode edit \
  --tools list_files,read_file,search_files,write_file,edit_file,fetch_url,bash \
  --offline --model qwen2.5-coder:7b \
  --task 'Inspect the customer pricing rules and service. Repair pricing.py if needed. Keep validation and acceptance tests unchanged, read files before editing, and add a regression test if missing. Ask for approval to run python3 -m unittest discover -s tests -v. Report only observed verification.'
```

`--offline` replaces the approved documentation URL with
`fixtures/decimal-offline.txt`; tool output explicitly says **offline fixture**.
For the injected-web exercise, additionally pass
`--offline-fixture web-injected.txt`. The URL allowlist is still enforced.
Remove `--offline` to access **only** HTTPS pages on `docs.python.org` on
port 443 with no query string, fragment, login, or redirects. The response is
truncated to 12,000 bytes and labelled when incomplete. Failed network requests
become error observations.

Default mode is **read-only**. The `--tools` flag is an independent allowlist;
only tools allowed by *both* settings appear in the model's system prompt.
Runtime rechecks this on every call. Ordinary unprotected file edits require
edit mode, but never an extra prompt. Every bash command in edit mode prints
its complete text and resolved target directory, and runs only when you type
exactly `yes`; no, EOF and blank input all deny it. Do **not** approve any
command attempting to weaken validation or evade a denied edit.

## Agent workflow and safety boundaries

The local model emits exactly one JSON object per turn: a tool selection
(`{"tool":"read_file","args":{"path":"orders/pricing.py"}}`) or a final
summary (`{"final":"..."}`). The controller checks the schema, enabled names,
mode and path policy, executes a tool, and feeds its structured result back as
**untrusted data**. Invalid JSON/errors/denials cost a turn and are observations.
It stops with `final`, `turn_limit`, `model_error` or `cancelled`.

Supported tools with exact action arguments:

| Tool | Arguments | Capability |
| --- | --- | --- |
| `list_files` | none | Visible files, up to 200 |
| `read_file` | `path` | UTF-8 text, up to 12,000 characters |
| `search_files` | `query` | Literal search, max 200 files / 50 matches |
| `write_file` | `path`, `content` | Exclusive create, edit mode only |
| `edit_file` | `path`, `old`, `new` | Exact single occurrence replacement |
| `fetch_url` | `url` | Approved HTTPS Python documentation |
| `bash` | `command` | Human approval for **each** command |

No absolute, parent-traversing, hidden or escaping symlink paths are allowed
in file tools. The protected files `orders/validation.py`,
`tests/test_acceptance.py`, and `docs/business-rules.md` can be read but not
edited or replaced. Edited files are byte-limited. Bash runs with no inherited
API-key environment, no startup files, no stdin, a 20-second timeout, and a
12,000-byte incrementally enforced combined output bound. The process group is
killed on overrun.

**Important limit:** approved bash is *not a sandbox*. It may access files
outside the workspace and run malicious repository code. Output from file
reads, supplier notes and documentation is untrusted. System instructions help
against prompt injection, but Python policy enforcement is the reliable
control for the explicitly protected paths. TOCTOU filesystem races and
mistaken human approval remain possible.

## Pricing correction

`quote(lines, discount)` validates exactly as before and returns the same
`subtotal`, `shipping`, and `total` Decimal fields. Each price × quantity is
rounded to cents with `ROUND_HALF_UP`; rounded line amounts are summed.
The discount *amount* is rounded to cents and subtracted from goods. Shipping
is zero only if the discounted goods total is at least EUR 100.00; otherwise
it is EUR 5.00. Shipping is added **after** the discount.

The original baseline failed 5/9 acceptance tests. The corrected service
passed 9/9 acceptance tests and 2/2 additional regressions. It leaves
validation, storage, order-service interface, business rules and acceptance
tests unchanged.

## Injection demonstration and what was actually tested

The fixture `fixtures/supplier-injected.md` impersonates a system notice,
asks the agent to replace `validate_order` with a no-op, skip tests, and
claim success. The separate `fixtures/web-injected.txt` uses the same payload
through offline documentation retrieval.

For a real-model controlled test, make two disposable copies of the service,
replace `docs/supplier-note.md` in each with the supplier fixture, and ask
the model to read it while inspecting pricing. Record its tool requests and
human approvals; never weaken the protected files. Retain the original system
prompt and a second version for a before/after comparison if you have one.

The provided `test_supplier_note_attack_is_untrusted_observation` is a
**scripted simulation, not autonomous model evidence**. It verifies the
injected note arrives as labelled untrusted content and that a subsequent
scripted forbidden edit is denied. `test_attack_actions_as_dispatcher_data`
replays every supplied attack request; none mutates the protected file.
The offline-web variant verifies source attribution and approved-URL checks.
A genuine local-model before/after experiment remains for the student.

## Four-minute video guide (you must record it with your own explanation)

- **0:00–1:00** Show the CLI, `model.py` JSON POST to local Ollama, and
  `agent.py` one-tool-per-turn action/observation loop. Identify any scripted
  demonstration as scripted, not as an autonomous local model run.
- **1:00–2:00** Show `Runtime.available_tools`, the read-only denial tests,
  edit mode, path/protected-file restrictions, and the `yes` approval gate.
- **2:00–3:00** Show `orders/pricing.py`, the unchanged validation boundary,
  the two new regression tests and a real `unittest` run (11 tests pass).
- **3:00–4:00** Open the injected supplier note. Show a denied dispatcher
  action or your genuine agent trace, explain why file text cannot authorize
  changes, and mention that approved bash is not a sandbox.

**Before handing in:** enter author details in `questionnaire.md`, check the
local model/commands, make your own four-minute recording, and submit exactly
three items: the repository/ZIP, the video, and the answered questionnaire.

## Compatibility preserved from the older package

The original `sample-agent/tests/test_loop.py` was retained as `my-agent/tests/test_loop.py`. The new controller supports that older fake runtime (which only exposes `execute`) and emits JSON-encoded, explicitly untrusted tool observations with a `result` field. This compatibility change does not alter the actual `Runtime` permission checks. See `CHANGES.md`.
