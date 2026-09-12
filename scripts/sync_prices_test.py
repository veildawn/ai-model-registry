#!/usr/bin/env python3
"""Unit tests for AUTO_ENROLL: new vendor ids land, attic ids do not."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sync_prices as sp  # noqa: E402


def chat(prompt=10, completion=50, cache_read=0.25, cache_write=12.5, **extra):
    entry = {
        "mode": "chat",
        "input_cost_per_token": prompt / 1e6,
        "output_cost_per_token": completion / 1e6,
        "cache_read_input_token_cost": cache_read / 1e6,
        "cache_creation_input_token_cost": cache_write / 1e6,
        "max_input_tokens": 1000000,
        "supported_modalities": ["text", "image"],
    }
    entry.update(extra)
    return entry


class FamilyVersionTest(unittest.TestCase):
    def test_claude_and_gpt(self):
        self.assertEqual(sp.family_version("claude-fable-5"), ("claude-fable", (5, 0)))
        self.assertEqual(sp.family_version("claude-fable-5-1"), ("claude-fable", (5, 1)))
        self.assertEqual(sp.family_version("claude-opus-4-5-20251101"),
                         ("claude-opus", (4, 5)))
        self.assertEqual(sp.family_version("gpt-5.4-mini"), ("gpt", (5, 4)))
        self.assertEqual(sp.family_version("gpt-6-astra"), ("gpt", (6, 0)))
        self.assertEqual(sp.family_version("gpt-image-2.5-flare"), ("gpt-image", (2, 5)))
        self.assertEqual(sp.family_version("gemini-3.8-flash"), ("gemini", (3, 8)))
        self.assertEqual(sp.family_version("grok-4.20-0309-reasoning"), ("grok", (4, 20)))
        self.assertEqual(sp.family_version("grok-build-0.1"), ("grok-build", (0, 1)))


class EnrollReasonTest(unittest.TestCase):
    def setUp(self):
        self.floors = {
            "claude-fable": (5, 0),
            "claude-opus": (4, 5),
            "claude-sonnet": (4, 5),
            "claude-haiku": (4, 5),
            "gpt": (5, 4),
            "gpt-image": (2, 0),
            "gemini": (2, 0),
            "grok": (4, 3),
        }
        self.known = {
            "claude-fable-5",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-6",
            "gpt-5.4",
            "gpt-image-2",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        }

    def reason(self, provider, mid, entry=None):
        return sp.enroll_reason(provider, mid, entry or chat(), self.known, self.floors)

    def test_fable_51_enrolls(self):
        self.assertIsNone(self.reason("anthropic", "claude-fable-5-1",
                                      chat(cache_read=0.25)))

    def test_mythos_is_new_family(self):
        self.assertIsNone(self.reason("anthropic", "claude-mythos-5-1"))

    def test_skips_old_claude_and_dated_siblings(self):
        self.assertEqual(self.reason("anthropic", "claude-3-opus-20240229"),
                         "outside-include")
        self.assertEqual(self.reason("anthropic", "claude-opus-4-1"), "below-floor")
        self.assertEqual(self.reason("anthropic", "claude-haiku-4-5"), "already-present")
        self.assertEqual(self.reason("anthropic", "claude-opus-4-6-20260205"),
                         "snapshot-of-present")
        self.assertEqual(self.reason("anthropic", "claude-mythos-preview"),
                         "unversioned-preview")

    def test_skips_openai_attic_keeps_current_skus(self):
        self.assertEqual(self.reason("codex", "gpt-4o"), "outside-include")
        self.assertEqual(self.reason("codex", "gpt-5.1"), "below-floor")
        self.assertEqual(self.reason("codex", "gpt-5.4-2026-03-05"),
                         "snapshot-of-present")
        self.assertEqual(self.reason("codex", "gpt-5-mini"), "outside-include")
        self.assertIsNone(self.reason("codex", "gpt-5.4-nano"))
        self.assertIsNone(self.reason("codex", "gpt-5.7"))
        self.assertEqual(self.reason("codex", "gpt-image-1"), "below-floor")
        self.assertIsNone(self.reason("codex", "gpt-image-2.5-flare"))
        self.assertEqual(self.reason("codex", "ft:gpt-4o-mini-2024-07-18"),
                         "skipped-pattern")
        self.assertEqual(self.reason("codex", "gpt-5.4-mini-latest"), "skipped-pattern")

    def test_skips_gemini_snapshots_and_zero_price(self):
        self.assertEqual(
            self.reason("google-ai-studio", "gemini-2.5-flash-lite-preview-09-2025"),
            "snapshot-of-present")
        self.assertEqual(
            self.reason("google-ai-studio", "gemini-2.5-flash-lite-preview-06-17"),
            "snapshot-of-present")
        self.assertEqual(
            self.reason("google-ai-studio", "gemini-2.0-flash-001"),
            "snapshot-of-present")
        self.assertEqual(
            self.reason("google-ai-studio", "gemini-exp-1206",
                        chat(prompt=0, completion=0)),
            "skipped-pattern")
        self.assertIsNone(self.reason("google-ai-studio", "gemini-3.9-flash"))

    def test_skips_old_grok_keeps_new(self):
        self.assertEqual(self.reason("xai", "grok-3"), "outside-include")
        self.assertEqual(self.reason("xai", "grok-4-1-fast"), "outside-include")
        self.assertIsNone(self.reason("xai", "grok-4.7"))
        self.assertIsNone(self.reason("xai", "grok-code-fast"))

    def test_resellers_are_not_enrolled(self):
        self.assertEqual(self.reason("qoder", "claude-fable-5-1"),
                         "not-enrolled-provider")

    def test_antigravity_enrolls_claude_and_gemini(self):
        floors = {"claude-opus": (4, 6), "claude-sonnet": (4, 6), "gemini": (2, 5)}
        known = {"claude-opus-4-6-thinking", "claude-sonnet-4-6", "gemini-3-flash-agent"}
        def reason(mid, entry=None):
            return sp.enroll_reason("antigravity", mid, entry or chat(), known, floors)
        self.assertIsNone(reason("claude-fable-5-1", chat(cache_read=0.25)))
        self.assertEqual(reason("claude-opus-4-6"), "already-present")
        self.assertEqual(reason("gemini-3-flash"), "already-present")
        self.assertEqual(reason("gemini-3-flash-preview"), "already-present")
        self.assertEqual(reason("claude-opus-4-5"), "below-floor")
        self.assertIsNone(reason("gemini-3.9-flash"))
        self.assertEqual(reason("gpt-5.4"), "outside-include")

    def test_unpriced_and_unserved(self):
        self.assertEqual(
            self.reason("xai", "grok-imagine-image-pro",
                        {"mode": "image_generation"}),
            "unpriced")
        self.assertEqual(
            self.reason("codex", "gpt-5.4-nano",
                        {"mode": "embedding", "input_cost_per_token": 1e-7}),
            "unserved-surface")


class EnrollNewModelsTest(unittest.TestCase):
    def test_inserts_alphabetically_and_delegates(self):
        models = [
            {"model": "claude-fable-5", "source": "litellm",
             "prompt_per_1m": 10, "completion_per_1m": 50},
            {"model": "claude-opus-5", "source": "litellm",
             "prompt_per_1m": 5, "completion_per_1m": 25},
        ]
        idx = {
            "anthropic": {
                "claude-fable-5": ("claude-fable-5", chat()),
                "claude-fable-5-1": ("claude-fable-5-1", chat(cache_read=0.25)),
                "claude-opus-4-1": ("claude-opus-4-1", chat(prompt=15, completion=75)),
            }
        }
        added = sp.enroll_new_models("anthropic", models, idx, {})
        self.assertEqual(added, ["claude-fable-5-1"])
        self.assertEqual([m["model"] for m in models],
                         ["claude-fable-5", "claude-fable-5-1", "claude-opus-5"])
        new = models[1]
        self.assertEqual(new["source"], "litellm")
        self.assertEqual(new["pricing_style"], "anthropic")
        self.assertEqual(new["prompt_per_1m"], 10)
        self.assertEqual(new["completion_per_1m"], 50)
        self.assertEqual(new["cache_read_per_1m"], 0.25)
        self.assertEqual(new["surface"], "chat")

    def test_antigravity_uses_vendor_api_and_drops_gemini_preview(self):
        models = [
            {"model": "claude-opus-4-6-thinking", "source": "vendor-api",
             "prompt_per_1m": 5, "completion_per_1m": 25},
            {"model": "gemini-3-flash", "source": "vendor-api",
             "prompt_per_1m": 0.5, "completion_per_1m": 3},
        ]
        idx = {
            "anthropic": {
                "claude-fable-5-1": ("claude-fable-5-1", chat(cache_read=0.25)),
                "claude-opus-4-6": ("claude-opus-4-6", chat(prompt=5, completion=25)),
            },
            "gemini": {
                "gemini-3-flash-preview": ("gemini-3-flash-preview",
                                           chat(prompt=0.5, completion=3)),
                "gemini-3.9-flash-preview": ("gemini-3.9-flash-preview",
                                             chat(prompt=0.75, completion=3.75)),
            },
        }
        added = sp.enroll_new_models("antigravity", models, idx, {})
        self.assertEqual(added, ["claude-fable-5-1", "gemini-3.9-flash"])
        by_id = {m["model"]: m for m in models}
        self.assertEqual(by_id["claude-fable-5-1"]["source"], "vendor-api")
        self.assertEqual(by_id["claude-fable-5-1"]["pricing_style"], "anthropic")
        self.assertEqual(by_id["claude-fable-5-1"]["cache_read_per_1m"], 0.25)
        self.assertEqual(by_id["gemini-3.9-flash"]["source"], "vendor-api")
        self.assertEqual(by_id["gemini-3.9-flash"]["pricing_style"], "openai")
        self.assertNotIn("gemini-3-flash-preview", by_id)


if __name__ == "__main__":
    unittest.main()
