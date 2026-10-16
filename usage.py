"""Read ChatGPT, Claude, Grok, and Gemini usage already signed in on this Mac.

The numbers come from the same read-only endpoints each official CLI uses.
Nothing here sends a prompt, spends quota, or writes a credential file.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 20


def split_percent(used) -> tuple[int, int]:
    used_i = int(round(float(used)))
    used_i = max(0, min(100, used_i))
    return used_i, 100 - used_i


def window(label: str, used, resets_at, *, approx: bool = False, wid: str | None = None) -> dict:
    used_i, remaining = split_percent(used)
    return {
        "id": wid or label,
        "label": label,
        "used": used_i,
        "remaining": remaining,
        "resetsAt": resets_at,
        "approx": approx,
    }


def provider(pid: str, name: str, plan: str | None, windows: list, *, ok: bool = True, note: str | None = None, extra: str | None = None) -> dict:
    return {
        "id": pid,
        "name": name,
        "plan": plan,
        "ok": ok,
        "note": note,
        "extra": extra,
        "windows": windows,
    }


def failed(pid: str, name: str, note: str) -> dict:
    return provider(pid, name, None, [], ok=False, note=note)


def claude_plan(subscription: str | None, tier: str | None) -> str | None:
    tier_label = {
        "default_claude_max_20x": "Max 20x",
        "default_claude_max_5x": "Max 5x",
        "default_claude_max": "Max",
        "default_claude_pro": "Pro",
    }.get(tier or "")
    sub_label = {
        "max": "Max",
        "pro": "Pro",
        "team": "Team",
        "enterprise": "Enterprise",
    }.get((subscription or "").lower())
    if sub_label and tier_label and sub_label not in tier_label:
        return f"{sub_label} · {tier_label}"
    return tier_label or sub_label


def parse_claude(payload: dict, plan: str | None) -> dict:
    windows = []
    limits = payload.get("limits") or []
    for item in limits:
        if item.get("percent") is None:
            continue
        kind = item.get("kind") or ""
        model = ((item.get("scope") or {}).get("model") or {})
        name = model.get("display_name")
        if kind == "session":
            label = "5h"
        elif kind in ("weekly_all", "weekly"):
            label = "wk"
        elif name:
            label = name
        else:
            continue
        windows.append(window(label, item["percent"], item.get("resets_at"), wid=kind or label))
    if not windows:
        for key, label in (
            ("five_hour", "5h"),
            ("seven_day", "wk"),
            ("seven_day_opus", "Opus"),
            ("seven_day_sonnet", "Sonnet"),
        ):
            block = payload.get(key) or None
            if not isinstance(block, dict) or block.get("utilization") is None:
                continue
            windows.append(window(label, block["utilization"], block.get("resets_at"), wid=key))
    if not windows:
        return failed("claude", "Claude", "Could not read usage")
    return provider("claude", "Claude", plan, windows)


def window_label(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return "usage"
    if abs(seconds - 18000) <= 600:
        return "5h"
    if abs(seconds - 86400) <= 3600:
        return "1d"
    if abs(seconds - 604800) <= 6 * 3600:
        return "wk"
    days = round(seconds / 86400)
    if days >= 2:
        return f"{days}d"
    hours = max(1, round(seconds / 3600))
    return f"{hours}h"


def codex_plan(plan_type: str | None) -> str | None:
    return {
        "promax": "Pro",
        "pro": "Pro",
        "plus": "Plus",
        "team": "Team",
        "free": "Free",
        "business": "Business",
        "enterprise": "Enterprise",
    }.get((plan_type or "").lower(), None if not plan_type else plan_type)


def format_credits(raw) -> str | None:
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    if abs(number - round(number)) < 0.05:
        return f"{round(number):,}"
    return f"{number:,.1f}"


def _iso_from_unix(value) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def parse_codex(payload: dict) -> dict:
    rate = payload.get("rate_limit") or {}
    windows = []
    for key, block in (("primary", rate.get("primary_window")), ("secondary", rate.get("secondary_window"))):
        if not isinstance(block, dict) or block.get("used_percent") is None:
            continue
        resets = block.get("reset_at")
        windows.append(
            window(
                window_label(block.get("limit_window_seconds")),
                block["used_percent"],
                _iso_from_unix(resets),
                wid=key,
            )
        )
    credits = payload.get("credits") or {}
    extra = None
    if credits.get("unlimited"):
        extra = "Credits unlimited"
    elif credits.get("has_credits"):
        formatted = format_credits(credits.get("balance"))
        if formatted:
            extra = f"Credits {formatted}"
    if not windows and not extra:
        return failed("chatgpt", "ChatGPT", "Could not read usage")
    return provider("chatgpt", "ChatGPT", codex_plan(payload.get("plan_type")), windows, extra=extra)


PRODUCT_LABELS = {
    "GrokBuild": "Build",
    "GrokChat": "Chat",
    "Api": "API",
    "Imagine": "Imagine",
    "Voice": "Voice",
}


def parse_grok(billing: dict, settings: dict | None = None) -> dict:
    config = billing.get("config") or {}
    plan = None
    if isinstance(settings, dict):
        shown = settings.get("subscription_tier_display")
        if isinstance(shown, str) and shown.strip():
            plan = shown.strip()
    period = config.get("currentPeriod") or {}
    resets = period.get("end") or config.get("billingPeriodEnd")
    windows = []
    reported = config.get("creditUsagePercent")
    if reported is None and period.get("type"):
        windows.append(window("wk", 0, resets, approx=True, wid="week"))
    elif reported is not None:
        windows.append(window("wk", reported, resets, wid="week"))
    headline = windows[0]["used"] if windows else None
    products = []
    for item in config.get("productUsage") or []:
        if not isinstance(item, dict) or item.get("usagePercent") is None:
            continue
        label = PRODUCT_LABELS.get(item.get("product"), item.get("product") or "기타")
        products.append(window(label, item["usagePercent"], resets, wid=f"product-{label}"))
    if len(products) == 1 and headline is not None and products[0]["used"] == headline:
        products = []
    windows.extend(products)
    cap = ((config.get("onDemandCap") or {}).get("val"))
    used_od = ((config.get("onDemandUsed") or {}).get("val"))
    if isinstance(cap, (int, float)) and cap > 0 and isinstance(used_od, (int, float)):
        windows.append(window("extra", used_od / cap * 100, resets, wid="ondemand"))
    if not windows:
        return failed("grok", "Grok", "Could not read usage")
    return provider("grok", "Grok", plan, windows)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _request(url: str, headers: dict, method: str = "GET", body: bytes | None = None):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as error:
        error.close()
        raise RuntimeError(f"HTTP {error.code}") from None


def _note_for_error(error: Exception) -> str:
    text = str(error)
    if text.startswith("No ") or text.startswith("Could not") or text.startswith("Open ") or text.startswith("Run "):
        return text
    if "HTTP 429" in text:
        return "Try again in a moment"
    if "HTTP 401" in text or "HTTP 403" in text:
        return "Login expired"
    return "Could not read usage"


def _login_note(error: Exception, expired: str) -> str:
    note = _note_for_error(error)
    if note == "Login expired":
        return expired
    return note


def _claude_oauth() -> dict:
    path = Path.home() / ".claude" / ".credentials.json"
    if not path.is_file():
        raise RuntimeError("No Claude login on this Mac")
    data = _read_json(path)
    oauth = data.get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        raise RuntimeError("No Claude login on this Mac")
    return oauth


def _expires_in(expires_at) -> float | None:
    if not isinstance(expires_at, (int, float)):
        return None
    seconds = expires_at / 1000 if expires_at > 1e12 else expires_at
    return seconds - time.time()


def fetch_claude() -> dict:
    try:
        oauth = _claude_oauth()
        remaining = _expires_in(oauth.get("expiresAt"))
        if remaining is not None and remaining < 120:
            return failed("claude", "Claude", "Open Claude once")
        _, payload = _request(
            "https://api.anthropic.com/api/oauth/usage",
            {
                "Authorization": f"Bearer {oauth['accessToken']}",
                "anthropic-beta": "oauth-2025-04-20",
                "anthropic-version": "2023-06-01",
                "User-Agent": "claude-cli/2.1.80 (external, cli)",
                "x-app": "cli",
                "Accept": "application/json",
            },
        )
        plan = claude_plan(oauth.get("subscriptionType"), oauth.get("rateLimitTier"))
        return parse_claude(payload, plan)
    except Exception as error:
        return failed("claude", "Claude", _login_note(error, "Open Claude once"))


def fetch_chatgpt() -> dict:
    try:
        path = Path.home() / ".codex" / "auth.json"
        if not path.exists():
            raise RuntimeError("No ChatGPT login on this Mac")
        auth = _read_json(path)
        tokens = auth.get("tokens") or {}
        access = tokens.get("access_token")
        account = tokens.get("account_id")
        if not access or not account:
            raise RuntimeError("No ChatGPT login on this Mac")
        _, payload = _request(
            "https://chatgpt.com/backend-api/wham/usage",
            {
                "Authorization": f"Bearer {access}",
                "ChatGPT-Account-Id": account,
                "Accept": "application/json",
                "User-Agent": "codex-cli",
            },
        )
        return parse_codex(payload)
    except Exception as error:
        return failed("chatgpt", "ChatGPT", _login_note(error, "Open Codex once"))


def _grok_entry() -> dict:
    path = Path.home() / ".grok" / "auth.json"
    if not path.exists():
        raise RuntimeError("No Grok login on this Mac")
    data = _read_json(path)
    entries = [value for value in data.values() if isinstance(value, dict) and value.get("key")]
    if not entries:
        raise RuntimeError("No Grok login on this Mac")
    entries.sort(key=lambda item: item.get("expires_at") or "", reverse=True)
    return entries[0]


def fetch_grok() -> dict:
    try:
        entry = _grok_entry()
        headers = {
            "Authorization": f"Bearer {entry['key']}",
            "X-XAI-Token-Auth": "xai-grok-cli",
            "Accept": "application/json",
        }
        _, billing = _request("https://cli-chat-proxy.grok.com/v1/billing?format=credits", headers)
        settings = None
        try:
            _, settings = _request("https://cli-chat-proxy.grok.com/v1/settings", headers)
        except Exception:
            settings = None
        return parse_grok(billing, settings)
    except Exception as error:
        return failed("grok", "Grok", _login_note(error, "Run grok once in the terminal"))


def gemini_label(model_id: str) -> str:
    text = (model_id or "").lower().split("/")[-1]
    if "flash-lite" in text or "flash_lite" in text:
        return "Flash Lite"
    if "flash" in text:
        return "Flash"
    if "pro" in text:
        return "Pro"
    if "embed" in text:
        return "Embed"
    short = text[7:] if text.startswith("gemini-") else text
    for suffix in ("-preview", "-latest", "-exp"):
        if short.endswith(suffix):
            short = short[: -len(suffix)]
    return (short or "usage")[:18]


def parse_gemini(payload: dict, plan: str | None, extra: str | None = None) -> dict:
    grouped: dict[str, tuple] = {}
    for bucket in payload.get("buckets") or []:
        if not isinstance(bucket, dict) or bucket.get("remainingFraction") is None:
            continue
        try:
            fraction = float(bucket["remainingFraction"])
        except (TypeError, ValueError):
            continue
        label = gemini_label(str(bucket.get("modelId") or "usage"))
        used = (1 - fraction) * 100
        requests = str(bucket.get("tokenType") or "").upper() == "REQUESTS"
        current = grouped.get(label)
        if current is None or (requests and not current[1]) or (requests == current[1] and used > current[0]):
            grouped[label] = (used, requests, bucket.get("resetTime"), str(bucket.get("modelId") or label))
    if not grouped:
        return failed("gemini", "Gemini", "Could not read usage")
    ranked = sorted(grouped.items(), key=lambda item: item[1][0], reverse=True)[:4]
    preferred = ["Pro", "Flash", "Flash Lite"]
    ranked.sort(key=lambda item: (preferred.index(item[0]) if item[0] in preferred else 50, item[0]))
    windows = [
        window(label, value[0], value[2], wid=value[3])
        for label, value in ranked
    ]
    return provider("gemini", "Gemini", plan, windows, extra=extra)


def gemini_plan(load: dict) -> tuple[str | None, str | None]:
    paid = load.get("paidTier") if isinstance(load.get("paidTier"), dict) else {}
    current = load.get("currentTier") if isinstance(load.get("currentTier"), dict) else {}
    name = paid.get("name") or current.get("name")
    plan = name.strip() if isinstance(name, str) and name.strip() else None
    if not plan:
        tier_id = str(paid.get("id") or current.get("id") or "")
        plan = {
            "free-tier": "Free",
            "standard-tier": "Standard",
            "legacy-tier": "Legacy",
        }.get(tier_id)
        if plan is None and tier_id:
            plan = tier_id.removesuffix("-tier").replace("-", " ").title()
    extra = None
    for item in paid.get("availableCredits") or []:
        if isinstance(item, dict) and item.get("creditType") == "GOOGLE_ONE_AI":
            formatted = format_credits(item.get("creditAmount"))
            if formatted:
                extra = f"Credits {formatted}"
    return plan or None, extra


def _gemini_access_token() -> str:
    home = Path.home()
    candidates = [
        home / ".gemini" / "oauth_creds.json",
        home / ".config" / "gemini" / "oauth_creds.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        data = _read_json(path)
        token = data.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("Login expired")
        remaining = _expires_in(data.get("expiry_date"))
        if remaining is not None and remaining < 120:
            raise RuntimeError("Login expired")
        return token
    raise RuntimeError("No Gemini login on this Mac")


def fetch_gemini() -> dict:
    try:
        token = _gemini_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "gemini-cli",
        }
        _, loaded = _request(
            "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
            headers,
            method="POST",
            body=json.dumps(
                {
                    "metadata": {
                        "ideType": "GEMINI_CLI",
                        "pluginType": "GEMINI",
                        "platform": "PLATFORM_UNSPECIFIED",
                    }
                }
            ).encode(),
        )
        project = loaded.get("cloudaicompanionProject") if isinstance(loaded, dict) else None
        if not isinstance(project, str) or not project:
            return failed("gemini", "Gemini", "Run gemini once")
        _, quota = _request(
            "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
            headers,
            method="POST",
            body=json.dumps({"project": project}).encode(),
        )
        plan, extra = gemini_plan(loaded if isinstance(loaded, dict) else {})
        return parse_gemini(quota if isinstance(quota, dict) else {}, plan, extra)
    except Exception as error:
        return failed("gemini", "Gemini", _login_note(error, "Run gemini once"))


def fetch_all() -> list[dict]:
    return [fetch_chatgpt(), fetch_claude(), fetch_grok(), fetch_gemini()]
