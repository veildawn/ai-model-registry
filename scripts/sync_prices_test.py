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
        self.assertEqual(sp.family_version("gemini-omni-1.2-flash"), ("gemini-omni", (1, 2)))
        self.assertEqual(sp.family_version("gemini-nano-banana-2.1"), ("gemini-nano-banana", (2, 1)))
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
            self.reason("gemini", "gemini-2.5-flash-lite-preview-09-2025"),
            "snapshot-of-present")
        self.assertEqual(
            self.reason("gemini", "gemini-2.5-flash-lite-preview-06-17"),
            "snapshot-of-present")
        self.assertEqual(
            self.reason("gemini", "gemini-2.0-flash-001"),
            "snapshot-of-present")
        self.assertEqual(
            self.reason("gemini", "gemini-exp-1206",
                        chat(prompt=0, completion=0)),
            "skipped-pattern")
        self.assertIsNone(self.reason("gemini", "gemini-3.9-flash"))
        self.assertIsNone(self.reason("gemini", "gemini-omni-1.2-flash"))
        self.assertIsNone(self.reason("gemini", "gemini-nano-banana-2.1",
                                      chat(mode="image_generation")))
        self.assertIsNone(self.reason("gemini", "gemini-3.8-flash-cyber"))
        self.assertIsNone(self.reason("gemini", "gemini-4-argon-cyber-permissive"))
        self.assertIsNone(self.reason("vertex", "gemini-3.9-flash"))
        self.assertIsNone(self.reason("vertex", "gemini-omni-1.2-flash"))

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

    def test_bedrock_geo_and_inregion_claude(self):
        floors = {
            "claude-fable": (5, 0),
            "claude-opus": (4, 5),
            "claude-sonnet": (4, 5),
            "claude-haiku": (4, 5),
        }
        known = set()
        def reason(mid, entry=None):
            return sp.enroll_reason("bedrock", mid, entry or chat(), known, floors)
        self.assertIsNone(reason("us.anthropic.claude-sonnet-4-6"))
        self.assertIsNone(reason("anthropic.claude-sonnet-4-6"))
        self.assertIsNone(reason("eu.anthropic.claude-haiku-4-5-20251001-v1:0"))
        self.assertIsNone(reason("global.anthropic.claude-opus-4-8"))
        self.assertEqual(reason("us-gov.anthropic.claude-sonnet-4-6"), "gov-region")
        self.assertEqual(reason("anthropic.claude-3-opus-20240229-v1:0"),
                         "outside-include")
        self.assertEqual(reason("claude-sonnet-4-5-20250929-v1:0"),
                         "outside-include")
        self.assertEqual(reason("us.anthropic.claude-opus-4-1"), "below-floor")
        self.assertEqual(reason("meta.llama3-1-70b"), "outside-include")


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

    def test_bedrock_inregion_takes_geo_rates_and_keeps_global(self):
        models = []
        idx = {
            "bedrock_converse": {
                "anthropic.claude-sonnet-4-6": (
                    "anthropic.claude-sonnet-4-6",
                    chat(prompt=3, completion=15, cache_read=0.3, cache_write=3.75)),
                "us.anthropic.claude-sonnet-4-6": (
                    "us.anthropic.claude-sonnet-4-6",
                    chat(prompt=3.3, completion=16.5, cache_read=0.33, cache_write=4.125)),
                "eu.anthropic.claude-sonnet-4-6": (
                    "eu.anthropic.claude-sonnet-4-6",
                    chat(prompt=3.3, completion=16.5, cache_read=0.33, cache_write=4.125)),
                "global.anthropic.claude-sonnet-4-6": (
                    "global.anthropic.claude-sonnet-4-6",
                    chat(prompt=3, completion=15, cache_read=0.3, cache_write=3.75)),
                "us-gov.anthropic.claude-sonnet-4-6": (
                    "us-gov.anthropic.claude-sonnet-4-6",
                    chat(prompt=3.6, completion=18, cache_read=0.36, cache_write=4.5)),
                "anthropic.claude-opus-4-1": (
                    "anthropic.claude-opus-4-1",
                    chat(prompt=15, completion=75)),
            }
        }
        added = sp.enroll_new_models(
            "bedrock", models, idx, {},
            registry_dir=os.path.dirname(HERE))
        # floors_from anthropic.json in this checkout
        by_id = {m["model"]: m for m in models}
        self.assertIn("anthropic.claude-sonnet-4-6", added)
        self.assertIn("us.anthropic.claude-sonnet-4-6", added)
        self.assertIn("global.anthropic.claude-sonnet-4-6", added)
        self.assertNotIn("us-gov.anthropic.claude-sonnet-4-6", by_id)
        self.assertNotIn("anthropic.claude-opus-4-1", by_id)
        inregion = by_id["anthropic.claude-sonnet-4-6"]
        self.assertEqual(inregion["prompt_per_1m"], 3.3)
        self.assertEqual(inregion["completion_per_1m"], 16.5)
        self.assertEqual(inregion["cache_read_per_1m"], 0.33)
        self.assertEqual(inregion["cache_write_per_1m"], 4.125)
        self.assertEqual(inregion["pricing_style"], "anthropic")
        self.assertEqual(inregion["source"], "litellm")
        self.assertEqual(by_id["global.anthropic.claude-sonnet-4-6"]["prompt_per_1m"], 3)
        self.assertEqual(by_id["us.anthropic.claude-sonnet-4-6"]["prompt_per_1m"], 3.3)

    def test_bedrock_prefers_dated_foundation_model_id(self):
        models = []
        idx = {
            "bedrock_converse": {
                "us.anthropic.claude-haiku-4-5": (
                    "us.anthropic.claude-haiku-4-5", chat(prompt=1.1, completion=5.5)),
                "us.anthropic.claude-haiku-4-5-20251001-v1:0": (
                    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                    chat(prompt=1.1, completion=5.5)),
            }
        }
        added = sp.enroll_new_models(
            "bedrock", models, idx, {},
            registry_dir=os.path.dirname(HERE))
        self.assertEqual(added, ["us.anthropic.claude-haiku-4-5-20251001-v1:0"])


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


class AllProviderFactsTest(unittest.TestCase):
    def test_slash_and_free_and_dot_spellings(self):
        self.assertEqual(sp.bare_model_id("deepseek-ai/deepseek-v4-flash"),
                         "deepseek-v4-flash")
        self.assertEqual(sp.bare_model_id("deepseek-v4-flash-free"),
                         "deepseek-v4-flash")
        self.assertEqual(sp.first_party_owner("deepseek-ai/deepseek-v4-flash"),
                         "deepseek")
        self.assertEqual(sp.first_party_owner("deepseek-v4-flash-free"), "deepseek")
        self.assertTrue(sp.is_foreign_copy("siliconflow",
                                           "deepseek-ai/deepseek-v4-flash"))
        self.assertFalse(sp.is_foreign_copy("deepseek", "deepseek-v4-flash"))
        keys = sp.first_party_keys("deepseek-ai/deepseek-v4-flash")
        self.assertIn("deepseek-v4-flash", keys)
        keys = sp.first_party_keys("deepseek-v4-flash-free")
        self.assertIn("deepseek-v4-flash", keys)
        keys = sp.first_party_keys("claude-opus-4.5")
        self.assertIn("claude-opus-4-5", keys)
        keys = sp.first_party_keys("kimi-k3")
        self.assertIn("k3", keys)
        keys = sp.first_party_keys("us.anthropic.claude-haiku-4-5-20251001-v1:0")
        self.assertIn("claude-haiku-4-5-20251001", keys)
        self.assertIn("claude-haiku-4-5", keys)
        self.assertEqual(
            sp.first_party_owner("us.anthropic.claude-sonnet-4-6"), "anthropic")
        self.assertTrue(sp.is_foreign_copy(
            "bedrock", "anthropic.claude-sonnet-4-6"))

    def test_lookup_slash_id_hits_first_party(self):
        first_party = {
            "deepseek-v4-flash": {
                "context_window": 1000000,
                "input_modalities": ["text", "image"],
                "effort_levels": ["low", "high", "max"],
                "surface": "chat",
            },
        }
        facts = sp.lookup_facts("deepseek-ai/deepseek-v4-flash", first_party)
        self.assertEqual(facts["context_window"], 1000000)
        self.assertEqual(facts["input_modalities"], ["text", "image"])
        facts = sp.lookup_facts("deepseek-v4-flash-free", first_party)
        self.assertEqual(facts["context_window"], 1000000)

    def test_reseller_overwrites_stale_window_first_party_does_not(self):
        facts = {
            "context_window": 1000000,
            "input_modalities": ["text", "image"],
        }
        stale = {
            "model": "deepseek-ai/deepseek-v4-flash",
            "context_window": 200000,
            "input_modalities": ["text"],
        }
        changes = {f: after for f, _, after in sp.apply_catalog_facts(
            stale, facts, sp.FIRST_PARTY_FACTS, overwrite=True)}
        self.assertEqual(changes["context_window"], 1000000)
        self.assertEqual(changes["input_modalities"], ["text", "image"])
        owner = {
            "model": "deepseek-v4-flash",
            "context_window": 200000,
            "input_modalities": ["text"],
        }
        self.assertEqual(
            sp.apply_catalog_facts(owner, facts, sp.FIRST_PARTY_FACTS,
                                   overwrite=False),
            [])

    def test_dated_pin_does_not_replace_floating_id_in_index(self):
        index = {}
        sp.remember_first_party(index, "xai", [
            {
                "model": "grok-4.20-multi-agent",
                "context_window": 1000000,
                "surface": "chat",
            },
            {
                "model": "grok-4.20-multi-agent-0309",
                "context_window": 2000000,
                "surface": "chat",
            },
        ])
        self.assertEqual(index["grok-4.20-multi-agent"]["context_window"], 1000000)
        self.assertEqual(index["grok-4.20-multi-agent-0309"]["context_window"], 2000000)
        self.assertEqual(
            sp.lookup_facts("grok-4.20-multi-agent", index)["context_window"],
            1000000)
        self.assertEqual(
            sp.lookup_facts("grok-4.20-multi-agent-0309", index)["context_window"],
            2000000)


def host_row(context, output):
    return sp.facts_from_models_dev_model(
        {"limit": {"context": context, "output": output},
         "modalities": {"output": ["text"]}})


class OutputCeilingTest(unittest.TestCase):
    def test_placeholder_outputs_are_not_ceilings(self):
        self.assertIsNone(sp.positive_output_limit({"limit": {"output": 0}}))
        self.assertIsNone(sp.positive_output_limit({"limit": {"output": 1}}))
        self.assertEqual(sp.positive_output_limit({"limit": {"output": 64000}}), 64000)
        self.assertNotIn("output_ceiling", host_row(2048, 1))
        self.assertEqual(host_row(1000000, 65536)["output_ceiling"], 65536)

    def test_publisher_beats_a_host_that_only_serves_the_weights(self):
        host_facts = {
            "moonshotai": {"kimi-k3": host_row(1048576, 1048576)},
            "moonshotai-cn": {"kimi-k3": host_row(1048576, 1048576)},
            "nvidia": {"moonshotai/kimi-k3": host_row(1048576, 131072)},
            "alibaba": {"kimi-k3": host_row(1048576, 1048576)},
        }
        ceilings, _blocked = sp.index_output_ceilings(host_facts)
        self.assertEqual(ceilings["kimi-k3"], 1048576)
        self.assertEqual(ceilings["k3"], 1048576)
        self.assertEqual(sp.lookup_output_ceiling("k3", ceilings), 1048576)

    def test_publisher_split_drops_the_id(self):
        host_facts = {
            "moonshotai": {"kimi-k3": host_row(1048576, 1048576)},
            "moonshotai-cn": {"kimi-k3": host_row(1048576, 131072)},
            "some-aggregator": {"kimi-k3": host_row(1048576, 1048576)},
        }
        ceilings, blocked = sp.index_output_ceilings(host_facts)
        self.assertNotIn("k3", ceilings)
        self.assertIn("k3", blocked)

    def test_unanimous_aggregators_fill_when_the_publisher_is_silent(self):
        host_facts = {
            "ollama-cloud": {"gemma4:31b": host_row(262144, 32768)},
            "opencode": {"gemma4:31b": host_row(262144, 32768)},
        }
        ceilings, _blocked = sp.index_output_ceilings(host_facts)
        self.assertEqual(ceilings["gemma4:31b"], 32768)

    def test_aggregator_split_stays_blank_until_the_surface_speaks(self):
        host_facts = {
            "ollama-cloud": {"gemma4:31b": host_row(262144, 32768)},
            "opencode": {"gemma4:31b": host_row(262144, 262144)},
        }
        ceilings, _blocked = sp.index_output_ceilings(host_facts)
        self.assertNotIn("gemma4:31b", ceilings)
        blank = {"model": "gemma4:31b"}
        self.assertEqual(
            sp.models_dev_output_ceiling(
                blank, "gemma4:31b", ceilings, host_facts["ollama-cloud"]),
            32768)
        filled = {"model": "gemma4:31b", "output_ceiling": 8192}
        self.assertIsNone(sp.models_dev_output_ceiling(
            filled, "gemma4:31b", ceilings, host_facts["ollama-cloud"]))

    def test_embedding_width_is_not_a_response_cap(self):
        row = {"model": "text-embedding-3-small", "surface": "embedding"}
        self.assertIsNone(sp.models_dev_output_ceiling(
            row, row["model"], {"text-embedding-3-small": 1536}, {}))

    def test_publisher_placeholder_blocks_an_aggregator_dimension(self):
        # Gemini Embedding's own row says output 1, which is not a generation
        # cap. An aggregator calling that 4096 must not become output_ceiling.
        host_facts = {
            "google": {"gemini-embedding-001": host_row(2048, 1)},
            "merge-gateway": {
                "google/gemini-embedding-001": host_row(2048, 4096)},
        }
        ceilings, blocked = sp.index_output_ceilings(host_facts)
        self.assertNotIn("gemini-embedding-001", ceilings)
        self.assertIn("gemini-embedding-001", blocked)

    def test_doubao_reads_volcengine_not_a_reseller_copy(self):
        host_facts = {
            "volcengine": {"doubao-seed-evolving": host_row(256000, 256000)},
            "volcengine-coding-plan": {
                "doubao-seed-evolving": host_row(256000, 256000)},
            "requesty": {"doubao-seed-evolving": host_row(256000, 128000)},
        }
        ceilings, _blocked = sp.index_output_ceilings(host_facts)
        self.assertEqual(ceilings["doubao-seed-evolving"], 256000)

    def test_exact_floating_id_beats_a_dated_pin_and_a_split_stays_blank(self):
        host_facts = {
            "volcengine": {
                "doubao-seed-2-1-pro-260628": host_row(256000, 256000),
                "doubao-seed-2-0-mini-260428": host_row(256000, 131072),
                "doubao-seed-2-0-lite-260428": host_row(256000, 131072),
                "doubao-seed-2-1-pro-260101": host_row(256000, 64000),
            },
            "volcengine-coding-plan": {
                "doubao-seed-2.0-lite": host_row(256000, 32000),
            },
            "requesty": {
                "doubao-seed-2-1-lite-260628": host_row(256000, 99999),
            },
        }
        ceilings, _blocked = sp.index_output_ceilings(host_facts)
        # Two dated pins of 2.1-pro disagree, so the floating id stays blank.
        self.assertNotIn("doubao-seed-2.1-pro", ceilings)
        self.assertEqual(
            sp.lookup_output_ceiling("doubao-seed-2.0-mini", ceilings), 131072)
        self.assertEqual(ceilings["doubao-seed-2.0-lite"], 32000)
        self.assertEqual(
            sp.lookup_output_ceiling("doubao-seed-2-0-lite", ceilings), 32000)
        self.assertNotIn("doubao-seed-2.1-lite", ceilings)

    def test_dated_pins_that_agree_fill_both_spellings(self):
        host_facts = {
            "volcengine": {
                "doubao-seed-2-1-pro-260628": host_row(256000, 256000),
            },
        }
        ceilings, _blocked = sp.index_output_ceilings(host_facts)
        self.assertEqual(ceilings["doubao-seed-2.1-pro"], 256000)
        self.assertEqual(ceilings["doubao-seed-2-1-pro"], 256000)

    def test_speed_tier_copies_the_sibling_ceiling_only(self):
        models = [
            {"model": "minimax-m2.1", "output_ceiling": 8192, "surface": "chat"},
            {"model": "minimax-m2.1-highspeed", "surface": "chat"},
            {"model": "minimax-m2.7-highspeed", "output_ceiling": 131072,
             "surface": "chat"},
            {"model": "orphan-highspeed", "surface": "chat"},
        ]
        changes = sp.inherit_speed_tier_ceilings(models, {})
        self.assertEqual(
            [(m["model"], ceiling) for m, _, ceiling in changes],
            [("minimax-m2.1-highspeed", 8192)])
        self.assertNotIn("output_ceiling", models[1])

    def test_family_ceiling_is_all_or_nothing(self):
        entries = [{
            "model": "glm-5",
            "variants": {"suffixes": ["", "-thinking"]},
        }]
        partial = sp.applicable_ceiling_updates(
            entries, {"glm-5": 131072})
        self.assertEqual(partial, {})
        full = sp.applicable_ceiling_updates(
            entries, {"glm-5": 131072, "glm-5-thinking": 131072})
        self.assertEqual(full, {"glm-5": 131072, "glm-5-thinking": 131072})
        self.assertTrue(sp.assign_stored_ceilings(entries, full))
        self.assertEqual(entries[0]["output_ceiling"], 131072)


    def test_vendor_host_alone_does_not_beat_a_conflicting_ordinary_host(self):
        # Moonshot silent; NVIDIA (VENDOR_HOSTS) and Requesty disagree.
        host_facts = {
            "nvidia": {"moonshotai/kimi-k9": host_row(1048576, 10000)},
            "requesty": {"kimi-k9": host_row(1048576, 20000)},
        }
        ceilings, blocked = sp.index_output_ceilings(host_facts)
        self.assertNotIn("k9", ceilings)
        self.assertNotIn("kimi-k9", ceilings)
        self.assertFalse(blocked)

    def test_publisher_split_blocks_surface_fallback(self):
        host_facts = {
            "moonshotai": {"kimi-k3": host_row(1048576, 1048576)},
            "moonshotai-cn": {"kimi-k3": host_row(1048576, 131072)},
        }
        ceilings, blocked = sp.index_output_ceilings(host_facts)
        self.assertNotIn("k3", ceilings)
        self.assertIn("k3", blocked)
        blank = {"model": "kimi-k3"}
        surface = {"kimi-k3": host_row(1048576, 1048576)}
        self.assertIsNone(sp.models_dev_output_ceiling(
            blank, "kimi-k3", ceilings, surface, blocked))


class MimoSpecParserTest(unittest.TestCase):
    def test_every_table_is_read_and_a_later_one_does_not_wipe_lengths(self):
        import sync_mimo

        page = """
        <table><tr><td>`mimo-v2.6-pro`</td>
        <td>Context Window: 1M</td><td>Maximum Output: 128K</td></tr></table>
        <table><tr><td>`mimo-v2.5-asr`</td>
        <td>Context Window: 8k</td><td>Maximum Output: 2k</td></tr></table>
        <table>
        <tr><td>`mimo-v2.5-tts`</td><td>Speech Synthesis</td>
        <td rowspan="3">Context Window: 8K Maximum Output: 8K</td></tr>
        <tr><td>`mimo-v2.5-tts-voiceclone`</td><td>Timbre Cloning</td></tr>
        <tr><td>`mimo-v2.5-tts-voicedesign`</td><td>Timbre Design</td></tr>
        </table>
        <table><tr><td>`mimo-v2.5-asr` `mimo-v2.5-tts`</td>
        <td>RPM 60</td></tr></table>
        <table><tr><td>`mimo-v2-omni`</td><td>no length here</td></tr></table>
        """
        specs = sync_mimo.parse_model_specs(page)
        self.assertEqual(specs["mimo-v2.6-pro"]["context_window"], 1048576)
        self.assertEqual(specs["mimo-v2.6-pro"]["output_ceiling"], 128000)
        self.assertEqual(specs["mimo-v2.5-asr"]["context_window"], 8192)
        self.assertEqual(specs["mimo-v2.5-asr"]["output_ceiling"], 2000)
        self.assertNotIn("input_modalities", specs["mimo-v2.5-asr"])
        self.assertEqual(specs["mimo-v2.5-tts"]["output_ceiling"], 8000)
        self.assertEqual(specs["mimo-v2.5-tts-voiceclone"]["context_window"], 8192)
        self.assertEqual(specs["mimo-v2.5-tts-voiceclone"]["output_ceiling"], 8000)
        self.assertEqual(specs["mimo-v2.5-tts-voicedesign"]["output_ceiling"], 8000)
        self.assertNotIn("output_ceiling", specs["mimo-v2-omni"])
        self.assertNotIn("context_window", specs["mimo-v2-omni"])


if __name__ == "__main__":
    unittest.main()
