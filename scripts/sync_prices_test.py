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

    def test_antigravity_enrolls_gemini_not_claude(self):
        floors = {"claude-opus": (4, 6), "claude-sonnet": (4, 6), "gemini": (2, 5)}
        known = {"claude-opus-4-6-thinking", "claude-sonnet-4-6", "gemini-3-flash-agent"}
        def reason(mid, entry=None):
            return sp.enroll_reason("antigravity", mid, entry or chat(), known, floors)
        self.assertEqual(reason("claude-fable-5-1", chat(cache_read=0.25)),
                         "outside-include")
        self.assertEqual(reason("claude-opus-4-6"), "already-present")
        self.assertEqual(reason("gemini-3-flash"), "already-present")
        self.assertEqual(reason("gemini-3-flash-preview"), "already-present")
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
            },
            "gemini": {
                "gemini-3-flash-preview": ("gemini-3-flash-preview",
                                           chat(prompt=0.5, completion=3)),
                "gemini-3.9-flash-preview": ("gemini-3.9-flash-preview",
                                             chat(prompt=0.75, completion=3.75)),
            },
        }
        added = sp.enroll_new_models("antigravity", models, idx, {})
        self.assertEqual(added, ["gemini-3.9-flash"])
        by_id = {m["model"]: m for m in models}
        self.assertNotIn("claude-fable-5-1", by_id)
        self.assertEqual(by_id["gemini-3.9-flash"]["source"], "vendor-api")
        self.assertEqual(by_id["gemini-3.9-flash"]["pricing_style"], "openai")
        self.assertNotIn("gemini-3-flash-preview", by_id)


class CatalogEnrollTest(unittest.TestCase):
    def test_skips_date_tags_and_foreign_providers(self):
        known = {"deepseek-v4-flash", "glm-5.3"}
        self.assertEqual(
            sp.catalog_enroll_reason("ollama", "deepseek-v4-flash:0731", known),
            "snapshot-of-present")
        self.assertEqual(
            sp.catalog_enroll_reason("ollama", "deepseek-v4-flash", known),
            "already-present")
        self.assertEqual(
            sp.catalog_enroll_reason("qoder", "glm-5.3-flash", known),
            "not-enrolled-provider")
        self.assertIsNone(sp.catalog_enroll_reason("ollama", "glm-5.3-flash", known))
        self.assertIsNone(sp.catalog_enroll_reason("ollama", "gemma4:31b", known))

    def test_copies_first_party_and_skips_ollama_prices(self):
        first_party = {
            "glm-5.3-flash": {
                "pricing_style": "openai",
                "prompt_per_1m": 0.075,
                "completion_per_1m": 0.25,
                "cache_read_per_1m": 0.015,
                "cache_write_per_1m": 0,
                "context_window": 1000000,
                "input_modalities": ["text", "image", "video"],
                "effort_levels": ["low", "high", "max"],
                "surface": "chat",
            },
            "k3": {
                "pricing_style": "openai",
                "prompt_per_1m": 3,
                "completion_per_1m": 15,
                "cache_read_per_1m": 0.3,
                "cache_write_per_1m": 0,
                "context_window": 1048576,
                "effort_levels": ["low", "high", "max"],
                "surface": "chat",
            },
        }
        host = {
            "glm-5.3-flash": {
                "prompt_per_1m": 0.15,
                "completion_per_1m": 0.5,
                "context_window": 999,
            },
            "omen-alpha": {
                "prompt_per_1m": 0.2,
                "completion_per_1m": 0.66,
                "cache_read_per_1m": 0.04,
                "context_window": 500000,
                "effort_levels": ["low", "high"],
                "surface": "chat",
            },
        }
        go = [{"model": "glm-5", "source": "manual"}]
        added = sp.enroll_catalog_models(
            "opencode-go", go,
            ["glm-5.3-flash", "kimi-k3", "omen-alpha"],
            first_party, host)
        self.assertEqual(added, ["glm-5.3-flash", "kimi-k3", "omen-alpha"])
        by_id = {m["model"]: m for m in go}
        glm = by_id["glm-5.3-flash"]
        self.assertEqual(glm["source"], "manual")
        self.assertEqual(glm["prompt_per_1m"], 0.075)
        self.assertEqual(glm["completion_per_1m"], 0.25)
        self.assertEqual(glm["context_window"], 1000000)
        self.assertEqual(glm["input_modalities"], ["text", "image", "video"])
        self.assertEqual(by_id["kimi-k3"]["context_window"], 1048576)
        self.assertEqual(by_id["kimi-k3"]["prompt_per_1m"], 3)
        self.assertEqual(by_id["omen-alpha"]["prompt_per_1m"], 0.2)

        ollama = [{"model": "deepseek-v4-flash", "source": "manual"}]
        added = sp.enroll_catalog_models(
            "ollama", ollama, ["glm-5.3-flash", "deepseek-v4-flash:0731"],
            first_party, host)
        self.assertEqual(added, ["glm-5.3-flash"])
        row = {m["model"]: m for m in ollama}["glm-5.3-flash"]
        self.assertNotIn("prompt_per_1m", row)
        self.assertNotIn("pricing_style", row)
        self.assertEqual(row["context_window"], 1000000)
        self.assertEqual(row["effort_levels"], ["low", "high", "max"])
        self.assertEqual(row["source"], "manual")

    def test_vendor_facts_win_over_stale_catalog_copy(self):
        vendor = {
            "muse-spark-1.3-contributor": {
                "prompt_per_1m": 0.1,
                "completion_per_1m": 0.2,
                "cache_read_per_1m": 0.002,
                "context_window": 1048576,
                "input_modalities": ["text", "image", "video", "pdf", "audio"],
                "effort_levels": ["minimal", "low", "medium", "high", "xhigh"],
                "surface": "chat",
            },
        }
        host = {
            "muse-spark-1.3-contributor": {
                "prompt_per_1m": 0.1,
                "completion_per_1m": 0.2,
                "context_window": 1048576,
                "input_modalities": ["text", "image"],
                "effort_levels": ["minimal", "low", "medium", "high", "xhigh", "max"],
                "surface": "chat",
            },
        }
        go = [{"model": "glm-5", "source": "manual"}]
        added = sp.enroll_catalog_models(
            "opencode-go", go, ["muse-spark-1.3-contributor"],
            {}, host, vendor)
        self.assertEqual(added, ["muse-spark-1.3-contributor"])
        row = go[1]
        self.assertEqual(row["input_modalities"],
                         ["text", "image", "video", "pdf", "audio"])
        self.assertEqual(row["effort_levels"],
                         ["minimal", "low", "medium", "high", "xhigh"])
        self.assertEqual(row["prompt_per_1m"], 0.1)
        stale = {
            "model": "muse-spark-1.3-contributor",
            "input_modalities": ["text", "image", "video", "audio"],
            "effort_levels": ["minimal", "low", "medium", "high", "xhigh", "max"],
            "context_window": 262144,
            "prompt_per_1m": 0.1,
            "completion_per_1m": 0.2,
            "cache_read_per_1m": 0.002,
            "cache_write_per_1m": 0,
        }
        facts = sp.lookup_facts(
            "muse-spark-1.3-contributor", {}, vendor, host)
        changes = {f: after for f, _, after in sp.apply_catalog_facts(
            stale, facts, sp.FIRST_PARTY_FACTS, overwrite=True)}
        self.assertEqual(changes["input_modalities"],
                         ["text", "image", "video", "pdf", "audio"])
        self.assertEqual(changes["effort_levels"],
                         ["minimal", "low", "medium", "high", "xhigh"])
        self.assertEqual(changes["context_window"], 1048576)
        rate_facts = dict(facts)
        rate_facts["completion_per_1m"] = 9.99
        rate_changes = sp.apply_catalog_facts(
            stale, rate_facts, sp.FIRST_PARTY_RATES, overwrite=False)
        self.assertEqual(rate_changes, [])

    def test_vendor_zero_price_does_not_hide_host_rate(self):
        vendor = {
            "deepseek-v4.1-flash": {
                "prompt_per_1m": 0,
                "completion_per_1m": 0,
                "context_window": 1000000,
                "effort_levels": ["low", "high", "max"],
                "surface": "chat",
            },
        }
        host = {
            "deepseek-v4.1-flash": {
                "prompt_per_1m": 0.15,
                "completion_per_1m": 0.6,
                "cache_read_per_1m": 0.003,
                "context_window": 1000000,
                "input_modalities": ["text", "image"],
                "surface": "chat",
            },
        }
        facts = sp.lookup_facts("deepseek-v4.1-flash", {}, vendor, host)
        self.assertEqual(facts["prompt_per_1m"], 0.15)
        self.assertEqual(facts["completion_per_1m"], 0.6)
        self.assertEqual(facts["effort_levels"], ["low", "high", "max"])
        go = [{"model": "glm-5", "source": "manual"}]
        added = sp.enroll_catalog_models(
            "opencode-go", go, ["deepseek-v4.1-flash"], {}, host, vendor)
        self.assertEqual(added, ["deepseek-v4.1-flash"])
        row = {m["model"]: m for m in go}["deepseek-v4.1-flash"]
        self.assertEqual(row["prompt_per_1m"], 0.15)
        self.assertEqual(row["completion_per_1m"], 0.6)

    def test_vendor_without_ladder_clears_aggregator_effort(self):
        vendor = {
            "kimi-k2.6": {
                "context_window": 262144,
                "input_modalities": ["text", "image", "video"],
                "surface": "chat",
            },
        }
        stale = {
            "model": "kimi-k2.6",
            "context_window": 262144,
            "effort_levels": ["none", "minimal", "low", "medium", "high", "xhigh", "max"],
        }
        facts = sp.lookup_facts("kimi-k2.6", {}, vendor, {})
        self.assertNotIn("effort_levels", facts)
        cleared = sp.clear_vendor_silent_effort(stale, facts, vendor)
        self.assertEqual(cleared, [("effort_levels", stale["effort_levels"], None)])
        self.assertEqual(sp.clear_vendor_silent_effort(stale, facts, {}), [])


if __name__ == "__main__":
    unittest.main()
