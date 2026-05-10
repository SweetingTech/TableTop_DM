"""POI / tile image generation via OpenRouter (or compatible).

Routes through whatever the campaign has in `settings.image_gen.provider`.
Default is OpenRouter, which proxies image-capable models like Google's
Gemini ("Banana") image preview, Flux, etc.

Returns either a remote `https://` URL (preferred when the provider supports
it) or a `data:` URL of the generated PNG bytes. Either format plugs straight
into `state.map_pois.image_url` and the Three.js renderer's TextureLoader.
"""

import base64
import logging
import json
import uuid
from typing import Optional
from urllib import request as urllib_request, error as urllib_error

from shared.db.connection import execute_one


# Defaults if the campaign hasn't configured anything explicit.
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# The image-generation model OpenRouter routes the tool call to.
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image"
# The chat model that *drives* the tool call. OpenRouter's server-tool flow
# requires a host model that supports tool calling — it receives the user
# prompt, decides to invoke the image tool, and embeds the result. Any cheap
# tool-capable chat model works (gpt-4o-mini, claude-haiku, deepseek-chat,
# llama-3-instruct, etc). The actual image cost is on the image model.
DEFAULT_OPENROUTER_HOST_MODEL = "openai/gpt-4o-mini"

# Models known to support OpenRouter's image_generation server tool (Nov 2026).
# Surfaced in the UI as suggestions; not enforced — paste any newer model id.
SUPPORTED_IMAGE_MODELS = [
    "google/gemini-2.5-flash-image",
    "google/gemini-3.1-flash-image-preview",
    "google/gemini-3-pro-image-preview",
    "bytedance-seed/seedream-4.5",
    "openai/gpt-5.4-image-2",
    "openai/gpt-5-image-mini",
    "black-forest-labs/flux.2-pro",
    "sourceful/riverflow-v2-fast",
]


class ImageGenError(Exception):
    pass


def _campaign_image_config(campaign_id: uuid.UUID) -> dict:
    row = execute_one(
        "SELECT * FROM state.campaign_settings WHERE campaign_id = %s",
        (str(campaign_id),),
    )
    settings = (row or {}).get("settings") or {}
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except Exception:
            settings = {}
    image_gen = (settings.get("image_gen") or {})
    api_keys = (settings.get("api_keys") or {})
    provider = (image_gen.get("provider") or "openrouter").lower()

    # Lookup priority: image-specific key > provider key > env fallback.
    api_key = (
        api_keys.get(f"image_{provider}")
        or api_keys.get(provider)
        or _env_key_for(provider)
    )
    return {
        "provider": provider,
        "model": image_gen.get("model") or DEFAULT_IMAGE_MODEL,
        # OpenRouter only — the chat model that drives the server-tool call.
        "host_model": image_gen.get("host_model") or DEFAULT_OPENROUTER_HOST_MODEL,
        "api_key": api_key,
        "base_url": _base_url_for(provider),
    }


def _env_key_for(provider: str) -> Optional[str]:
    import os
    if provider == "openrouter":
        return os.environ.get("OPENROUTER_API_KEY")
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    return None


def _base_url_for(provider: str) -> str:
    return {
        "openrouter": DEFAULT_OPENROUTER_BASE,
        "openai": "https://api.openai.com/v1",
    }.get(provider, DEFAULT_OPENROUTER_BASE)


def generate_poi_image(
    campaign_id: uuid.UUID,
    *,
    name: str,
    kind: str,
    description: Optional[str] = None,
    style_hint: str = "PS1-era pixel art, top-down, isometric, crisp pixels, no antialiasing",
) -> str:
    """Build a prompt from the POI metadata, call the configured provider,
    return the resulting image URL or data URL.

    Raises ImageGenError on any failure with a descriptive message.
    """
    cfg = _campaign_image_config(campaign_id)
    if not cfg["api_key"]:
        raise ImageGenError(
            f"No API key configured for image provider '{cfg['provider']}'. "
            "Add one in Control Plane → AI Settings → Image Generation."
        )

    prompt = _build_prompt(name=name, kind=kind, description=description, style=style_hint)

    if cfg["provider"] == "openrouter":
        return _call_openrouter_image(cfg, prompt)
    if cfg["provider"] == "openai":
        return _call_openai_image(cfg, prompt)
    raise ImageGenError(f"Unsupported image provider: {cfg['provider']}")


def _build_prompt(*, name: str, kind: str, description: Optional[str], style: str) -> str:
    kind_hint = {
        "BUILDING": "small top-down view of a single building",
        "NPC":      "single character portrait",
        "SIGN":     "wooden signpost",
        "HAZARD":   "ominous warning marker",
        "TREASURE": "treasure pile or shiny item",
        "PORTAL":   "magical portal",
        "GENERIC":  "generic landmark icon",
    }.get(kind.upper(), "single object icon")
    parts = [f"{kind_hint}: {name}"]
    if description:
        parts.append(description)
    parts.append(style)
    return ". ".join(parts)


def _call_openrouter_image(cfg: dict, prompt: str) -> str:
    """Generate an image via OpenRouter's `openrouter:image_generation`
    server tool. The flow is:

      1. We send a chat-completion request to a HOST chat model (cfg["host_model"])
         with the user prompt + the image-generation tool declared.
      2. The host model decides to call the tool with a refined prompt.
      3. OpenRouter executes the image gen using cfg["model"] (the image-only
         model — e.g. google/gemini-2.5-flash-image) and returns the URL to
         the host model.
      4. The host model embeds the image in its final response.

    Cost = host model tokens + image model invocation.

    Reference: https://openrouter.ai/docs/features/server-tools/image-generation
    """
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": cfg["host_model"],
        "messages": [{"role": "user", "content": f"Please generate this image: {prompt}"}],
        "tools": [{
            "type": "openrouter:image_generation",
            "parameters": {
                "model": cfg["model"],
                "output_format": "png",
            },
        }],
    }).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/SweetingTech/TableTop_DM",
            "X-Title": "TableTop DM",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        logging.error("openrouter image gen %d: %s", e.code, err_body)
        raise ImageGenError(f"OpenRouter HTTP {e.code}: {err_body[:400]}")
    except Exception as e:
        raise ImageGenError(f"OpenRouter request failed: {e}")

    return _extract_image_url(payload)


def _extract_image_url(payload: dict) -> str:
    """OpenRouter's server-tool response can carry the image URL in several
    shapes depending on how the host model formats its reply. Try them all.
    """
    # 1. Direct `images` array on the assistant message (Gemini-style)
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    for img in (message.get("images") or []):
        u = (img.get("image_url") or {}).get("url") if isinstance(img, dict) else None
        if u:
            return u

    # 2. content[].type == "image_url" (multimodal content array)
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                u = (part.get("image_url") or {}).get("url")
                if u:
                    return u

    # 3. Tool-call result with status=ok / imageUrl (the raw tool response
    #    bubbling up if the host model doesn't reformat).
    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        # OpenAI-style tool_call: {"function": {"arguments": "..."}}; here the
        # tool *result* (not the call) might appear in a separate tool message.
        if isinstance(tc, dict):
            func = tc.get("function") or {}
            args = func.get("arguments")
            if isinstance(args, str):
                try:
                    a = json.loads(args)
                    if a.get("imageUrl"):
                        return a["imageUrl"]
                except Exception:
                    pass
    # Server-tool result message style — OpenRouter may include it in choices
    # as a separate tool-role message.
    for c in (payload.get("choices") or []):
        m = c.get("message") or {}
        if m.get("role") == "tool":
            try:
                tr = json.loads(m.get("content") or "{}")
                if tr.get("imageUrl"):
                    return tr["imageUrl"]
                if tr.get("status") == "error":
                    raise ImageGenError(f"Image tool error: {tr.get('error', 'unknown')}")
            except json.JSONDecodeError:
                pass

    # 4. Markdown image syntax in plain content
    if isinstance(content, str):
        import re
        m = re.search(r"!\[[^\]]*\]\((https?://[^)\s]+|data:image/[^)\s]+)\)", content)
        if m:
            return m.group(1)

    raise ImageGenError(
        "OpenRouter response had no image data. The host model may not have "
        "invoked the image tool (try a model that supports tools, like "
        "openai/gpt-5.2 or anthropic/claude-sonnet-4)."
    )


def _call_openai_image(cfg: dict, prompt: str) -> str:
    """OpenAI Images API returns base64-encoded PNG bytes. We wrap as data URL."""
    url = cfg["base_url"].rstrip("/") + "/images/generations"
    body = json.dumps({
        "model": cfg["model"],
        "prompt": prompt,
        "size": "1024x1024",
        "response_format": "b64_json",
    }).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise ImageGenError(f"OpenAI HTTP {e.code}: {err_body[:300]}")
    except Exception as e:
        raise ImageGenError(f"OpenAI request failed: {e}")

    b64 = ((payload.get("data") or [{}])[0]).get("b64_json")
    if not b64:
        raise ImageGenError("OpenAI response had no image data")
    return f"data:image/png;base64,{b64}"
