#!/usr/bin/env python3
"""Sync MiMo first-party model specifications and pricing from official documentation.

Fetches facts directly from:
- https://mimo.mi.com/static/docs/price/pay-as-you-go.md (pricing)
- https://mimo.mi.com/static/docs/quick-start/summary/model.md (context, output limit, capabilities)
- https://mimo.mi.com/static/docs/quick-start/usage-guide/text-generation/deep-thinking.md (reasoning effort support)
- https://mimo.mi.com/static/docs/api/chat/openai-api.md (modalities and parameters)

Updates providers/mimo.json with list prices and capabilities, and propagates
facts across other providers (like opencode-go) via first-party sync rules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIMO_JSON = ROOT / "providers" / "mimo.json"

DOC_PRICING = "https://mimo.mi.com/static/docs/price/pay-as-you-go.md"
DOC_MODELS = "https://mimo.mi.com/static/docs/quick-start/summary/model.md"
DOC_THINKING = "https://mimo.mi.com/static/docs/quick-start/usage-guide/text-generation/deep-thinking.md"
DOC_OPENAI = "https://mimo.mi.com/static/docs/api/chat/openai-api.md"

def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ai-model-registry/1.0)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")

def parse_pricing_tables(text: str) -> dict[str, dict[str, float]]:
    """Parse Overseas Pricing (USD) language models table."""
    pos = text.find("Overseas Pricing")
    if pos == -1:
        pos = text.find("dollar / M tokens")
    if pos == -1:
        raise ValueError("Could not locate Overseas Pricing section in pay-as-you-go.md")

    table_end = text.find("</table>", pos)
    table_text = text[pos:table_end]

    prices: dict[str, dict[str, float]] = {}
    rows = table_text.split("<tr>")
    for r in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL)
        if not cells:
            continue
        clean_cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        model_cell = None
        price_cells = []
        for c in clean_cells:
            if "`mimo-" in c:
                model_cell = c
            elif "$" in c:
                price_cells.append(c)

        if not model_cell or len(price_cells) < 3:
            continue

        raw_models = re.findall(r"`(mimo-[a-zA-Z0-9\.\-_]+)`", model_cell)
        try:
            cache_read = float(price_cells[0].replace("$", "").strip())
            prompt = float(price_cells[1].replace("$", "").strip())
            completion = float(price_cells[2].replace("$", "").strip())
        except ValueError:
            continue

        for m in raw_models:
            if m not in prices:  # First occurrence is Real-time API
                prices[m] = {
                    "cache_read_per_1m": cache_read,
                    "prompt_per_1m": prompt,
                    "completion_per_1m": completion,
                    "cache_write_per_1m": 0,
                }

    return prices

def _scaled(val: int, unit: str, *, binary_k: bool) -> int:
    unit = (unit or "").upper()
    if unit == "M":
        return 1048576 if val == 1 else val * 1000000
    if unit == "K":
        # Output caps in this registry are decimal K (128K -> 128000). Context
        # windows are binary K, which is what the model card's 8K ASR window is.
        return val * 1024 if binary_k else val * 1000
    return val


def parse_model_specs(text: str, openai_text: str = "") -> dict[str, dict]:
    """Parse model capabilities and limits from model.md and openai-api.md.

    The page has one table per family (chat, ASR, TTS, then a rate-limit table
    that names the same ids and states no length). Reading only up to the first
    ``</table>`` dropped ASR and TTS, so the hourly sync never wrote their
    Maximum Output. TTS states the length once, in a rowspan that also covers
    voice clone and voice design. A later table that does not repeat the
    length must not wipe a length an earlier table stated, and a missing
    length is not 128K.
    """
    specs: dict[str, dict] = {}
    # Check multi-modality mentions in openai doc
    # e.g. "Currently, the mimo-v2.6-flash, mimo-v2.6-pro, mimo-v2.6-pro-ultraspeed and mimo-v2.5 models support image, audio or video input"
    omni_models = set(re.findall(r"`(mimo-[a-zA-Z0-9\.\-_]+)` models? support image, audio or video input", openai_text))

    # A rowspan cell states the length once for several model rows (TTS,
    # voice clone, voice design share one "Maximum Output: 8K"). The carry
    # lasts only for the rows that cell spans, and a later table that names
    # the same ids without a length must not wipe it or invent 128K.
    carry_left = 0
    carried_context = None
    carried_output = None

    rows = text.split("<tr>")
    for r in rows:
        raw_cells = re.findall(r"<td([^>]*)>(.*?)</td>", r, re.DOTALL)
        if not raw_cells:
            continue
        clean_cells = [re.sub(r"<[^>]+>", " ", body).strip() for _, body in raw_cells]
        raw_models = re.findall(r"`(mimo-[a-zA-Z0-9\.\-_]+)`", clean_cells[0])
        if not raw_models:
            if carry_left:
                carry_left -= 1
            continue

        context_window = None
        output_ceiling = None
        has_omni = False
        span = 1

        for attrs, body in raw_cells:
            c = re.sub(r"<[^>]+>", " ", body)
            if "Full-modal" in c or "full-modal" in c:
                has_omni = True
            stated = False
            ctx_match = re.search(r"Context Window:\s*([0-9]+)\s*([KMkm])?", c)
            if ctx_match:
                context_window = _scaled(int(ctx_match.group(1)), ctx_match.group(2), binary_k=True)
                stated = True
            out_match = re.search(r"Maximum Output:\s*([0-9]+)\s*([KMkm])?", c)
            if out_match:
                output_ceiling = _scaled(int(out_match.group(1)), out_match.group(2), binary_k=False)
                stated = True
            span_match = re.search(r'rowspan="(\d+)"', attrs)
            if stated and span_match:
                span = max(span, int(span_match.group(1)))

        if context_window or output_ceiling:
            if span > 1:
                carry_left = span - 1
                carried_context = context_window
                carried_output = output_ceiling
            else:
                carry_left = 0
        elif carry_left > 0:
            context_window = carried_context
            output_ceiling = carried_output
            carry_left -= 1

        for m in raw_models:
            prev = specs.get(m, {})
            # A length row is not a modality list. Defaulting these to text
            # turned the ASR model into a text model. Only a row that actually
            # says full-modal, or the v2.6 family the card describes that way,
            # publishes modalities.
            modalities = None
            if has_omni or m in omni_models or m.startswith("mimo-v2.6"):
                modalities = ["text", "image", "audio", "video"]
            elif prev.get("input_modalities"):
                modalities = prev["input_modalities"]
            entry = {}
            if modalities:
                entry["input_modalities"] = modalities
            if context_window:
                entry["context_window"] = context_window
            elif prev.get("context_window"):
                entry["context_window"] = prev["context_window"]
            if output_ceiling:
                entry["output_ceiling"] = output_ceiling
            elif prev.get("output_ceiling"):
                entry["output_ceiling"] = prev["output_ceiling"]
            specs[m] = entry

    return specs

def parse_reasoning_models(thinking_text: str) -> set[str]:
    """Parse models supporting thinking from deep-thinking.md."""
    return set(re.findall(r"`(mimo-[a-zA-Z0-9\.\-_]+)`", thinking_text))

def sync_mimo(check: bool = False) -> tuple[int, list[str]]:
    print("Fetching official MiMo documentation...")
    pricing_text = fetch_url(DOC_PRICING)
    models_text = fetch_url(DOC_MODELS)
    thinking_text = fetch_url(DOC_THINKING)
    openai_text = fetch_url(DOC_OPENAI)

    prices = parse_pricing_tables(pricing_text)
    specs = parse_model_specs(models_text, openai_text)
    thinking_models = parse_reasoning_models(thinking_text)

    # Standard MiMo effort levels
    standard_efforts = ["low", "medium", "high"]

    with open(MIMO_JSON, "r", encoding="utf-8") as f:
        mimo_data = json.load(f)

    existing_by_id = {m["model"]: m for m in mimo_data.get("models", [])}
    changes = []

    # Audio/voice models from official docs
    audio_models = {
        "mimo-v2.5-asr": {"surface": None, "effort_levels": ["none"]},
        "mimo-v2.5-tts": {"surface": "audio", "effort_levels": ["none"]},
        "mimo-v2.5-tts-voiceclone": {"surface": "audio", "effort_levels": ["none"]},
        "mimo-v2.5-tts-voicedesign": {"surface": "audio", "effort_levels": ["none"]},
    }

    # Desired order: v2.6 series, v2.5 series, audio series
    model_order = [
        "mimo-v2.6-pro",
        "mimo-v2.6-flash",
        "mimo-v2.6-pro-ultraspeed",
        "mimo-v2.5",
        "mimo-v2.5-pro",
        "mimo-v2.5-asr",
        "mimo-v2.5-tts",
        "mimo-v2.5-tts-voiceclone",
        "mimo-v2.5-tts-voicedesign",
    ]

    all_model_ids = list(dict.fromkeys(model_order + list(prices.keys())))
    updated_models = []

    for m_id in all_model_ids:
        cur = existing_by_id.get(m_id, {})
        entry = {"model": m_id, "pricing_style": "openai"}

        # Pricing
        if m_id in prices:
            p = prices[m_id]
            entry["prompt_per_1m"] = p["prompt_per_1m"]
            entry["completion_per_1m"] = p["completion_per_1m"]
            entry["cache_read_per_1m"] = p["cache_read_per_1m"]
            entry["cache_write_per_1m"] = p["cache_write_per_1m"]
        else:
            entry["prompt_per_1m"] = cur.get("prompt_per_1m", 0)
            entry["completion_per_1m"] = cur.get("completion_per_1m", 0)
            entry["cache_read_per_1m"] = cur.get("cache_read_per_1m", 0)
            entry["cache_write_per_1m"] = cur.get("cache_write_per_1m", 0)

        entry["source"] = "manual"

        # Specs
        sp = specs.get(m_id, {})
        if sp.get("context_window"):
            entry["context_window"] = sp["context_window"]
        elif "context_window" in cur:
            entry["context_window"] = cur["context_window"]

        if sp.get("output_ceiling"):
            entry["output_ceiling"] = sp["output_ceiling"]
        elif "output_ceiling" in cur:
            entry["output_ceiling"] = cur["output_ceiling"]

        # Reasoning effort levels
        if m_id in thinking_models:
            entry["effort_levels"] = standard_efforts
        elif m_id in audio_models:
            entry["effort_levels"] = audio_models[m_id]["effort_levels"]
        elif "effort_levels" in cur:
            entry["effort_levels"] = cur["effort_levels"]

        # Surface. ASR's card has a context window and no chat route; a parsed
        # length must not reclassify it as chat. audio_models records "audio"
        # where the route is known and leaves ASR on whatever the file already
        # says.
        if m_id in audio_models:
            if audio_models[m_id]["surface"]:
                entry["surface"] = audio_models[m_id]["surface"]
            elif cur.get("surface"):
                entry["surface"] = cur["surface"]
        elif m_id in prices or (sp and sp.get("context_window")):
            entry["surface"] = "chat"
        elif "surface" in cur:
            entry["surface"] = cur["surface"]

        # Modalities
        if sp.get("input_modalities"):
            entry["input_modalities"] = sp["input_modalities"]
        elif "input_modalities" in cur:
            entry["input_modalities"] = cur["input_modalities"]
        elif m_id.startswith("mimo-v2.6"):
            entry["input_modalities"] = ["text", "image", "audio", "video"]

        # Clean None values
        entry = {k: v for k, v in entry.items() if v is not None}

        if cur != entry:
            if not cur:
                changes.append(f"Added model: {m_id}")
            else:
                diff_keys = [k for k in set(entry) | set(cur) if entry.get(k) != cur.get(k)]
                changes.append(f"Updated {m_id}: {', '.join(diff_keys)}")

        updated_models.append(entry)

    mimo_data["models"] = updated_models

    if changes and not check:
        with open(MIMO_JSON, "w", encoding="utf-8") as f:
            json.dump(mimo_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Updated {MIMO_JSON} with {len(changes)} change(s).")
    elif changes:
        print(f"Check mode: {len(changes)} change(s) detected.")
    else:
        print("mimo.json is already up to date with official specs.")

    return len(changes), changes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report differences without writing")
    args = parser.parse_args()

    count, changes = sync_mimo(check=args.check)
    for c in changes:
        print("  -", c)
    if args.check and count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
