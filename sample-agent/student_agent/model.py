"""Local Ollama chat adapter."""

import json
import os
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "300"))
MAX_RESPONSE_BYTES = 1000000
NUM_CTX = int(os.environ.get("NUM_CTX", "16384"))


class OllamaModel:
    """Callable adapter for Ollama's local chat endpoint."""

    def __init__(self, model_name, endpoint=DEFAULT_ENDPOINT, timeout=REQUEST_TIMEOUT):
        self.model_name = model_name
        self.endpoint = endpoint
        self.timeout = timeout

    def __call__(self, messages):
        """Return the model's message content as a JSON string."""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0, "num_predict": 2048, "num_ctx": NUM_CTX},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Ollama returned HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"cannot reach Ollama at {self.endpoint}: {exc.reason}") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Ollama response exceeded the size limit")
        data = json.loads(body)
        if "error" in data:
            raise RuntimeError(str(data["error"]))
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError("Ollama response is missing message.content")
        return content
