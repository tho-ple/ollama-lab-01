# Repair changes (old ollama-lab-01-main -> repaired edition)

## Test evidence
- Original starter service: 4/9 acceptance tests passed, 5 failed.
- Supplied completed ZIP: 15/15 public agent-contract tests, 11/11 pricing tests and 6/6 security/adapter tests passed.
- Repaired older project: 15/15 public contract tests, 11/11 pricing tests, 8/8 tests in `my-agent/tests` passed (the 6 new checks plus 2 original loop tests).
- Local Ollama server was not accessible in this evaluation environment; a real `qwen2.5-coder:7b` run remains to be verified on Linux.

## Files changed/added
| Path | Change |
|---|---|
| `target-service/orders/pricing.py` | Replaced flawed pricing computation: round each line amount with `ROUND_HALF_UP`, sum rounded lines, round the discount amount separately, check free shipping against discounted goods (>= 100 EUR), add shipping AFTER discount. Kept the public function signature and dictionary keys. |
| `target-service/tests/test_student.py` | Added two regression tests: multiplication-before-rounding and rounding up to the free-shipping threshold. |
| `target-service/.gitignore` | Restored original starter ignore rules for `__pycache__/` and compiled Python files, so running tests does not dirty git status. |
| `target-service/README.md` | Clarified this is now a repaired service rather than the broken baseline. |
| `my-agent/student_agent/runtime.py` | Added completed tool registry, secure file-boundary and protected-file checks, strict permissions, bounded read/edit/search, allowlisted/offline documentation, manual bash approval and execution limits. |
| `my-agent/student_agent/model.py` | Completed local Ollama JSON adapter using 90s timeout, temperature 0, output limit 2048 tokens and bounded HTTP response. |
| `my-agent/student_agent/agent.py` | Enforced max-15-turn JSON controller, mode-filtered tool advertisement, error/denial observations, explicit stop reasons, untrusted input guidance. Extra compatibility fix: supports old fake runtime without `available_tools`; observation stays explicitly untrusted but uses JSON `result` to satisfy the original loop tests. |
| `my-agent/student_agent/cli.py` and `__main__.py` | Added CLI flags for root, mode, tools, model, offline documentation, task and trace, with strict yes-only bash approvals and JSONL logs outside target. |
| `my-agent/tests/test_security.py` | Added 6 security/adapter tests (including injected note and web fixtures). |
| `my-agent/tests/test_loop.py` | Retained the original 2 agent-loop tests from `sample-agent/tests/test_loop.py`, unchanged. |
| `README.md`, `questionnaire.md` | Copied the completed working instructions and drafted answers; review answers and fill in your author details. |
| `sample-agent/` | Removed the superseded implementation and old run traces; use `my-agent/`. |

## Explicitly unchanged
The following are byte-for-byte equal to the original lab starter package:
- `target-service/orders/validation.py`
- `target-service/orders/service.py`
- `target-service/orders/storage.py`
- `target-service/orders/__init__.py`
- `target-service/tests/test_acceptance.py`
- `target-service/docs/business-rules.md`
- `target-service/docs/supplier-note.md`

The public checks and injection fixtures also remain original.

## Verify on Linux

```bash
cd ollama-lab-01-main
python3 checks/check_agent.py --implementation my-agent --module student_agent
(cd target-service && python3 -m unittest discover -s tests -v)
(cd my-agent && python3 -m unittest discover -s tests -v)
```

Expected: `Ran 15 tests ... OK`, `Ran 11 tests ... OK`, `Ran 8 tests ... OK`.

For the real model, first start Ollama and run the **read-only** command in `README.md`. It was not possible to run a live model in this environment.
