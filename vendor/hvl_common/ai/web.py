"""
Live Web Grounding, SSRF-Safe URL Page Fetching, and Tool Annotation Utilities for HVL AI Applications.
Combines direct HTTP HTML snapshot extraction with Gemini UrlContext + GoogleSearch fallback.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import re
import typing
import urllib.parse
from typing import Any, Optional, Sequence
import requests

logger = logging.getLogger("hvl_common.ai.web")

_BLOCKED_HOSTS = {"localhost", "0.0.0.0", "127.0.0.1", "::1", "metadata.google.internal"}


def resolve_callable_tool_annotations(tools: Optional[Sequence[Any]]) -> list[Any]:
    """Resolves stringified PEP 563 (`from __future__ import annotations`) type hints on callable tools for google-genai AFC."""
    if not tools:
        return []
    resolved: list[Any] = []
    for tool in tools:
        if callable(tool) and hasattr(tool, "__annotations__"):
            try:
                hints = typing.get_type_hints(tool)
                if hints:
                    tool.__annotations__ = hints
            except Exception:
                pass
        resolved.append(tool)
    return resolved


def prepare_model_call_config(model_id: str, call_config: Any) -> Any:
    """Strips unsupported native `tools` config when cascading to Gemma models (which return 500/MALFORMED_FUNCTION_CALL with tools)."""
    if call_config is None or not model_id.lower().startswith("gemma") or not getattr(call_config, "tools", None):
        return call_config
    from google.genai import types
    sys_inst = re.sub(r"(?:Live Web & URL Browsing:|Connected Tools:).*?\n", "", str(getattr(call_config, "system_instruction", "") or ""), flags=re.S).strip()
    sys_inst = (sys_inst + "\nAnswer directly in helpful Markdown (including clickable [Title](https://...) links when asked). Do NOT emit tool or function calls.").strip()
    return types.GenerateContentConfig(
        temperature=getattr(call_config, "temperature", None),
        system_instruction=sys_inst or None,
    )


def finalize_model_response(
    ai_client: Any, model_id: str, p_model: str, idx: int, contents: Any, call_config: Any, response: Any
) -> Any:
    """Executes manual tool-call synthesis or retries on empty/MALFORMED_FUNCTION_CALL responses, and attaches model_used metadata."""
    fcs = getattr(response, "function_calls", None) or []
    raw_tools = getattr(call_config, "tools", None) if call_config is not None else None
    text_val = (getattr(response, "text", None) or "").strip()
    if fcs and raw_tools and not text_val:
        tool_map = {getattr(fn, "__name__", ""): fn for fn in raw_tools if callable(fn)}
        tool_outputs: list[str] = []
        for fc in fcs[:3]:
            fn = tool_map.get(getattr(fc, "name", ""))
            if fn:
                try:
                    tool_outputs.append(f"[Tool {fc.name} result]: {fn(**dict(getattr(fc, 'args', None) or {}))}")
                except Exception as exc:
                    tool_outputs.append(f"[Tool {fc.name} error]: {exc}")
        if tool_outputs:
            from google.genai import types
            sys_inst = re.sub(r"(?:Live Web & URL Browsing:|Connected Tools:).*?\n", "", str(getattr(call_config, "system_instruction", "") or ""), flags=re.S)
            sys_inst = (sys_inst + "\nAnswer in natural Markdown using the tool results below. Do NOT emit function calls.").strip()
            follow_contents = list(contents) if isinstance(contents, list) else [{"role": "user", "parts": [{"text": str(contents)}]}]
            last_parts = list((follow_contents[-1].get("parts") if isinstance(follow_contents[-1], dict) else None) or [])
            non_text_parts = [p for p in last_parts if not (isinstance(p, dict) and "text" in p)]
            base_text = "\n".join(str(p["text"]) for p in last_parts if isinstance(p, dict) and "text" in p)
            combined_text = (f"{base_text}\n\n" if base_text else "") + "\n".join(tool_outputs)
            follow_contents[-1] = {
                "role": "user",
                "parts": non_text_parts + [{"text": combined_text}],
            }
            response = ai_client.models.generate_content(
                model=model_id,
                contents=follow_contents,
                config=types.GenerateContentConfig(temperature=getattr(call_config, "temperature", None), system_instruction=sys_inst),
            )
            text_val = (getattr(response, "text", None) or "").strip()
    if not text_val:
        from google.genai import types
        sys_inst = re.sub(r"(?:Live Web & URL Browsing:|Connected Tools:).*?\n", "", str(getattr(call_config, "system_instruction", "") or ""), flags=re.S)
        sys_inst = (sys_inst + "\nRespond directly in plain Markdown text with helpful details and links. Do NOT call any tools or functions.").strip()
        response = ai_client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(temperature=getattr(call_config, "temperature", None), system_instruction=sys_inst),
        )
    is_fb = model_id != p_model or idx > 0
    for attr, val in (("model_used", model_id), ("fallback_occurred", is_fb)):
        try:
            setattr(response, attr, val)
        except Exception:
            try:
                response.__dict__[attr] = val
            except Exception:
                pass
    return response


def normalize_public_url(raw_url: str) -> tuple[Optional[str], Optional[str]]:
    """Normalizes a user-supplied URL or bare domain and enforces SSRF safety against private/local hosts."""
    clean = (raw_url or "").strip().strip("<>\"'()[]{}").rstrip(".,?!")
    if not clean:
        return None, "URL cannot be empty."
    if "://" not in clean:
        clean = f"https://{clean}"

    try:
        parsed = urllib.parse.urlparse(clean)
    except Exception:
        return None, f"Invalid URL: {raw_url}"

    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None, f"Unsupported URL scheme or missing host: {raw_url}"

    host = parsed.hostname.strip().lower()
    if host in _BLOCKED_HOSTS or host.endswith((".local", ".internal", ".localhost")):
        return None, f"Access to local/internal host '{host}' is restricted."

    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
            return None, f"Access to private/reserved IP '{host}' is restricted."
    except ValueError:
        pass

    return parsed.geturl(), None


def _extract_html_metadata_and_text(raw_html: str, max_chars: int = 5000) -> tuple[str, str, str]:
    """Extracts <title>, meta description, and readable visible text from raw HTML."""
    if not raw_html:
        return "", "", ""

    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.I | re.S)
    title = html.unescape(re.sub(r"\s+", " ", title_m.group(1)).strip()) if title_m else ""

    desc = ""
    for pat in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ):
        if dm := re.search(pat, raw_html, flags=re.I | re.S):
            desc = html.unescape(re.sub(r"\s+", " ", dm.group(1)).strip())
            if desc:
                break

    cleaned = re.sub(r"<!--.*?-->", " ", raw_html, flags=re.S)
    cleaned = re.sub(r"<(?:script|style|svg|noscript|iframe|template)\b[^>]*>.*?</(?:script|style|svg|noscript|iframe|template)>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"</?(?:p|div|section|article|header|footer|main|aside|nav|h[1-6]|li|tr|br|hr)\b[^>]*>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in cleaned.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].rstrip() + "..."
    return title, desc, text


def fetch_direct_page_snapshot(url: str, timeout: int = 6, max_chars: int = 5000) -> dict[str, Any]:
    """Performs an SSRF-safe HTTP GET to extract live page title, description, and visible text."""
    norm_url, err = normalize_public_url(url)
    if err or not norm_url:
        return {"ok": False, "url": url, "final_url": url, "status_code": 0, "title": "", "description": "", "text": "", "error": err or "Invalid URL"}

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) HVLAssistant/1.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.get(norm_url, headers=headers, timeout=timeout, allow_redirects=True)
        final_norm, final_err = normalize_public_url(resp.url or norm_url)
        if final_err:
            return {"ok": False, "url": norm_url, "final_url": resp.url, "status_code": 0, "title": "", "description": "", "text": "", "error": final_err}
        ctype = (resp.headers.get("Content-Type") or "").lower()
        raw_body = resp.text or ""
        if "json" in ctype or "text/plain" in ctype:
            title, desc, text = "", "", raw_body[:max_chars].strip()
        else:
            title, desc, text = _extract_html_metadata_and_text(raw_body, max_chars=max_chars)
        return {
            "ok": resp.status_code < 400,
            "url": norm_url,
            "final_url": final_norm or norm_url,
            "status_code": resp.status_code,
            "title": title,
            "description": desc,
            "text": text,
        }
    except Exception as exc:
        return {"ok": False, "url": norm_url, "final_url": norm_url, "status_code": 0, "title": "", "description": "", "text": "", "error": str(exc)}


def extract_grounding_sources(response: Any) -> list[dict[str, str]]:
    """Extracts deduplicated web grounding citation sources from a Gemini response."""
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    candidates = getattr(response, "candidates", None) or (response.get("candidates") if isinstance(response, dict) else None) or []
    if candidates:
        cand = candidates[0]
        g_meta = getattr(cand, "grounding_metadata", None) or (cand.get("grounding_metadata") if isinstance(cand, dict) else None)
        for chunk in getattr(g_meta, "grounding_chunks", None) or (g_meta.get("grounding_chunks") if isinstance(g_meta, dict) else None) or []:
            web = getattr(chunk, "web", None) or (chunk.get("web") if isinstance(chunk, dict) else None)
            if not web:
                continue
            uri = (getattr(web, "uri", None) or (web.get("uri") if isinstance(web, dict) else None) or "").strip()
            title = (getattr(web, "title", None) or (web.get("title") if isinstance(web, dict) else None) or uri).strip()
            if uri and uri not in seen_urls:
                seen_urls.add(uri)
                sources.append({"title": title, "url": uri})
    return sources


def fetch_live_web_search(query: str, max_results: int = 5, timeout: int = 5) -> dict[str, Any]:
    """Fallback live web search via DuckDuckGo Lite HTML when Gemini Search Grounding quota is 0/0."""
    clean_q = (query or "").strip()
    if not clean_q:
        return {"success": False, "query": query, "answer": "", "sources": [], "formatted_reply": "Web search unavailable: Query cannot be empty.", "error": "Query cannot be empty."}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.post("https://lite.duckduckgo.com/lite/", data={"q": clean_q}, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return {"success": False, "query": query, "answer": "", "sources": [], "formatted_reply": f"Web search HTTP {resp.status_code}", "error": f"HTTP {resp.status_code}"}
        body = resp.text or ""
        links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]+class=["\']result-link["\'][^>]*>(.*?)</a>', body, re.I | re.S)
        if not links:
            links = re.findall(r'<a[^>]+class=["\']result-link["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.I | re.S)
        snippets = re.findall(r'<td[^>]+class=["\']result-snippet["\'][^>]*>(.*?)</td>', body, re.I | re.S)
        sources: list[dict[str, str]] = []
        bullets: list[str] = []
        for idx, (raw_url, raw_title) in enumerate(links[:max_results]):
            title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            snippet = html.unescape(re.sub(r"<[^>]+>", "", snippets[idx])).strip() if idx < len(snippets) else ""
            snippet = re.sub(r"\s+", " ", snippet)
            url = html.unescape(raw_url).strip()
            if url and title:
                sources.append({"title": title, "url": url})
                bullets.append(f"- **{title}** ({url}): {snippet}" if snippet else f"- **{title}** ({url})")
        if not sources:
            return {"success": False, "query": query, "answer": "", "sources": [], "formatted_reply": f"No live web results found for '{clean_q}'.", "error": "No results"}
        answer = f"Live web results for '{clean_q}':\n" + "\n".join(bullets)
        sources_text = "\n".join(f"- [{s['title']}]({s['url']})" for s in sources[:5])
        formatted = f"{answer}\n\nSources:\n{sources_text}"
        return {"success": True, "query": query, "answer": answer, "sources": sources, "formatted_reply": formatted, "model_used": "live-web-fallback"}
    except Exception as exc:
        return {"success": False, "query": query, "answer": "", "sources": [], "formatted_reply": f"Web search unavailable: {exc}", "error": str(exc)}


def fetch_web_page_grounded(
    url: str,
    question: str = "",
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
    primary_model: str = "gemini-3.5-flash-lite",
    fallback_models: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Fetches a live URL using SSRF-safe HTTP snapshot extraction with Gemini UrlContext/GoogleSearch fallback."""
    from hvl_common.ai.gemini import generate_content_with_fallback

    norm_url, err = normalize_public_url(url)
    if err or not norm_url:
        msg = err or "URL cannot be empty."
        return {"success": False, "url": url, "answer": "", "sources": [], "formatted_reply": f"Web page fetch unavailable: {msg}", "error": msg}

    snap = fetch_direct_page_snapshot(norm_url)
    if snap.get("error") and "restricted" in str(snap.get("error")).lower():
        msg = str(snap["error"])
        return {"success": False, "url": norm_url, "answer": "", "sources": [], "formatted_reply": f"Web page fetch unavailable: {msg}", "error": msg}

    # Fast path: when direct HTTP fetch succeeded with readable content and no custom LLM client override was passed
    if snap.get("ok") and (snap.get("title") or snap.get("text")) and client is None:
        final_u = snap.get("final_url") or norm_url
        parts = [f"URL: {final_u}"]
        if snap.get("title"):
            parts.append(f"Title: {snap['title']}")
        if snap.get("description"):
            parts.append(f"Description: {snap['description']}")
        if snap.get("text"):
            parts.append(f"Page Content:\n{snap['text']}")
        formatted = "\n".join(parts)
        return {
            "success": True, "url": norm_url, "final_url": final_u,
            "title": snap.get("title", ""), "answer": formatted,
            "sources": [{"title": snap.get("title") or norm_url, "url": final_u}],
            "formatted_reply": formatted, "model_used": "http-snapshot",
        }

    user_q = (question or "").strip() or f"Describe what is on {norm_url} and summarize its content."
    prompt = f"{user_q}\nTarget URL: {norm_url}"
    if snap.get("title") or snap.get("text"):
        prompt += f"\nTitle: {snap.get('title', '')}\nContent:\n{snap.get('text', '')}"

    try:
        from google.genai import types

        config = types.GenerateContentConfig(
            tools=[types.Tool(url_context=types.UrlContext()), types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
            system_instruction="Inspect the target URL and provide a concise, factual summary of the page content.",
        )
        response = generate_content_with_fallback(
            contents=prompt,
            api_key=api_key,
            client=client,
            primary_model=primary_model,
            fallback_models=fallback_models or ["gemini-3.1-flash-lite", "gemini-3.7-flash"],
            config=config,
        )
        text = (getattr(response, "text", "") or "").strip()
        sources = extract_grounding_sources(response) or [{"title": snap.get("title") or norm_url, "url": snap.get("final_url") or norm_url}]
        return {
            "success": True, "url": norm_url, "final_url": snap.get("final_url", norm_url),
            "title": snap.get("title", ""), "answer": text, "sources": sources,
            "formatted_reply": text, "model_used": getattr(response, "model_used", primary_model),
        }
    except Exception as exc:
        logger.warning(f"Web page fetch failed for '{norm_url}': {exc}")
        return {
            "success": False, "url": norm_url, "answer": "", "sources": [],
            "formatted_reply": f"Web page fetch unavailable: {exc}", "error": str(exc),
        }
