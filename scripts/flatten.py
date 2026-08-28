#!/usr/bin/env python3
"""Print the registry as a flat, sorted, per-model fact set.

This is the refactor's yardstick. Collapsing variant families changes how the
files are WRITTEN and must not change a single fact any consumer reads, so the
migration is verified by diffing this output across it — not by reading the
diff of the files themselves, which is the thing that is supposed to change.

    python3 scripts/flatten.py > /tmp/before.txt
    ...collapse...
    python3 scripts/flatten.py | diff /tmp/before.txt -   # must be empty

One line per (provider, model), every published fact on it, so a diff points at
the exact id and field that moved.
"""
import collections
import glob
import json
import os
import sys

PROVIDERS_DIR = os.path.realpath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "providers"))

# Every field a consumer can read off an entry. Order is fixed so two runs of
# this script are byte-comparable.
FIELDS = (
    "pricing_style",
    "prompt_per_1m",
    "completion_per_1m",
    "cache_read_per_1m",
    "cache_write_per_1m",
    "context_window",
    "input_modalities",
    "effort_levels",
    "surface",
    "aliases",
    "source",
)


def expand(entry, base_facts=None):
    """One stored entry as the per-id entries a consumer sees.

    A row with no `variants` is itself, which is every row before the collapse
    and most rows after it.
    """
    variants = entry.get("variants")
    if not variants:
        yield entry
        return

    overrides = {}
    for group in variants.get("overrides", []):
        patch = {k: v for k, v in group.items() if k != "suffixes"}
        for suffix in group.get("suffixes", []):
            overrides[suffix] = patch

    shared = {k: v for k, v in entry.items() if k not in ("variants", "model")}
    for suffix in variants.get("suffixes", []):
        row = dict(shared)
        row.update(overrides.get(suffix, {}))
        row["model"] = entry["model"] + suffix
        yield row


def rows():
    for path in sorted(glob.glob(os.path.join(PROVIDERS_DIR, "*.json"))):
        resolved = os.path.realpath(path)
        if os.path.dirname(resolved) != PROVIDERS_DIR:
            continue
        with open(resolved) as fh:
            doc = json.load(fh, object_pairs_hook=collections.OrderedDict)
        for entry in doc.get("models", []):
            for row in expand(entry):
                yield doc["name"], row


def main() -> int:
    out = []
    for provider, row in rows():
        facts = " ".join(
            f"{f}={json.dumps(row.get(f), sort_keys=True)}" for f in FIELDS)
        out.append(f"{provider}\t{row['model']}\t{facts}")
    duplicates = [k for k, n in collections.Counter(
        line.split("\t", 2)[:2].__str__() for line in out).items() if n > 1]
    for line in sorted(out):
        print(line)
    if duplicates:
        print(f"\nDUPLICATE (provider, model): {len(duplicates)}", file=sys.stderr)
        return 1
    print(f"\n{len(out)} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
