"""Tool registry and permission boundary."""

import os
import signal
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOOL_ARGUMENTS = {
    "list_files": (),
    "read_file": ("path",),
    "search_files": ("query",),
    "write_file": ("path", "content"),
    "edit_file": ("path", "old", "new"),
    "fetch_url": ("url",),
    "bash": ("command",),
}

MUTATING_TOOLS = frozenset({"write_file", "edit_file", "bash"})

PROTECTED_FILES = frozenset(
    {
        "orders/validation.py",
        "tests/test_acceptance.py",
        "docs/business-rules.md",
    }
)

MAX_ARGUMENT_CHARS = 12000
MAX_READ_CHARS = 12000
MAX_FILE_BYTES = 12000
MAX_LISTED_FILES = 200
MAX_SEARCH_FILES = 200
MAX_SEARCH_MATCHES = 50
SEARCH_READ_BYTES = 200000
FETCH_HOST = "docs.python.org"
FETCH_TIMEOUT = 10
FETCH_READ_BYTES = 12000
BASH_TIMEOUT = 20
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
MINIMAL_ENV = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
    "TZ",
    "TMP",
    "TEMP",
    "TMPDIR",
    "USERPROFILE",
    "SystemRoot",
    "COMSPEC",
    "WINDIR",
    "PATHEXT",
)


def _ok(output):
    return {"status": "ok", "output": output}


def _error(output):
    return {"status": "error", "output": output}


def _denied(output):
    return {"status": "denied", "output": output}


def _read_bounded(path, limit):
    with path.open("rb") as handle:
        return handle.read(limit + 1)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):
        return None


class Runtime:
    """Validate and execute model-requested tools inside a workspace."""

    def __init__(
        self,
        root,
        mode="read-only",
        enabled=None,
        approve=None,
        offline=False,
    ):
        self.root = Path(root).resolve()
        self.mode = mode
        self.enabled = set(TOOL_ARGUMENTS if enabled is None else enabled)
        self.approve = approve or (lambda _command, _cwd: False)
        self.offline = offline

    def execute(self, action):
        """Validate one action, enforce policy, and return a result object."""
        tool, args, problem = self._validate(action)
        if problem is not None:
            return problem
        if tool not in self.enabled:
            return _denied(f"tool '{tool}' is not enabled")
        if tool in MUTATING_TOOLS and self.mode != "edit":
            return _denied(f"tool '{tool}' is not allowed in '{self.mode}' mode")
        try:
            return self._dispatch(tool, args)
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}")

    def _validate(self, action):
        if not isinstance(action, dict):
            return None, None, _error('action must look like {"tool": ..., "args": {...}}')
        tool = action.get("tool")
        if not isinstance(tool, str) or tool not in TOOL_ARGUMENTS:
            return None, None, _error(f"unknown tool: {tool!r}; expected one of {', '.join(TOOL_ARGUMENTS)}")
        args = action.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return None, None, _error("the 'args' value must be JSON object")
        expected = TOOL_ARGUMENTS[tool]
        if set(args) != set(expected):
            return None, None, _error(f"{tool} expects exactly these arguments: {', '.join(expected) or 'none'}")
        for name in expected:
            value = args[name]
            if not isinstance(value, str):
                return None, None, _error(f"argument '{name}' must be a string")
            if len(value) > MAX_ARGUMENT_CHARS:
                return None, None, _error(f"argument '{name}' exceeds {MAX_ARGUMENT_CHARS} characters")
        return tool, args, None

    def _dispatch(self, tool, args):
        if tool == "list_files":
            return self._list_files()
        if tool == "read_file":
            return self._read_file(args["path"])
        if tool == "search_files":
            return self._search_files(args["query"])
        if tool == "write_file":
            return self._write_file(args["path"], args["content"])
        if tool == "edit_file":
            return self._edit_file(args["path"], args["old"], args["new"])
        if tool == "fetch_url":
            return self._fetch_url(args["url"])
        return self._bash(args["command"])

    def _resolve_path(self, raw):
        if not isinstance(raw, str) or not raw.strip():
            return None, _error("path must be a non-empty string")
        requested = Path(raw)
        if requested.is_absolute():
            return None, _denied("absolute paths are not allowed")
        if ".." in requested.parts:
            return None, _denied("path escapes the workspace")
        resolved = (self.root / requested).resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError:
            return None, _denied("path resolves outside the workspace")
        if any(part.startswith(".") for part in relative.parts):
            return None, _denied("hidden paths such as .git and .venv are not allowed")
        return resolved, None

    def _is_protected(self, resolved):
        return resolved.relative_to(self.root).as_posix() in PROTECTED_FILES

    def _walk(self):
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                yield Path(dirpath) / name

    def _list_files(self):
        entries = []
        truncated = False
        for file in self._walk():
            entries.append(file.relative_to(self.root).as_posix())
            if len(entries) >= MAX_LISTED_FILES:
                truncated = True
                break
        return _ok({"files": entries, "truncated": truncated})

    def _read_file(self, raw):
        resolved, problem = self._resolve_path(raw)
        if problem is not None:
            return problem
        if not resolved.is_file():
            return _error(f"not a readable file: {raw}")
        text = resolved.read_text(encoding="utf-8")
        if len(text) > MAX_READ_CHARS:
            return _ok(text[:MAX_READ_CHARS] + f"\n...[truncated {len(text) - MAX_READ_CHARS} characters]")
        return _ok(text)

    def _search_files(self, query):
        if not query:
            return _error("query must not be empty")
        matches = []
        scanned = 0
        truncated = False
        for file in self._walk():
            scanned += 1
            if scanned > MAX_SEARCH_FILES:
                truncated = True
                break
            try:
                data = _read_bounded(file, SEARCH_READ_BYTES)
            except OSError:
                continue
            if b"\x00" in data[:8192]:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if query not in line:
                    continue
                matches.append(
                    {
                        "path": file.relative_to(self.root).as_posix(),
                        "line": number,
                        "excerpt": line.strip()[:200],
                    }
                )
                if len(matches) >= MAX_SEARCH_MATCHES:
                    truncated = True
                    break
            if truncated:
                break
        return _ok({"matches": matches, "scanned": scanned, "truncated": truncated})

    def _write_file(self, raw, content):
        resolved, problem = self._resolve_path(raw)
        if problem is not None:
            return problem
        if self._is_protected(resolved):
            return _denied(f"course-owned file cannot be written: {raw}")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            return _error(f"content exceeds {MAX_FILE_BYTES} bytes")
        if resolved.exists():
            return _error(f"file already exists: {raw}")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        try:
            with resolved.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError:
            return _error(f"file already exists: {raw}")
        return _ok(f"created {raw} with {len(content)} characters")

    def _edit_file(self, raw, old, new):
        resolved, problem = self._resolve_path(raw)
        if problem is not None:
            return problem
        if self._is_protected(resolved):
            return _denied(f"course-owned file cannot be edited: {raw}")
        if not old:
            return _error("'old' must not be empty")
        if not resolved.is_file():
            return _error(f"not a readable file: {raw}")
        if resolved.stat().st_size > MAX_FILE_BYTES:
            return _error(f"{raw} is larger than {MAX_FILE_BYTES} bytes")
        text = resolved.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            return _error("'old' text not found; re-read the file and copy the text exactly")
        if count > 1:
            return _error(f"'old' text matches {count} times; include more surrounding context")
        updated = text.replace(old, new)
        if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
            return _error(f"edited file would exceed {MAX_FILE_BYTES} bytes")
        resolved.write_text(updated, encoding="utf-8")
        return _ok(f"edited {raw}")

    def _validate_url(self, url):
        if not url.startswith("https://"):
            return _denied("only HTTPS URLs are allowed")
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port
        except ValueError:
            return _denied("the URL has an invalid port")
        if parts.username or parts.password:
            return _denied("credentials in a URL are not allowed")
        if parts.hostname != FETCH_HOST:
            return _denied(f"only https://{FETCH_HOST} is allowed")
        if parts.query or parts.fragment:
            return _denied("query strings and fragments are not allowed")
        if port not in (None, 443):
            return _denied("only the default HTTPS port is allowed")
        return None

    def _fetch_url(self, url):
        problem = self._validate_url(url)
        if problem is not None:
            return problem
        if self.offline:
            return self._offline_fixture(url)
        return self._live_fetch(url)

    def _offline_fixture(self, url):
        fixture = FIXTURES_DIR / "decimal-offline.txt"
        if not fixture.is_file():
            return _error(f"offline fixture is missing: {fixture}")
        data = _read_bounded(fixture, FETCH_READ_BYTES)
        truncated = len(data) > FETCH_READ_BYTES
        return _ok(
            {
                "url": url,
                "content": data[:FETCH_READ_BYTES].decode("utf-8", errors="replace"),
                "truncated": truncated,
                "source": "offline fixture",
            }
        )

    def _live_fetch(self, url):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "student-agent/1.0", "Accept": "text/html, text/plain"},
        )
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=FETCH_TIMEOUT) as response:
                if not response.headers.get_content_type().startswith("text/"):
                    return _error(f"refusing non-text content type: {response.headers.get_content_type()}")
                data = response.read(FETCH_READ_BYTES + 1)
        except urllib.error.HTTPError as exc:
            return _error(f"HTTP {exc.code} while fetching {url} (redirects are refused)")
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}")
        truncated = len(data) > FETCH_READ_BYTES
        return _ok(
            {
                "url": url,
                "content": data[:FETCH_READ_BYTES].decode("utf-8", errors="replace"),
                "truncated": truncated,
                "source": "live",
            }
        )

    def _bash(self, command):
        cwd = str(self.root)
        if not self.approve(command, cwd):
            return _denied("command was not approved")
        env = {name: os.environ[name] for name in MINIMAL_ENV if name in os.environ}
        try:
            process = subprocess.Popen(
                ["bash", "--noprofile", "--norc", "-c", command],
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                errors="replace",
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            return _error(f"bash is unavailable: {exc}")
        try:
            output, _ = process.communicate(timeout=BASH_TIMEOUT)
        except subprocess.TimeoutExpired:
            _stop(process)
            return _error(f"command timed out after {BASH_TIMEOUT}s")
        except KeyboardInterrupt:
            _stop(process)
            raise
        text = output or ""
        truncated = len(text) > MAX_ARGUMENT_CHARS
        if truncated:
            text = text[:MAX_ARGUMENT_CHARS] + "\n...[truncated]"
        return _ok({"exit_code": process.returncode, "output": text, "truncated": truncated})


def _stop(process):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass
