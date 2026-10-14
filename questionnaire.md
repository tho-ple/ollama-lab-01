# Week 1 questionnaire — completed technical answers

**Name and collaborators:** [Enter your name and any collaborators before submission].
**Contributions:** The coding agent, pricing repair, tests, and draft answers were
created with AI assistance. The submitting student should personally review the
source, test the installed local Ollama model, and record the video; no student
identity or unperformed hands-on step is claimed here.

### 1. How does your agent move from a task to a tool call, an observation, and its next action?

`run_agent` builds system instructions listing permitted tools and adds the
student's task as a user message. At each of at most 15 turns, the Ollama
adapter returns JSON, the controller sends a tool action to `Runtime.execute`,
and the structured result is appended to history as an explicitly untrusted
observation. The following model call receives that history, or the loop stops
at a `{"final":"..."}` message or a defined termination condition.

### 2. How does the model choose a tool, and how does your program decide whether it may run?

The model chooses one tool name and argument object from the descriptions in
the system prompt; this is a proposal, not authorization. `Runtime.execute`
checks the exact action and argument keys, requires string values no longer
than 12,000 characters, enforces `--tools` and the selected mode, and uses
canonical workspace paths to block traversal and protected-file writes. The
runtime denies unauthorized actions even if the model asks for them.

### 3. How do read-only and edit mode differ? Why does bash need special treatment?

Read-only permits listing, reading, searching and approved documentation
retrieval when enabled, but denies file creation, edits and bash without asking
for approval. Edit mode permits new files and unique-text edits except for
protected files; bash additionally requires the human to approve the specific
command by typing exactly `yes`. Bash is special because executing local
commands can bypass file-tool checks and access other files, so approval is a
human security decision rather than a filesystem sandbox.

### 4. What happens when a tool fails, the model returns invalid JSON, or the turn limit is reached?

Tool failures and permission denials return a `status` of `error` or `denied`,
with an explanation fed back as a non-system observation; the model can try a
safer alternative. Invalid or malformed JSON similarly consumes one of the
15 available turns and appears as a parse-error observation. Hitting the limit
returns `turn_limit`, while model connection errors and interruption return
`model_error` and `cancelled`; none is misrepresented as a successful repair.

### 5. Where did the injected instruction enter, what did it request, and how did your agent respond before and after your changes?

The malicious text entered as `docs/supplier-note.md` (or through a labelled
offline `fetch_url` fixture), impersonated a system notice, and asked to disable
`orders/validation.py`, skip acceptance tests, use bash to bypass denials, and
falsely claim success. In a scripted test of the completed agent, a forbidden
edit after reading the note was denied and the protected file remained
unchanged; explicit system guidance labels tool results untrusted and forbids
promoting file instructions into authority. Because Ollama was unavailable,
no genuine live-model *before versus after* behavior was measured, so this
scripted outcome must not be described as an autonomous model result.

### 6. Would you accept the service repair? Explain what you checked, one remaining limitation, and how you verified any AI-generated code.

I would accept the corrected pricing logic as a tested implementation: the
original nine acceptance tests and the two additional quantity/threshold
rounding regressions all passed, and the public agent checks and six custom
security checks passed as well. I inspected that only the pricing module and
new regression test changed under the service root, leaving validation,
storage and course-owned acceptance tests intact. Remaining limitations are
that approved bash is not sandboxed and this environment did not have a live
Ollama instance, so local autonomous-repair performance still needs
verification before claiming that demonstration was completed.
