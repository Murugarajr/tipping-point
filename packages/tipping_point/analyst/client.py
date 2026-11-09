"""OpenAI-compatible Chat Completions adapter for the Rescue Analyst (httpx, no SDK).

Verified official contract references (checked 2026-11-09):
- OpenAI Chat Completions: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
  POST {base}/chat/completions, Bearer auth, `tools` [{type: "function", function: {name, description,
  parameters}}], `tool_choice`, `max_completion_tokens` (`max_tokens` deprecated),
  choices[].message.tool_calls[{id, type: "function", function: {name, arguments: JSON string}}],
  finish_reason in stop|length|tool_calls|content_filter, tool results as {role: "tool", tool_call_id,
  content}. The response `model` may be a dated snapshot of the requested model.
- OpenRouter tool calling: https://openrouter.ai/docs/guides/features/tool-calling (same message shapes;
  `tools` must be sent on every request), API overview: https://openrouter.ai/docs/api/reference/overview
  (`max_tokens`; finish_reason also `error`), errors: https://openrouter.ai/docs/api/reference/errors-and-debugging
  (a 200 body may carry only an `error` object), provider routing:
  https://openrouter.ai/docs/guides/routing/provider-selection (`provider.require_parameters` routes only to
  providers that support every request parameter, including `tools`), models:
  https://openrouter.ai/docs/api/api-reference/models/get-models (authenticated; `supported_parameters`).

Model identity policy (explicit, fail-closed; never prefix or pattern matching):
- OpenRouter: the configured model must exactly equal an `id` in the authenticated models listing filtered to
  `supported_parameters=tools`. A response is accepted only if its `model` equals that entry's `id` or the
  `canonical_slug` the same listing entry reports. Anything else is MODEL_MISMATCH.
- OpenAI: exact string equality between the configured model and the response `model`. OpenAI's API exposes no
  alias-resolution data to verify against, so configure the exact id OpenAI reports (e.g. a dated snapshot);
  an alias that resolves to a differently named model fails closed.

Routing: one selected model through OpenRouter; no application-level model or API-provider fallback. OpenRouter may
still route that same model among its infrastructure providers; `provider.require_parameters` limits this to
providers supporting every request parameter (including `tools`) but does not pin a single provider.

Request parameters are deliberately minimal (model, messages, tools, tool_choice, token cap, provider). Under `require_parameters`, every optional
parameter must be listed by at least one endpoint of the model, or OpenRouter answers 404 with no endpoint to
route to. `parallel_tool_calls` is not sent: on 2026-11-09 no `openai/gpt-4.1-mini` endpoint listed it
(GET /api/v1/models/openai/gpt-4.1-mini/endpoints), which made every analyst request fail with 404.

Destinations are server-owned presets. Nothing here accepts a base URL, key, header or model from a browser.
Errors are sanitised: provider bodies, keys and transport details never leave this module.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

ProviderName = Literal["openrouter", "openai"]


@dataclass(frozen=True)
class ProviderPreset:
    name: ProviderName
    label: str
    base_url: str
    token_param: str


PROVIDERS: dict[str, ProviderPreset] = {
    "openrouter": ProviderPreset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "max_tokens"),
    "openai": ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", "max_completion_tokens"),
}

APP_TITLE = "Tipping Point Rescue Analyst"
MODEL_CHECK_TTL_SECONDS = 3600


class AnalystProviderError(RuntimeError):
    """Base sanitised provider failure. `code` is safe to show; the message never carries provider text."""

    code = "PROVIDER_ERROR"
    status = 502
    message = "The analyst model provider returned an error. Nothing was changed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class AnalystConfigError(AnalystProviderError):
    code = "ANALYST_NOT_CONFIGURED"
    status = 503
    message = "The analyst is not configured on the server."


class ProviderAuthError(AnalystProviderError):
    code = "PROVIDER_AUTH"
    status = 502
    message = "The analyst provider rejected the server's credentials or account. An operator must check the configuration."


class ProviderRateLimitError(AnalystProviderError):
    code = "PROVIDER_RATE_LIMITED"
    status = 429
    message = "The analyst provider is rate limiting requests. Try again shortly."


class ProviderTimeoutError(AnalystProviderError):
    code = "PROVIDER_TIMEOUT"
    status = 504
    message = "The analyst provider did not answer in time. Nothing was changed."


class ProviderResponseError(AnalystProviderError):
    code = "PROVIDER_BAD_RESPONSE"
    status = 502
    message = "The analyst provider returned a response the server could not use. Nothing was changed."


class ModelUnsupportedError(AnalystProviderError):
    code = "MODEL_UNSUPPORTED"
    status = 503
    message = "The configured analyst model is not available with tool calling on this provider."


class NoCompatibleEndpointError(AnalystProviderError):
    """OpenRouter 404 on chat/completions after the model passed the tools listing check: no endpoint of the
    selected model accepts every request parameter (or the account's routing/data policy excludes them all)."""

    code = "PROVIDER_NO_ENDPOINT"
    status = 503
    message = "No provider endpoint for the configured model currently accepts this request. Nothing was changed."


class ModelMismatchError(AnalystProviderError):
    code = "MODEL_MISMATCH"
    status = 502
    message = "The provider reported a model that is not the configured model or its verified canonical id; the answer was discarded."


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Completion:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    model: str
    usage: dict[str, int]


# (provider, configured model) -> (checked_at, accepted response model ids from the provider's own listing)
_model_checks: dict[tuple[str, str], tuple[float, frozenset[str]]] = {}
_model_checks_lock = threading.Lock()


class ChatCompletionsClient:
    """One fixed provider + model per client; no fallback to another provider or model."""

    def __init__(
        self,
        *,
        provider: ProviderName,
        api_key: str | None,
        model: str | None,
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 700,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if provider not in PROVIDERS:
            raise AnalystConfigError()
        self.preset = PROVIDERS[provider]
        self._api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self._transport = transport
        # Until verified against the provider's listing, only the exact configured id is accepted.
        self._accepted_models: frozenset[str] = frozenset({self.model}) if self.model else frozenset()

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self.model)

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if self.preset.name == "openrouter":
            headers["X-OpenRouter-Title"] = APP_TITLE
        return httpx.Client(
            base_url=self.preset.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout_seconds),
            transport=self._transport,
            follow_redirects=False,
        )

    def _send(self, method: str, path: str, *, payload: dict | None = None, params: dict | None = None) -> Any:
        if not self.configured:
            raise AnalystConfigError()
        try:
            with self._client() as client:
                response = client.request(method, path, json=payload, params=params)
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.HTTPError:
            raise AnalystProviderError() from None
        if response.status_code in (401, 402, 403):
            raise ProviderAuthError()
        if response.status_code == 429:
            raise ProviderRateLimitError()
        if response.status_code in (408, 504):
            raise ProviderTimeoutError()
        if response.status_code == 404 and path == "/chat/completions":
            # OpenRouter already verified the model is listed with tools, so a 404 here means routing found no
            # endpoint; on OpenAI a 404 means the model id is unknown to this account.
            raise NoCompatibleEndpointError() if self.preset.name == "openrouter" else ModelUnsupportedError()
        if response.status_code >= 400:
            raise AnalystProviderError()
        try:
            body = response.json()
        except ValueError:
            raise ProviderResponseError() from None
        if not isinstance(body, dict):
            raise ProviderResponseError()
        if body.get("error"):
            # OpenRouter can report failures inside an HTTP 200 body.
            raise AnalystProviderError()
        return body

    @property
    def accepted_models(self) -> frozenset[str]:
        return self._accepted_models

    def ensure_model_supports_tools(self) -> None:
        """OpenRouter: verify the exact configured id is listed with `tools`, and record the accepted ids.

        The accepted set is the listing entry's own `id` and `canonical_slug`; nothing is inferred from names.
        OpenAI publishes no tool-capability or alias data in a form this adapter can verify, so OpenAI keeps
        exact equality and an unsupported model surfaces as a sanitised provider error. Cached per process.
        """
        if self.preset.name != "openrouter":
            return
        key = (self.preset.name, self.model)
        now = time.monotonic()
        with _model_checks_lock:
            cached = _model_checks.get(key)
            if cached is not None and now - cached[0] < MODEL_CHECK_TTL_SECONDS:
                self._accepted_models = cached[1]
                return
        body = self._send("GET", "/models", params={"supported_parameters": "tools"})
        data = body.get("data")
        if not isinstance(data, list):
            raise ProviderResponseError()
        listed = next((m for m in data if isinstance(m, dict) and m.get("id") == self.model), None)
        if listed is None or "tools" not in (listed.get("supported_parameters") or []):
            raise ModelUnsupportedError()
        accepted = {self.model}
        canonical = listed.get("canonical_slug")
        if isinstance(canonical, str) and canonical.strip():
            accepted.add(canonical.strip())
        self._accepted_models = frozenset(accepted)
        with _model_checks_lock:
            _model_checks[key] = (now, self._accepted_models)

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            self.preset.token_param: self.max_output_tokens,
        }
        if self.preset.name == "openrouter":
            # One selected model; no `models` fallback list is ever sent. OpenRouter may still route this
            # model among its infrastructure providers; require_parameters limits routing to providers that
            # support every request parameter (notably `tools`) but does not pin a single provider.
            payload["provider"] = {"require_parameters": True}
        body = self._send("POST", "/chat/completions", payload=payload)
        return self._parse(body)

    def _parse(self, body: dict) -> Completion:
        answered = body.get("model")
        if not isinstance(answered, str) or answered not in self._accepted_models:
            raise ModelMismatchError()
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderResponseError()
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish == "error":
            raise AnalystProviderError()
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderResponseError()
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ProviderResponseError()
        calls: list[ToolCall] = []
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise ProviderResponseError()
        for raw in raw_calls:
            function = raw.get("function") if isinstance(raw, dict) else None
            if (
                not isinstance(raw, dict) or raw.get("type", "function") != "function" or not isinstance(function, dict)
                or not isinstance(raw.get("id"), str) or not raw["id"] or len(raw["id"]) > 200
                or not isinstance(function.get("name"), str) or not isinstance(function.get("arguments", ""), str)
            ):
                raise ProviderResponseError()
            calls.append(ToolCall(id=raw["id"], name=function["name"][:100], arguments=function.get("arguments") or "{}"))
        usage_raw = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        usage = {k: int(v) for k, v in usage_raw.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, int)}
        return Completion(content=content, tool_calls=calls, finish_reason=str(finish or ""), model=answered, usage=usage)


def parse_arguments(raw: str) -> dict:
    """Tool arguments are a JSON object string; anything else is rejected (never evaluated)."""
    if len(raw) > 2000:
        raise ValueError("arguments too long")
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("arguments must be a JSON object")
    return value
