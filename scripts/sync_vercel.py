#!/usr/bin/env python3
"""Sync Vercel AI Gateway model specifications and pricing from official catalog.

Fetches facts directly from:
- https://ai-gateway.vercel.sh/v1/models (catalog models, pricing, context window, parameters)
- https://vercel.com/ai-gateway/models (capabilities, modality surfaces)

Updates providers/vercel.json with list prices, context windows, output limits,
modalities, and surfaces.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERCEL_JSON = ROOT / "providers" / "vercel.json"
MODELS_URL = "https://ai-gateway.vercel.sh/v1/models"

SURFACE_MAP = {
    "language": "chat",
    "evaluation": "decision",
    "decision": "decision",
    "image": "image",
    "video": "video",
    "embedding": "embedding",
    "reranking": "rerank",
    "speech": "audio",
    "transcription": "audio",
    "realtime": "audio",
}

def fetch_catalog() -> list[dict]:
    req = urllib.request.Request(MODELS_URL, headers={"Accept": "application/json", "User-Agent": "ai-model-registry/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
        return data.get("data", [])

def build_vercel_entry(row: dict) -> dict:
    mid = row.get("id", "").strip()
    m_type = row.get("type", "language")
    surface = SURFACE_MAP.get(m_type, "chat")

    p = row.get("pricing", {})
    inp = p.get("input")
    out = p.get("output")
    cache_read = p.get("input_cache_read")
    cache_write = p.get("input_cache_write")

    prompt_per_1m = round(float(inp) * 1_000_000, 6) if inp is not None else 0.0
    completion_per_1m = round(float(out) * 1_000_000, 6) if out is not None else 0.0
    cache_read_per_1m = round(float(cache_read) * 1_000_000, 6) if cache_read is not None else 0.0
    cache_write_per_1m = round(float(cache_write) * 1_000_000, 6) if cache_write is not None else 0.0

    entry = collections.OrderedDict()
    entry["model"] = mid
    entry["pricing_style"] = "openai"
    entry["prompt_per_1m"] = prompt_per_1m
    entry["completion_per_1m"] = completion_per_1m
    entry["cache_read_per_1m"] = cache_read_per_1m
    entry["cache_write_per_1m"] = cache_write_per_1m

    # Audio token splits and unit prices (per image, per generated-video
    # second, per speech character, per transcribed second) — the columns the
    # four token buckets cannot express. Scale choices stay conservative and
    # documented: the MIDDLE resolution where a vendor prices video per
    # resolution, and 1024x1024 where image prices key on size.
    if p.get("audio_input_token_cost") is not None:
        entry["audio_in_per_1m"] = round(float(p["audio_input_token_cost"]) * 1_000_000, 6)
    if p.get("audio_output_token_cost") is not None:
        entry["audio_out_per_1m"] = round(float(p["audio_output_token_cost"]) * 1_000_000, 6)
    if p.get("image") is not None:
        try:
            entry["per_image"] = round(float(p["image"]), 6)
        except (TypeError, ValueError):
            pass
    if p.get("speech_input_character_cost") is not None:
        entry["tts_per_1m_chars"] = round(float(p["speech_input_character_cost"]) * 1_000_000, 6)
    if p.get("transcription_duration_cost_per_second") is not None:
        entry["asr_per_second"] = round(float(p["transcription_duration_cost_per_second"]), 8)
    duration = p.get("video_duration_pricing")
    if isinstance(duration, list) and duration:
        by_res = {str(t.get("resolution")): t.get("cost_per_second") for t in duration if isinstance(t, dict)}
        pick = by_res.get("720p")
        if pick is None and len(duration) == 1:
            pick = duration[0].get("cost_per_second")
        if pick is not None:
            entry["video_per_second"] = round(float(pick), 6)
    dim = p.get("image_dimension_quality_pricing")
    if isinstance(dim, list) and dim and "per_image" not in entry:
        by_size = {str(t.get("size")): t.get("cost") for t in dim if isinstance(t, dict)}
        pick = by_size.get("1024x1024")
        if pick is None and len(dim) == 1:
            pick = dim[0].get("cost")
        if pick is not None:
            entry["per_image"] = round(float(pick), 6)

    # Time-tiered pricing: vercel's own shape is multiplier + UTC minute
    # windows with weekdays, published as rate_variants on the row (the base
    # card stays the off-peak list the fields above carry). The holiday
    # calendar a vendor states (peak_pricing.holiday_calendar) is beyond a
    # static condition; the variant prices holiday weekdays at peak, the one
    # imprecision this accepts.
    peak = p.get("peak_pricing")
    if isinstance(peak, dict) and peak.get("multiplier") and isinstance(peak.get("windows"), list):
        windows, weekdays = [], False
        for w in peak["windows"]:
            if not isinstance(w, dict):
                continue
            start, end = w.get("start_minute_utc"), w.get("end_minute_utc")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            windows += [start, end]
            if w.get("days_of_week") in ([1, 2, 3, 4, 5], None):
                weekdays = weekdays or w.get("days_of_week") == [1, 2, 3, 4, 5]
        if windows:
            variant = collections.OrderedDict()
            variant["name"] = "peak"
            variant["utc_window_minutes"] = windows
            if weekdays:
                variant["weekdays_only"] = True
            variant["multiplier"] = float(peak["multiplier"])
            entry["rate_variants"] = [variant]

    entry["source"] = "vendor-api"

    if inp is not None and float(inp) == 0.0 and float(out or 0.0) == 0.0:
        entry["free"] = True

    ctx = row.get("context_window", 0)
    if isinstance(ctx, int) and ctx > 0:
        entry["context_window"] = ctx

    max_tok = row.get("max_tokens", 0)
    if isinstance(max_tok, int) and max_tok > 0:
        entry["output_ceiling"] = max_tok

    input_mods = row.get("modalities", {}).get("input")
    if isinstance(input_mods, list) and input_mods:
        entry["input_modalities"] = input_mods

    effort_levels = []
    for opt in row.get("reasoning_options", []):
        if opt.get("type") == "effort":
            for val in opt.get("values", []):
                if isinstance(val, str) and val not in effort_levels:
                    effort_levels.append(val)
    if effort_levels:
        entry["effort_levels"] = effort_levels

    entry["surface"] = surface
    entry["price_reviewed"] = "Official pricing from vercel.com/ai-gateway/models and GET ai-gateway.vercel.sh/v1/models."

    return entry

def sync_vercel(check: bool = False) -> tuple[int, list[str]]:
    catalog = fetch_catalog()
    if not catalog:
        raise RuntimeError("Empty catalog fetched from Vercel AI Gateway")

    new_models = []
    seen = set()
    for row in catalog:
        mid = row.get("id", "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        new_models.append(build_vercel_entry(row))

    new_models.sort(key=lambda m: m["model"])

    existing_data = {}
    if VERCEL_JSON.exists():
        with open(VERCEL_JSON, encoding="utf-8") as f:
            existing_data = json.load(f)

    existing_models = {m["model"]: m for m in existing_data.get("models", [])}

    changes = []
    # Check for additions and updates
    for nm in new_models:
        mid = nm["model"]
        if mid not in existing_models:
            changes.append(f"Added model {mid}")
        else:
            em = existing_models[mid]
            for k, v in nm.items():
                if k == "price_reviewed":
                    continue
                if em.get(k) != v:
                    changes.append(f"Updated {mid} {k}: {em.get(k)} -> {v}")

    # Check for removals
    new_ids = {m["model"] for m in new_models}
    for emid in existing_models:
        if emid not in new_ids:
            changes.append(f"Removed model {emid}")

    if changes and not check:
        output_data = collections.OrderedDict([
            ("name", "vercel"),
            ("display_name", "Vercel AI Gateway"),
            ("list_prices", True),
            ("models", new_models),
        ])
        with open(VERCEL_JSON, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Updated {VERCEL_JSON} with {len(new_models)} models ({len(changes)} changes).")
        # Regenerate all.json bundle
        subprocess.run([sys.executable, str(ROOT / "scripts" / "bundle.py")], check=True)
    elif changes:
        print(f"Check mode: {len(changes)} change(s) detected.")
    else:
        print("vercel.json is already up to date with official catalog.")

    return len(changes), changes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report differences without writing")
    args = parser.parse_args()

    count, changes = sync_vercel(check=args.check)
    for c in changes[:20]:
        print("  -", c)
    if len(changes) > 20:
        print(f"  ... and {len(changes) - 20} more changes.")
    if args.check and count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
