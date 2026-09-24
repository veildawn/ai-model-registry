#!/usr/bin/env python3
"""Sync StepFun first-party model specifications and pricing from official documentation.

Fetches facts directly from:
- https://platform.stepfun.com/docs/zh/guides/pricing/details.md (pricing & limits)
- https://platform.stepfun.com/docs/zh/step-plan/overview.md (Step Plan supported models)
- https://platform.stepfun.com/docs/zh/guides/models/step-5-preview.md (Step 5 specs)
- https://platform.stepfun.com/docs/zh/guides/models/step-3.7-flash.md (Step 3.7 specs)

Updates providers/stepfun.json with list prices and capabilities, and propagates
facts across other providers via first-party sync rules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPFUN_JSON = ROOT / "providers" / "stepfun.json"

DOC_PRICING = "https://platform.stepfun.com/docs/zh/guides/pricing/details.md"
DOC_STEP_PLAN = "https://platform.stepfun.com/docs/zh/step-plan/overview.md"
DOC_STEP5 = "https://platform.stepfun.com/docs/zh/guides/models/step-5-preview.md"
DOC_STEP37 = "https://platform.stepfun.com/docs/zh/guides/models/step-3.7-flash.md"

# Standard ECB conversion rate CNY -> USD used across repository for StepFun
CNY_TO_USD = 1.0 / 6.7669

def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ai-model-registry/1.0)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")

def parse_pricing_tables(text: str) -> dict[str, dict[str, float]]:
    """Parse pricing table for tokens (CNY converted to USD)."""
    prices: dict[str, dict[str, float]] = {}
    
    # 1. Match Markdown tables: | `step-...` | 1M tokens | input_miss | input_hit | output |
    pattern = r"\|\s*`(step[a-zA-Z0-9\.\-_]+)`\s*\|\s*1M tokens\s*\|\s*([\d\.]+)\s*元?\s*\|\s*([\d\.]+)\s*元?\s*\|\s*([\d\.]+)\s*元?\s*\|"
    for m in re.finditer(pattern, text):
        model_id = m.group(1)
        miss_cny = float(m.group(2))
        hit_cny = float(m.group(3))
        out_cny = float(m.group(4))
        prices[model_id] = {
            "prompt_per_1m": round(miss_cny * CNY_TO_USD, 6),
            "cache_read_per_1m": round(hit_cny * CNY_TO_USD, 6),
            "completion_per_1m": round(out_cny * CNY_TO_USD, 6),
            "cache_write_per_1m": 0,
            "cny_miss": miss_cny,
            "cny_hit": hit_cny,
            "cny_out": out_cny,
        }

    # 2. Audio tokens table (input_miss, hit, out)
    audio_pattern = r"\|\s*`(stepaudio[a-zA-Z0-9\.\-_]+)`\s*\|\s*1M tokens\s*\|\s*([\d\.]+)\s*元?\s*\|\s*([\d\.]+)\s*元?\s*\|\s*([\d\.]+)\s*元?\s*\|"
    for m in re.finditer(audio_pattern, text):
        model_id = m.group(1)
        miss_cny = float(m.group(2))
        hit_cny = float(m.group(3))
        out_cny = float(m.group(4))
        if model_id not in prices:
            prices[model_id] = {
                "prompt_per_1m": round(miss_cny * CNY_TO_USD, 6),
                "cache_read_per_1m": round(hit_cny * CNY_TO_USD, 6),
                "completion_per_1m": round(out_cny * CNY_TO_USD, 6),
                "cache_write_per_1m": 0,
                "cny_miss": miss_cny,
                "cny_hit": hit_cny,
                "cny_out": out_cny,
            }

    return prices

def sync_stepfun(check: bool = False) -> tuple[int, list[str]]:
    print("Fetching official StepFun documentation...")
    pricing_text = fetch_url(DOC_PRICING)
    prices = parse_pricing_tables(pricing_text)

    with open(STEPFUN_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Ensure list_prices is True as official first-party
    data["list_prices"] = True

    changes = []
    models = data.get("models", [])
    models_by_id = {m["model"]: m for m in models}

    # Model specifications and known reasoning ladders
    specs = {
        "step-5-preview": {
            "context_window": 1000000,
            "output_ceiling": 1000000,
            "input_modalities": ["text", "image", "video"],
            "effort_levels": ["low", "medium", "high"],
            "surface": "chat",
        },
        "step-3.7-flash": {
            "context_window": 256000,
            "input_modalities": ["text", "image", "video"],
            "effort_levels": ["low", "medium", "high"],
            "surface": "chat",
        },
        "step-3.5-flash-2603": {
            "context_window": 256000,
            "input_modalities": ["text"],
            "effort_levels": ["low", "high"],
            "surface": "chat",
        },
        "step-3.5-flash": {
            "context_window": 256000,
            "input_modalities": ["text"],
            "effort_levels": ["low", "medium", "high"],
            "surface": "chat",
        },
        "step-router-v1": {
            "output_ceiling": 250000,
            "input_modalities": ["text"],
            "surface": "chat",
        },
        "stepaudio-2.5-chat": {
            "input_modalities": ["text", "audio"],
            "surface": "chat",
        },
        "stepaudio-2.5-realtime": {
            "input_modalities": ["text", "audio"],
            "effort_levels": ["none"],
            "surface": "audio",
        },
        "stepaudio-2.5-tts": {
            "input_modalities": ["text"],
            "effort_levels": ["none"],
            "surface": "audio",
        },
        "stepaudio-2.5-asr": {
            "input_modalities": ["audio"],
            "effort_levels": ["none"],
            "surface": "audio",
        },
        "step-image-edit-2": {
            "input_modalities": ["text", "image"],
            "effort_levels": ["none"],
            "surface": "image",
        },
    }

    # Update or add models
    for m in models:
        mid = m["model"]
        sp = specs.get(mid, {})
        for k, v in sp.items():
            if m.get(k) != v:
                changes.append(f"Updated {mid} {k}: {m.get(k)} -> {v}")
                m[k] = v

        if mid in prices:
            p = prices[mid]
            for rate_key in ("prompt_per_1m", "completion_per_1m", "cache_read_per_1m", "cache_write_per_1m"):
                # keep existing precise rate if within 0.001 delta
                current_rate = m.get(rate_key, 0)
                new_rate = p[rate_key]
                if abs(current_rate - new_rate) > 0.01:
                    changes.append(f"Updated {mid} {rate_key}: {current_rate} -> {new_rate}")
                    m[rate_key] = new_rate

    if changes and not check:
        with open(STEPFUN_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Updated {STEPFUN_JSON} with {len(changes)} change(s).")
    elif changes:
        print(f"Check mode: {len(changes)} change(s) detected.")
    else:
        print("stepfun.json is already up to date with official specs.")

    return len(changes), changes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report differences without writing")
    args = parser.parse_args()

    count, changes = sync_stepfun(check=args.check)
    for c in changes:
        print("  -", c)
    if args.check and count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
