"""Local Ollama JSON-mode model adapter using only the Python standard library."""

import json
from urllib import error, request


class OllamaModel:
    """Callable adapter returning message.content from the local /api/chat API."""

    def __init__(self, model_name, endpoint='http://127.0.0.1:11434/api/chat'):
        self.model_name = model_name
        self.endpoint = endpoint

    def __call__(self, messages):
        body = json.dumps({
            'model': self.model_name,
            'messages': messages,
            'stream': False,
            'format': 'json',
            'options': {'temperature': 0, 'num_predict': 2048},
        }).encode('utf-8')
        req = request.Request(self.endpoint, data=body, method='POST', headers={
            'Content-Type': 'application/json', 'Accept': 'application/json',
        })
        try:
            with request.urlopen(req, timeout=90) as response:
                data = response.read(64 * 1024 + 1)
        except (error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f'Ollama unavailable at {self.endpoint}: {exc}') from exc
        if len(data) > 64 * 1024:
            raise RuntimeError('Ollama response too large')
        try:
            obj = json.loads(data)
            content = obj['message']['content']
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError('Malformed Ollama response') from exc
        if not isinstance(content, str) or len(content) > 12000:
            raise RuntimeError('Ollama message is not bounded text')
        return content
