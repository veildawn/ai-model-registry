#!/usr/bin/env python3
"""Generate all.json: every file this registry publishes, in one document.

This exists for the consumer's BOOT, not for anything a person reads. A client
that wants the whole registry over HTTP has to fetch index.json and then one
file per provider, because that is the layout — 21 sequential round trips today
for 140 KB of data, and one more every time a provider is added. The proxy's
boot sync gives the whole operation a 20 second budget, so that layout only
works while the average round trip stays under ~950ms; past that the sync times
out and the consumer silently falls back to its embedded snapshot, which is the
failure nobody notices because everything keeps serving, just from stale facts.

One GET of this bundle replaces all 21 and takes the round-trip count out of the
budget entirely.

It is GENERATED and committed. Never hand-edit it: `--check` fails CI when it
disagrees with the files it is built from, and the Go test in bundle_test.go
fails the build when parsing the bundle does not yield exactly the providers and
models that walking providers/*.json does.

The shape is a map from the registry-relative PATH to that file's parsed
content, which is deliberately the dullest thing that could work:

    {
      "version": 1,                        # the same version index.json states
      "generated_by": "scripts/bundle.py",
      "files": {
        "index.json":               {"version": 1, "providers": ["anthropic", ...]},
        "providers/anthropic.json": {"name", "display_name", "list_prices",
                                     "models", "hidden_models"},
        ...
      }
    }

Keying by path rather than by provider name is what lets a consumer serve the
bundle to the reader it ALREADY has: its per-file loader asks for a path, and
the bundle answers with that path's bytes, so the bundle needs no parser of its
own and cannot drift into a second dialect of the same data. The top-level
version repeats index.json's so a consumer can reject a bundle it does not
understand before parsing anything inside it.

Usage:
    python3 scripts/bundle.py            # write all.json
    python3 scripts/bundle.py --check    # write nothing; exit 1 if out of date
"""
import argparse
import collections
import glob
import json
import os
import sys

ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROVIDERS_DIR = os.path.join(ROOT, "providers")
INDEX = os.path.join(ROOT, "index.json")
BUNDLE = os.path.join(ROOT, "all.json")

# The key index.json takes inside the bundle. It is its own path, like every
# other entry: the bundle is addressed the way the directory is.
INDEX_KEY = "index.json"


def read_json(path: str):
    """Parse one registry file, keeping its key order so the bundle is stable."""
    resolved = os.path.realpath(path)
    if resolved != ROOT and not resolved.startswith(ROOT + os.sep):
        raise ValueError(f"refusing to read outside the registry: {path}")
    with open(resolved) as fh:
        return json.load(fh, object_pairs_hook=collections.OrderedDict)


def build() -> str:
    """The bundle's exact bytes, as they belong on disk."""
    index = read_json(INDEX)
    files = collections.OrderedDict()
    files[INDEX_KEY] = index

    # Every file on disk, not only the ones the index names. A provider file the
    # index has not been taught about yet is a bug the Go tests already catch;
    # dropping it here would turn that into a silent difference between the
    # bundle and the directory, which is the one thing this file must not have.
    for path in sorted(glob.glob(os.path.join(PROVIDERS_DIR, "*.json"))):
        resolved = os.path.realpath(path)
        if os.path.dirname(resolved) != PROVIDERS_DIR:
            continue
        name = os.path.basename(resolved)
        files["providers/" + name] = read_json(resolved)

    doc = collections.OrderedDict()
    doc["version"] = index.get("version")
    doc["generated_by"] = "scripts/bundle.py"
    doc["files"] = files
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def write(text: str) -> None:
    """Write the bundle, refusing any path that is not this repo's all.json."""
    target = os.path.realpath(BUNDLE) if os.path.exists(BUNDLE) else BUNDLE
    if os.path.dirname(target) != ROOT or os.path.basename(target) != "all.json":
        raise ValueError(f"refusing to write outside the registry: {target}")
    with open(target, "w") as fh:
        fh.write(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 when all.json is out of date")
    args = parser.parse_args()

    try:
        want = build()
    except Exception as err:  # a missing or malformed file — all the same here
        print(f"could not build the bundle: {err}", file=sys.stderr)
        return 2

    if args.check:
        try:
            with open(BUNDLE) as fh:
                have = fh.read()
        except FileNotFoundError:
            print("all.json is missing; run python3 scripts/bundle.py", file=sys.stderr)
            return 1
        if have != want:
            print("all.json is out of date; run python3 scripts/bundle.py",
                  file=sys.stderr)
            return 1
        print(f"all.json is current ({len(want)} bytes)")
        return 0

    write(want)
    print(f"wrote all.json ({len(want)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
