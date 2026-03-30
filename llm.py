"""
GibberLink Revisited — LLM Provider Adapters

Unified interface for calling LLMs across OpenRouter, Anthropic, Gemini,
OpenAI, and xAI Grok. Includes error classification and retry logic.
"""

import re
import asyncio

import httpx


# ── Error hierarchy ─────────────────────────────────────────

class LLMError(RuntimeError):
    """Base class for LLM API errors."""
    pass

class LLMRetryableError(LLMError):
    """Transient errors worth retrying: rate limits, timeouts, server errors."""
    pass

class LLMFatalError(LLMError):
    """Permanent errors that will never succeed on retry: bad key, model not found, quota."""
    pass


# ── Error classification ────────────────────────────────────

def _classify_llm_error(status_code: int | None, error_body: str) -> LLMError:
    """Inspect an HTTP status code and error body to return the right exception type."""
    body_lower = error_body.lower() if error_body else ""

    # Fatal (never retry)
    if status_code == 401 or "unauthorized" in body_lower or "authentication" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if status_code == 403 or "forbidden" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if status_code == 404 or "not found" in body_lower or "model_not_found" in body_lower or "does not exist" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if "quota" in body_lower or "billing" in body_lower or "insufficient" in body_lower or "payment" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if "content_filter" in body_lower or "safety" in body_lower or "blocked" in body_lower or "moderation" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")

    # Retryable
    if status_code == 429 or "rate_limit" in body_lower or "too many requests" in body_lower:
        return LLMRetryableError(f"[{status_code}] {error_body}")
    if status_code and status_code >= 500:
        return LLMRetryableError(f"[{status_code}] {error_body}")
    if "timeout" in body_lower or "timed out" in body_lower:
        return LLMRetryableError(f"[{status_code}] {error_body}")

    # Default: treat unknown errors as retryable (safer)
    return LLMRetryableError(f"[{status_code}] {error_body}")


# ── Human-readable error messages ───────────────────────────

def friendly_error(exc: Exception) -> str:
    """Convert raw LLM/TTS exceptions into user-friendly messages."""
    msg = str(exc)
    ml = msg.lower()

    if "rate_limit" in ml or "429" in ml or "too many requests" in ml:
        return "Rate limited by the API provider. Wait a moment and try again, or switch to a different model."
    if "401" in ml or "unauthorized" in ml or "authentication" in ml:
        return "API key is invalid or expired. Re-run `python3 setup.py` to reconfigure."
    if "404" in ml or "not found" in ml or "does not exist" in ml or "model_not_found" in ml:
        return "Model not found — it may have been removed or renamed. Re-run `python3 setup.py` to pick a new model."
    if "quota" in ml or "billing" in ml or "insufficient" in ml or "payment" in ml:
        return "API quota exhausted or billing issue. Check your account balance, or switch to a free model on OpenRouter."
    if "timeout" in ml or "timed out" in ml:
        return "The API took too long to respond. The provider may be overloaded — try again or switch models."
    if ("context" in ml and "length" in ml) or "too long" in ml or ("token" in ml and "limit" in ml):
        return "The conversation exceeded the model's context window. Try using fewer turns or a model with a larger context."
    if "content_filter" in ml or "safety" in ml or "blocked" in ml or "moderation" in ml:
        return "The model's content filter blocked the response. Try rephrasing the topic."
    if "connect" in ml and ("refused" in ml or "error" in ml):
        return "Could not connect to the API provider. Check your internet connection."
    if "empty" in ml and "response" in ml:
        return "The model returned an empty response. This sometimes happens with free models — try again."

    # Fallback: truncate raw message but keep it somewhat readable
    clean = msg.replace("RuntimeError: ", "").replace("API error: ", "")
    if len(clean) > 200:
        clean = clean[:200] + "..."
    return f"LLM error: {clean}"


# ── Provider-specific calls ─────────────────────────────────

OPENAI_COMPAT_URLS = {
    "openrouter":   "https://openrouter.ai/api/v1/chat/completions",
    "openai":       "https://api.openai.com/v1/chat/completions",
    "grok":         "https://api.x.ai/v1/chat/completions",
    "opencode_zen": "https://opencode.ai/zen/v1/chat/completions",
}


async def _call_anthropic(api_key, model, messages, system_prompt, max_tokens, client):
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "system": system_prompt, "messages": messages},
    )
    data = resp.json()
    if "error" in data:
        raise _classify_llm_error(resp.status_code, f"Anthropic: {data['error']}")
    content = data["content"][0]["text"] if data.get("content") else None
    if content is None:
        raise LLMRetryableError("Anthropic returned empty response")
    return content


async def _call_openai_compat(api_key, model, url, messages, system_prompt, max_tokens, client):
    resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system_prompt}] + messages},
    )
    data = resp.json()
    if "error" in data:
        raise _classify_llm_error(resp.status_code, f"API error: {data['error']}")
    content = data["choices"][0]["message"]["content"]
    if content is None:
        raise LLMRetryableError("Model returned empty response (content is null)")
    return content


async def _call_gemini(api_key, model, messages, system_prompt, max_tokens, client):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in messages]
    resp = await client.post(url, headers={"content-type": "application/json"}, json={
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents, "generationConfig": {"maxOutputTokens": max_tokens},
    })
    data = resp.json()
    if "error" in data:
        raise _classify_llm_error(resp.status_code, f"Gemini: {data['error'].get('message', data['error'])}")
    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise LLMRetryableError("Gemini returned empty or malformed response")
    if content is None:
        raise LLMRetryableError("Gemini returned null content")
    return content


# ── Unified call with retry ─────────────────────────────────

async def call_llm(provider, api_key, model, messages, system_prompt,
                   retries=3, max_tokens=200, client: httpx.AsyncClient | None = None):
    """Call an LLM with automatic retry for transient errors.

    Raises LLMFatalError immediately for auth/quota/model errors.
    Retries with exponential backoff for rate limits, timeouts, and 5xx.
    """
    if client is None:
        raise ValueError("An httpx.AsyncClient must be provided")

    last_err = None
    for attempt in range(retries):
        try:
            if provider == "anthropic":
                return await _call_anthropic(api_key, model, messages, system_prompt, max_tokens, client)
            elif provider == "gemini":
                return await _call_gemini(api_key, model, messages, system_prompt, max_tokens, client)
            else:
                url = OPENAI_COMPAT_URLS.get(provider, OPENAI_COMPAT_URLS["openrouter"])
                return await _call_openai_compat(api_key, model, url, messages, system_prompt, max_tokens, client)
        except LLMFatalError:
            raise
        except (LLMRetryableError, httpx.TimeoutException, httpx.ConnectError) as e:
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  [LLM] Attempt {attempt+1} failed (retryable): {e} — retrying in {wait}s")
                await asyncio.sleep(wait)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  [LLM] Attempt {attempt+1} failed: {e} — retrying in {wait}s")
                await asyncio.sleep(wait)
    raise last_err
