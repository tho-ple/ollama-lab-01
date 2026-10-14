"""Tool registry, strict workspace boundaries, and host-enforced permissions.

This is a permission gate, NOT a sandbox. In particular, approved bash code is
not confined to the workspace and must be reviewed by the user first.
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import selectors
import signal
import subprocess
import time
from urllib import error, parse, request


LIMIT = 12_000
MAX_FILES = 200
MAX_MATCHES = 50
PROTECTED = frozenset({
    'orders/validation.py',
    'tests/test_acceptance.py',
    'docs/business-rules.md',
})
TOOL_ARGUMENTS = {
    'list_files': (),
    'read_file': ('path',),
    'search_files': ('query',),
    'write_file': ('path', 'content'),
    'edit_file': ('path', 'old', 'new'),
    'fetch_url': ('url',),
    'bash': ('command',),
}
TOOL_DESCRIPTIONS = {
    'list_files': 'List up to 200 visible files inside the target.',
    'read_file': 'Read at most 12000 characters of one workspace text file.',
    'search_files': 'Search visible workspace text files for an exact, literal string.',
    'write_file': 'Create a new file exclusively; never overwrite.',
    'edit_file': 'Replace one unambiguous occurrence of old text in a file.',
    'fetch_url': 'Retrieve approved Python documentation using HTTPS (or a labelled offline fixture).',
    'bash': 'Run a shell command ONLY after the human explicitly approves it.',
}
READ_TOOLS = frozenset({'list_files', 'read_file', 'search_files', 'fetch_url'})
EDIT_TOOLS = frozenset({'write_file', 'edit_file', 'bash'})


class Denied(Exception):
    """Request violated the active policy."""


def answer(status, output):
    return {'status': status, 'output': output}


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Runtime:
    """Validate, authorize, and execute exactly one well-formed tool action."""

    def __init__(self, root, mode='read-only', enabled=None, approve=None,
                 offline=False, offline_fixture='decimal-offline.txt'):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('root must be an existing directory')
        if mode not in ('read-only', 'edit'):
            raise ValueError('mode must be read-only or edit')
        self.mode = mode
        self.enabled = set(TOOL_ARGUMENTS if enabled is None else enabled)
        if self.enabled - TOOL_ARGUMENTS.keys():
            raise ValueError('unknown enabled tools: ' + str(self.enabled - TOOL_ARGUMENTS.keys()))
        self.approve = approve or (lambda _command, _cwd: False)
        self.offline = offline
        if offline_fixture not in ('decimal-offline.txt', 'web-injected.txt'):
            raise ValueError('offline fixture must be a supplied fixture')
        self.offline_fixture = offline_fixture

    @property
    def available_tools(self):
        """Tools both enabled and permissible in the selected mode."""
        allowed = READ_TOOLS | (EDIT_TOOLS if self.mode == 'edit' else frozenset())
        return sorted(self.enabled & allowed)

    def execute(self, action):
        """Return {status: ok|error|denied, output: ...}; never execute JSON as code."""
        try:
            if not isinstance(action, dict) or set(action) != {'tool', 'args'}:
                return answer('error', 'action must have exactly tool and args')
            name, args = action['tool'], action['args']
            if not isinstance(name, str) or name not in TOOL_ARGUMENTS:
                return answer('error', 'unknown tool')
            if not isinstance(args, dict) or set(args) != set(TOOL_ARGUMENTS[name]):
                return answer('error', 'missing or unexpected argument names')
            if any(not isinstance(v, str) or len(v) > LIMIT for v in args.values()):
                return answer('error', 'arguments must be strings <= 12000 characters')
            if name not in self.enabled:
                return answer('denied', 'tool disabled by --tools')
            if self.mode == 'read-only' and name in EDIT_TOOLS:
                return answer('denied', 'tool requires edit mode')
            result = getattr(self, '_tool_' + name)(**args)
            # Bash supplies its own exit status, unlike the other tool handlers.
            return result if name == 'bash' else answer('ok', result)
        except Denied as exc:
            return answer('denied', str(exc))
        except (OSError, UnicodeError, ValueError, RuntimeError, TimeoutError) as exc:
            return answer('error', f'{type(exc).__name__}: {exc}')

    def _resolve(self, name, *, writing=False):
        # Check lexically, then canonically: resolve catches symlinks escaping the root.
        if not name or '\\' in name or '\x00' in name or PureWindowsPath(name).is_absolute():
            raise Denied('invalid or absolute path')
        relative = Path(name)
        if relative.is_absolute() or any(p == '..' or p.startswith('.') for p in relative.parts):
            raise Denied('absolute, traversal and hidden paths are forbidden')
        resolved = (self.root / relative).resolve()
        try:
            normalized = resolved.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise Denied('path escapes workspace') from exc
        if any(p.startswith('.') for p in Path(normalized).parts):
            raise Denied('hidden resolved path')
        if writing and normalized in PROTECTED:
            raise Denied('course-owned file is protected')
        return resolved

    def _files(self):
        """Yield up to 200 visible regular files without following symlinks."""
        count = 0
        for current, folders, files in os.walk(self.root, followlinks=False):
            folders[:] = sorted(d for d in folders if not d.startswith('.') and
                                not (Path(current) / d).is_symlink())
            for filename in sorted(files):
                path = Path(current) / filename
                if filename.startswith('.') or path.is_symlink() or not path.is_file():
                    continue
                if count == MAX_FILES:
                    return
                count += 1
                yield path

    def _tool_list_files(self):
        return [p.relative_to(self.root).as_posix() for p in self._files()]

    def _tool_read_file(self, path):
        location = self._resolve(path)
        with location.open('r', encoding='utf-8') as file:
            content = file.read(LIMIT + 1)
        return {'path': location.relative_to(self.root).as_posix(),
                'content': content[:LIMIT], 'truncated': len(content) > LIMIT,
                'source': 'untrusted workspace file'}

    def _tool_search_files(self, query):
        if not query:
            raise ValueError('query must be nonempty')
        matches = []
        for file in self._files():
            with file.open('rb') as stream:
                data = stream.read(LIMIT + 1)
            if b'\0' in data:
                continue
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    matches.append({'path': file.relative_to(self.root).as_posix(),
                                    'line': number, 'excerpt': line[:200]})
                    if len(matches) >= MAX_MATCHES:
                        return matches
        return matches

    def _tool_write_file(self, path, content):
        location = self._resolve(path, writing=True)
        if len(content.encode('utf-8')) > LIMIT:
            raise ValueError('file exceeds byte limit')
        # x mode is exclusive. A symlink or existing file cannot be overwritten.
        with location.open('x', encoding='utf-8') as file:
            file.write(content)
        return {'path': location.relative_to(self.root).as_posix(), 'created': True}

    def _tool_edit_file(self, path, old, new):
        location = self._resolve(path, writing=True)
        if not old:
            raise ValueError('old text must not be empty')
        if location.stat().st_size > LIMIT:
            raise ValueError('existing file exceeds byte limit')
        content = location.read_text(encoding='utf-8')
        if content.count(old) != 1:
            raise ValueError('old text must occur exactly once')
        edited = content.replace(old, new, 1)
        if len(edited.encode('utf-8')) > LIMIT:
            raise ValueError('edited file exceeds byte limit')
        # Resolve checked above; replace content without changing permissions.
        with location.open('w', encoding='utf-8') as file:
            file.write(edited)
        return {'path': location.relative_to(self.root).as_posix(), 'replacements': 1}

    @staticmethod
    def _validate_url(url):
        try:
            parsed = parse.urlsplit(url)
            port = parsed.port  # Accessing this also validates malformed ports.
        except ValueError as exc:
            raise Denied('malformed documentation URL') from exc
        if (parsed.scheme != 'https' or parsed.hostname != 'docs.python.org'
                or port not in (None, 443) or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or '?' in url or '#' in url or not parsed.path.startswith('/')):
            raise Denied('only plain HTTPS docs.python.org URLs are approved')
        return url

    def _tool_fetch_url(self, url):
        self._validate_url(url)
        if self.offline:
            fixture = (self.root.parent / 'fixtures' / self.offline_fixture).resolve()
            # The fixture directory is outside target-service by design.
            text = fixture.read_bytes()
            if len(text) > LIMIT:
                raise ValueError('offline fixture exceeds byte limit')
            return {'url': url, 'content': text.decode('utf-8'),
                    'truncated': False, 'source': 'offline fixture (untrusted data)'}
        opener = request.build_opener(_NoRedirect())
        req = request.Request(url, headers={'User-Agent': 'StudentCodingAgent/1.0',
                                             'Accept': 'text/html, text/plain'})
        try:
            with opener.open(req, timeout=10) as response:
                mime = response.headers.get_content_type()
                if mime not in ('text/plain', 'text/html'):
                    raise ValueError('documentation must be text or HTML')
                data = response.read(LIMIT + 1)
        except error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise Denied('redirects are forbidden') from exc
            raise ValueError(f'HTTP {exc.code}') from exc
        except error.URLError as exc:
            raise ValueError(f'network failure: {exc.reason}') from exc
        return {'url': url, 'content': data[:LIMIT].decode('utf-8', errors='replace'),
                'truncated': len(data) > LIMIT,
                'source': 'live HTTPS documentation (untrusted data)'}

    @staticmethod
    def _kill_process_group(proc):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    def _tool_bash(self, command):
        if not self.approve(command, str(self.root)):
            raise Denied('human did not approve this command')
        # Approval does not sandbox bash. Run with a minimal environment and no stdin.
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/nonexistent',
               'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONIOENCODING': 'utf-8'}
        proc = subprocess.Popen(['/bin/bash', '--noprofile', '--norc', '-c', command],
                                cwd=self.root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=env, start_new_session=True)
        selected = selectors.DefaultSelector()
        output = bytearray()
        started = time.monotonic()
        try:
            selected.register(proc.stdout, selectors.EVENT_READ)
            while selected.get_map():
                if time.monotonic() - started >= 20:
                    self._kill_process_group(proc)
                    return answer('error', {'exit_code': None,
                                            'output': output.decode('utf-8', 'replace'),
                                            'reason': '20-second timeout'})
                for key, _mask in selected.select(timeout=.2):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selected.unregister(key.fileobj)
                        continue
                    output.extend(chunk[:max(0, LIMIT + 1 - len(output))])
                    if len(output) > LIMIT:
                        self._kill_process_group(proc)
                        return answer('error', {'exit_code': None,
                                                'output': output[:LIMIT].decode('utf-8', 'replace'),
                                                'reason': 'output exceeded 12000 bytes'})
            remaining = 20 - (time.monotonic() - started)
            try:
                proc.wait(timeout=max(0.001, remaining))
            except subprocess.TimeoutExpired:
                self._kill_process_group(proc)
                return answer('error', {'exit_code': None,
                                        'output': output.decode('utf-8', 'replace'),
                                        'reason': '20-second timeout'})
            return answer('ok' if proc.returncode == 0 else 'error',
                          {'exit_code': proc.returncode,
                           'output': output.decode('utf-8', 'replace')})
        except BaseException:
            self._kill_process_group(proc)
            raise
        finally:
            selected.close()
            proc.stdout.close()
