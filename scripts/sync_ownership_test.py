"""A daily LiteLLM pass must respect a direct vendor catalog's ownership."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_prices as sp


class VendorOwnershipTest(unittest.TestCase):
    def sync_row(self, provider, row, upstream):
        with tempfile.TemporaryDirectory() as directory:
            providers = Path(directory) / "providers"
            providers.mkdir()
            path = providers / f"{provider}.json"
            path.write_text(json.dumps({"name": provider, "models": [row]}))
            with patch.object(sp, "regenerate_bundle"):
                result = sp.sync(directory, upstream, {}, apply=True)
            return result, json.loads(path.read_text())["models"][0]

    def test_direct_api_rows_are_not_litellm_orphans(self):
        row = {"model": "openai/gpt-test", "source": "vendor-api",
               "prompt_per_1m": 7, "context_window": 12345}
        result, after = self.sync_row("vercel", row, {})
        self.assertEqual(result[2], [])
        self.assertEqual(result[5]["vendor-api"], 1)
        self.assertEqual(after, row)

    def test_matching_litellm_row_cannot_overwrite_direct_api_facts(self):
        row = {"model": "gpt-test", "source": "vendor-api",
               "prompt_per_1m": 7, "context_window": 12345}
        upstream = {"gpt-test": {"litellm_provider": "openai",
                    "input_cost_per_token": 0.000001, "max_input_tokens": 99999}}
        with patch.dict(sp.NAMESPACES, {"vercel": ["openai"]}):
            result, after = self.sync_row("vercel", row, upstream)
        self.assertEqual(result[0], [])
        self.assertEqual(after, row)

    def test_derived_api_rows_still_report_missing_vendor(self):
        row = {"model": "claude-missing", "source": "vendor-api"}
        result, _ = self.sync_row("kiro", row, {})
        self.assertEqual(result[2], [("kiro", "claude-missing")])

    def test_derived_api_rows_still_take_vendor_prices(self):
        row = {"model": "claude-sonnet-4", "source": "vendor-api",
               "prompt_per_1m": 7}
        upstream = {"claude-sonnet-4-20250514": {
            "litellm_provider": "anthropic", "input_cost_per_token": 0.000003}}
        result, after = self.sync_row("kiro", row, upstream)
        self.assertEqual(result[2], [])
        self.assertEqual(after["prompt_per_1m"], 3)

    def test_inherited_image_price_is_not_reported_as_zero_dollars(self):
        row = {"model": "grok-test", "source": "manual", "prompt_per_1m": 2}
        upstream = {"xai/grok-test": {"litellm_provider": "xai",
                    "input_cost_per_token": 0.000002,
                    "input_cost_per_image_token": 0.000002}}
        result, _ = self.sync_row("xai", row, upstream)
        self.assertEqual(result[1], [])
        upstream["xai/grok-test"]["input_cost_per_image_token"] = 0.000003
        result, _ = self.sync_row("xai", row, upstream)
        self.assertEqual(len(result[1]), 1)
        self.assertEqual(result[1][0][3], "image_in_per_1m")


if __name__ == "__main__":
    unittest.main()
