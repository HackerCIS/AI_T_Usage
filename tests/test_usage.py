import os
import unittest

from server import listen_host, logo_path
from usage import (
    _login_note,
    claude_plan,
    claude_refresh_body,
    pick_claude_payload,
    gemini_plan,
    parse_claude,
    parse_codex,
    parse_gemini,
    parse_grok,
)


CLAUDE = {
    "five_hour": {"utilization": 1.0, "resets_at": "2026-10-15T16:00:00+00:00"},
    "seven_day": {"utilization": 14.0, "resets_at": "2026-10-19T21:00:00+00:00"},
    "limits": [
        {"kind": "session", "percent": 1, "resets_at": "2026-10-15T16:00:00+00:00"},
        {"kind": "weekly_all", "percent": 14, "resets_at": "2026-10-19T21:00:00+00:00"},
        {
            "kind": "weekly_scoped",
            "percent": 20,
            "resets_at": "2026-10-19T21:00:00+00:00",
            "scope": {"model": {"display_name": "Fable"}},
        },
    ],
}

CODEX = {
    "email": "person@example.com",
    "account_id": "should-not-leak",
    "plan_type": "promax",
    "rate_limit": {
        "primary_window": {
            "used_percent": 29,
            "limit_window_seconds": 604800,
            "reset_at": 1792657072,
        },
        "secondary_window": None,
    },
    "credits": {"has_credits": True, "unlimited": False, "balance": "54004.0042195000"},
}

GROK_QUIET = {
    "config": {
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "end": "2026-10-20T13:41:34+00:00",
        },
        "onDemandCap": {"val": 0},
        "onDemandUsed": {"val": 0},
        "prepaidBalance": {"val": 0},
    }
}


class ParseTests(unittest.TestCase):
    def test_claude_plan_and_windows(self):
        self.assertEqual(claude_plan("team", "default_claude_max_5x"), "Team · Max 5x")
        parsed = parse_claude(CLAUDE, "Team · Max 5x")
        self.assertEqual(parsed["plan"], "Team · Max 5x")
        self.assertEqual([row["label"] for row in parsed["windows"]], ["5h", "wk", "Fable"])
        self.assertEqual(parsed["windows"][0]["remaining"], 99)
        self.assertEqual(parsed["windows"][1]["remaining"], 86)

    def test_claude_falls_back_when_limits_missing(self):
        payload = {"five_hour": {"utilization": 40, "resets_at": "2026-10-15T16:00:00+00:00"}}
        parsed = parse_claude(payload, "Max")
        self.assertEqual(parsed["windows"][0]["remaining"], 60)

    def test_codex_hides_identity_and_reads_week(self):
        parsed = parse_codex(CODEX)
        blob = str(parsed)
        self.assertNotIn("person@example.com", blob)
        self.assertNotIn("should-not-leak", blob)
        self.assertEqual(parsed["plan"], "Pro")
        self.assertEqual(parsed["windows"][0]["label"], "wk")
        self.assertEqual(parsed["windows"][0]["remaining"], 71)
        self.assertEqual(parsed["extra"], "Credits 54,004")
        self.assertTrue(parsed["windows"][0]["resetsAt"].endswith("Z"))

    def test_grok_treats_a_missing_percent_as_under_one(self):
        parsed = parse_grok(GROK_QUIET, {"subscription_tier_display": "SuperGrok Heavy"})
        self.assertEqual(parsed["plan"], "SuperGrok Heavy")
        self.assertEqual(parsed["windows"][0]["remaining"], 100)
        self.assertTrue(parsed["windows"][0]["approx"])

    def test_grok_products_do_not_repeat_the_headline(self):
        payload = {
            "config": {
                "creditUsagePercent": 34,
                "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY", "end": "2026-10-20T00:00:00+00:00"},
                "productUsage": [
                    {"product": "GrokBuild", "usagePercent": 30},
                    {"product": "GrokChat", "usagePercent": 4},
                ],
            }
        }
        parsed = parse_grok(payload, None)
        self.assertEqual([row["label"] for row in parsed["windows"]], ["wk", "Build", "Chat"])

    def test_gemini_prefers_request_buckets_and_keeps_the_fullest(self):
        payload = {
            "buckets": [
                {
                    "modelId": "gemini-2.5-pro",
                    "tokenType": "INPUT_TOKENS",
                    "remainingFraction": 0.1,
                    "resetTime": "2026-10-17T00:00:00Z",
                },
                {
                    "modelId": "gemini-2.5-pro",
                    "tokenType": "REQUESTS",
                    "remainingFraction": 0.62,
                    "resetTime": "2026-10-17T00:00:00Z",
                },
                {
                    "modelId": "gemini-3-pro-preview",
                    "tokenType": "REQUESTS",
                    "remainingFraction": 0.4,
                    "resetTime": "2026-10-17T00:00:00Z",
                },
                {
                    "modelId": "gemini-2.5-flash",
                    "tokenType": "REQUESTS",
                    "remainingFraction": 0.9,
                    "resetTime": "2026-10-17T00:00:00Z",
                },
                {
                    "modelId": "gemini-2.5-flash-lite",
                    "tokenType": "REQUESTS",
                    "remainingFraction": 1,
                    "resetTime": "2026-10-17T00:00:00Z",
                },
            ]
        }
        parsed = parse_gemini(payload, "Google AI Pro")
        self.assertEqual(parsed["plan"], "Google AI Pro")
        self.assertEqual([row["label"] for row in parsed["windows"]], ["Pro", "Flash", "Flash Lite"])
        self.assertEqual(parsed["windows"][0]["used"], 60)
        self.assertEqual(parsed["windows"][0]["remaining"], 40)
        self.assertEqual(parsed["windows"][2]["used"], 0)
        self.assertFalse(parsed["windows"][2]["approx"])
        self.assertNotIn("person@example.com", str(parsed))

    def test_gemini_shows_at_most_four_windows(self):
        payload = {
            "buckets": [
                {"modelId": "gemini-2.5-pro", "tokenType": "REQUESTS", "remainingFraction": 0.5},
                {"modelId": "gemini-2.5-flash", "tokenType": "REQUESTS", "remainingFraction": 0.8},
                {"modelId": "gemini-2.5-flash-lite", "tokenType": "REQUESTS", "remainingFraction": 0.7},
                {"modelId": "text-embedding-004", "tokenType": "REQUESTS", "remainingFraction": 0.2},
                {"modelId": "gemini-robotics", "tokenType": "REQUESTS", "remainingFraction": 0.05},
            ]
        }
        parsed = parse_gemini(payload, None)
        labels = [row["label"] for row in parsed["windows"]]
        self.assertLessEqual(len(labels), 4)
        self.assertIn("Pro", labels)
        self.assertIn("robotics", labels)
        self.assertNotIn("Flash", labels)
        self.assertEqual(max(row["used"] for row in parsed["windows"]), 95)

    def test_gemini_plan_hides_the_project_id(self):
        plan, extra = gemini_plan(
            {
                "cloudaicompanionProject": "secret-project-id",
                "paidTier": {
                    "id": "standard-tier",
                    "name": "Google AI Pro",
                    "availableCredits": [{"creditType": "GOOGLE_ONE_AI", "creditAmount": "1200"}],
                },
            }
        )
        self.assertEqual(plan, "Google AI Pro")
        self.assertEqual(extra, "Credits 1,200")
        self.assertNotIn("secret-project-id", f"{plan} {extra}")
        fallback, _ = gemini_plan({"currentTier": {"id": "free-tier"}})
        self.assertEqual(fallback, "Free")

    def test_claude_prefers_the_login_that_expires_later(self):
        stale = {"claudeAiOauth": {"accessToken": "old", "expiresAt": 100}}
        current = {"claudeAiOauth": {"accessToken": "new", "expiresAt": 500}}
        missing = {"claudeAiOauth": {"expiresAt": 900}}
        chosen = pick_claude_payload([stale, missing, current])
        self.assertEqual(chosen["claudeAiOauth"]["accessToken"], "new")

    def test_claude_refresh_keeps_the_saved_scopes(self):
        body = claude_refresh_body("refresh-token", ["user:inference", "user:profile"])
        self.assertEqual(body["grant_type"], "refresh_token")
        self.assertEqual(body["refresh_token"], "refresh-token")
        self.assertEqual(body["scope"], "user:inference user:profile")
        self.assertNotIn("client_secret", body)
        bare = claude_refresh_body("refresh-token", None)
        self.assertNotIn("scope", bare)

    def test_expired_login_notes_do_not_repeat_the_old_korean_string(self):
        self.assertEqual(_login_note(RuntimeError("HTTP 401"), "Open Codex once"), "Open Codex once")
        self.assertEqual(_login_note(RuntimeError("HTTP 403"), "Run gemini once"), "Run gemini once")
        self.assertEqual(_login_note(RuntimeError("HTTP 429"), "Open Claude once"), "Try again in a moment")
        self.assertEqual(
            _login_note(RuntimeError("No Grok login on this Mac"), "Run grok once in the terminal"),
            "No Grok login on this Mac",
        )
        self.assertNotIn("ya29", _login_note(RuntimeError("HTTP 401 ya29.secret"), "Run gemini once"))

    def test_server_stays_on_localhost_unless_asked(self):
        old = os.environ.pop("NAMUM_LAN", None)
        try:
            self.assertEqual(listen_host([]), "127.0.0.1")
            self.assertEqual(listen_host(["--lan"]), "0.0.0.0")
            os.environ["NAMUM_LAN"] = "1"
            self.assertEqual(listen_host([]), "0.0.0.0")
        finally:
            os.environ.pop("NAMUM_LAN", None)
            if old is not None:
                os.environ["NAMUM_LAN"] = old

    def test_logo_route_is_an_allowlist(self):
        self.assertIsNone(logo_path("/logos/../server.py"))
        self.assertIsNone(logo_path("/logos/chatgpt.png/../../usage.py"))
        self.assertIsNone(logo_path("/logos/not-a-logo.png"))
        allowed = logo_path("/logos/gemini.png")
        self.assertIsNotNone(allowed)
        self.assertEqual(allowed.name, "gemini.png")


if __name__ == "__main__":
    unittest.main()
