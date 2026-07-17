"""DeepSeek API client (optional AI layer).

Purpose
-------
A minimal, dependency-free client for DeepSeek's OpenAI-compatible chat
completions API, used by AI form authoring and the optional enrichment
features (translation, quality review, cross-field constraints, coverage
and indicator matrices, and the advisory suggestion passes).

This is the ONLY place in the codebase that talks to a network service.
Every other module in :mod:`xlsform_studio` remains fully offline and
deterministic; AI features are opt-in and degrade gracefully to "not
available" when no API key is configured, so the tool's default behaviour
(and every existing test) is unaffected.

Inputs
------
* An API key (``DEEPSEEK_API_KEY`` env var by default).
* A system prompt + user prompt requesting a JSON response.

Outputs
-------
The parsed JSON response body (``dict``), or an :class:`AIError` describing
what went wrong (missing key, network failure, malformed response) so
callers can log an assumption and continue without AI enrichment.

Example
-------
>>> client = DeepSeekClient(api_key="")
>>> client.available
False
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..logging_config import get_logger

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 60

_log = get_logger("ai.client")

#: Refuse to send a form larger than this many questions to the AI API.
#: Guards against a pathological input exhausting the request payload,
#: the model's context window, or the API budget on a single call; the
#: deterministic pipeline has no such limit since it doesn't pay per token.
MAX_QUESTIONS_FOR_AI = 2000


class AIError(Exception):
    """Raised when an AI request fails (network, auth, or malformed reply).

    Callers in the AI pipeline catch this and degrade gracefully: the
    deterministic pipeline output is unaffected, and a note is added
    explaining that AI enrichment was skipped for that step.
    """


@dataclass
class DeepSeekClient:
    """Thin, dependency-free wrapper around DeepSeek's chat completions API."""

    #: ``repr=False`` so the default dataclass repr - which a stray
    #: ``print(client)``, log call, or unhandled-exception traceback could
    #: easily surface - never prints the raw key.
    api_key: str = field(
        default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY", ""),
        repr=False)
    base_url: str = field(default_factory=lambda: os.environ.get(
        "XLSFS_DEEPSEEK_BASE_URL", DEFAULT_BASE_URL))
    model: str = field(default_factory=lambda: os.environ.get(
        "XLSFS_DEEPSEEK_MODEL", DEFAULT_MODEL))
    timeout: int = DEFAULT_TIMEOUT

    @property
    def available(self) -> bool:
        """True when an API key is configured (does not verify it is valid)."""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    def complete_json(self, system_prompt: str, user_prompt: str,
                      max_tokens: int = 4000, temperature: float = 0.0) -> Dict[str, Any]:
        """Request a JSON-mode completion and return the parsed object.

        Raises :class:`AIError` on any failure (no key, network error, HTTP
        error, or a response that is not valid JSON) so callers can handle
        it uniformly.
        """
        if not self.available:
            raise AIError("No DeepSeek API key configured "
                          "(set the DEEPSEEK_API_KEY environment variable).")

        # DeepSeek's JSON mode requires the word "json" to appear in the
        # prompt, otherwise generation can misbehave.
        if "json" not in system_prompt.lower() and "json" not in user_prompt.lower():
            system_prompt += "\n\nRespond with a single JSON object."

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Log the request shape, never its content - prompts may embed
        # survey data (potentially sensitive respondent-adjacent context).
        _log.debug("request start: model=%s prompt_chars=%d max_tokens=%d",
                   self.model, len(system_prompt) + len(user_prompt), max_tokens)
        started = time.monotonic()
        try:
            body = self._post("/chat/completions", payload)
        except AIError as exc:
            # exc's message is already scrubbed of the Authorization header
            # by _post; safe to log verbatim.
            _log.warning("request failed after %.2fs: %s",
                        time.monotonic() - started, exc)
            raise
        _log.info("request ok: %.2fs", time.monotonic() - started)

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"Unexpected DeepSeek response shape: {exc}") from exc

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIError(f"DeepSeek did not return valid JSON: {exc}") from exc

    # ------------------------------------------------------------------
    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Perform the HTTP POST. Isolated for easy mocking in tests."""
        url = self.base_url.rstrip("/") + path
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise AIError(f"DeepSeek API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AIError(f"Could not reach DeepSeek API: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AIError(f"DeepSeek API request timed out after {self.timeout}s") from exc


def get_default_client() -> Optional[DeepSeekClient]:
    """Return a client if an API key is configured, else None."""
    client = DeepSeekClient()
    return client if client.available else None
