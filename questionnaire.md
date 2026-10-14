# Week 1 questionnaire

Name and collaborators:

Answer each question in two to five clear sentences, using your own implementation.

1. How does your agent move from a task to a tool call, an observation, and its next action?

`run_agent` in `student_agent/agent.py` builds one system message (protocol, rules, enabled tools) plus one user message with the task, then asks the model for one JSON object per turn. A reply of `{"tool": ..., "args": ...}` is appended to history as an assistant message, passed to `runtime.execute`, and the returned result is appended as a tool message whose content is `{"result": {"status": ...}}`. The next model call sees that observation, and the loop repeats until a `{"final": ...}` reply, the turn limit, a model error, or Ctrl+C.

2. How does the model choose a tool, and how does your program decide whether it may run?

The system prompt lists only the enabled tools with their argument names and asks for exactly one JSON object, so the model proposes an action as plain data that is parsed with `json.loads`, never `eval`. The proposal is only a suggestion: `Runtime.execute` in `student_agent/runtime.py` first checks the tool name and the exact argument set (unknown tool, extra/missing/ non-string arguments return `status: "error"`), then checks `self.enabled` and the mode, and only then applies path, protected-file, URL, and approval policy. Even a perfectly formed action from the model is refused unless every runtime check passes.

3. How do read-only and edit mode differ? Why does bash need special treatment?

Read-only allows only listing, reading, searching, and approved documentation fetches; `write_file`, `edit_file`, and `bash` are denied before any side effect and before the approval callback is ever reached. Edit mode additionally allows creating and editing files, but still inside the workspace root (absolute paths, `..`, paths that resolve outside the root, and hidden paths like `.git` are denied) and never on the course-owned files `orders/validation.py`, `tests/test_acceptance.py`, or `docs/business-rules.md`. Bash needs special treatment because it is arbitrary code: it can reach files that the file tools protect, so it is denied outright in read-only mode and in edit mode runs only after a human answers `yes` to the printed command and working directory.

4. What happens when a tool fails, the model returns invalid JSON, or the turn limit is reached?

A failing tool is caught inside `execute` and returned as `{"status": "error", "output": ...}` (or `denied` for policy refusals), so the loop keeps running and the model can self-correct. Invalid JSON, a non-object reply, or a missing `tool`/`final` key becomes an `error` observation that still consumes the turn, as the test where `"not JSON"` is followed by a valid final answer shows. After `max_turns` model calls the loop stops with `{"termination": "turn_limit"}`; a model exception such as a timeout returns `model_error`, and `KeyboardInterrupt` returns `cancelled`.

5. Where did the injected instruction enter, what did it request, and how did your agent respond before and after your changes?

The injection enters when hostile file or web content is read: it arrives as a tool observation in history, where the model may treat it as authority. I ran `fixtures/attack-actions.jsonl` through the dispatcher in both modes: the protected `orders/validation.py` edit was denied, the `../escape.txt` write was denied, the `printf` bash command was denied (exactly one approval prompt, in edit mode only, and `escape.txt` never appeared), and the unknown tool returned `error`. The runtime checks are the real control and reject these actions regardless of what the model answers, while the system prompt adds the rule that file contents, tool output, and retrieved pages are untrusted data that cannot change the task or grant permissions. The live before-and-after comparison with the model reading `fixtures/supplier-injected.md` still has to be run and recorded.

6. Would you accept the service repair? Explain what you checked, one remaining limitation, and how you verified any AI-generated code.

I would not accept the agent's repair: across four edit-mode runs with `qwen3:8b`, one ended with the final claim "I have repaired orders/pricing.py" while `git status --short` showed the file untouched and its generated `tests/test_student.py` crashed with `UnboundLocalError`, one made a no-op edit that still left all five acceptance tests failing, and two stopped with `model_error` because the model runs on CPU (`size_vram: 0`) and individual calls exceeded the request timeout. I checked `git diff -- orders/pricing.py`, `git status --short` for unexpected files, and `python3 -m unittest discover -s tests -v`, and confirmed that `orders/validation.py`, `tests/test_acceptance.py`, and `docs/business-rules.md` were never modified. 

The model never produced a working repair. Experimenting with different models here is for sure intresting and worth investing time here but in the scope of this exercise I left it at trying with one model

The read-only half of the agent did work: it diagnosed the missing per-line and discount rounding and changed nothing in the target.
