#!/usr/bin/env python3
"""Sync the rows an upstream owns; report on the rows we own.

Every model entry carries a `source`, and it decides who writes it:

    "litellm"     the vendor's own namespace carries this exact id. This script
                  overwrites the row's rates, context window and input
                  modalities from litellm on every run. Nobody edits these by
                  hand — an edit would be reverted the next morning, which is
                  the point: the row is delegated.
    "vendor-api"  a surface that publishes no rates of its own and meters at the
                  vendor's API list (kiro, antigravity). Written the same way,
                  from the vendor's row, after this surface's own suffixes are
                  stripped. Named apart from "litellm" because it is DERIVED:
                  someone auditing a bill needs to see which rows were read and
                  which were inferred.
    "cursor-docs" Cursor publishes its own per-model table as machine-readable
                  markdown, so its rates are READ from the reseller itself
                  rather than derived from a vendor. Capability facts still come
                  from the vendor's row, since a context window does not change
                  because a reseller fronts the model.
    "manual"      this script NEVER writes the row. It only reports when the
                  upstream disagrees, so a stale hand-authored rate stops
                  hiding.

Delegation is maximal on purpose: every row an upstream can be matched to is
handed over, and the ones it gets wrong are accepted. An upstream that is
occasionally wrong and always fresh beats a hand-authored file that is
occasionally right and always rotting, which is the state this registry was in —
its only freshness signal was a "last full refresh" date in the README that
nothing checked.

What stays manual is what no upstream has an answer for:

  - Resellers with a price list of their own that they do not publish: qoder,
    qoder-intl, workbuddy. A vendor's rate would be fiction rather than
    derivation there, since these really do discount.
  - Ids nothing upstream carries: `k3`, `kimi-for-coding*`, every `mimo-*`, the
    `grok-imagine-*` pairs, `glm-5-turbo`, `gpt-oss-120b-medium`, Antigravity's
    two `tab_*` completion models, and the Cursor ids its own table omits
    (`composer-2.5*`, `cursor-grok-4.5*`, `default`, `gpt-5.1*`).

Two consequences worth knowing, both accepted rather than worked around:

  - The CN-priced vendors move onto the vendor's INTERNATIONAL list. litellm's
    `zai/glm-4.7` at 0.6/2.2 is z.ai's USD list; what was here came from
    open.bigmodel.cn's CNY list (4.0/16.0 CNY at a frozen rate). They are two
    price lists, not two conversions of one — the swap is real, and it retires
    a hand-refreshed exchange-rate constant that was drifting from the day it
    was written.
  - `gpt-image-2` loses a deliberate reading: this registry carried the IMAGE
    output rate (30) because that is the only kind those routes emit, and
    litellm publishes the text one (10). Flip that one row's `source` back to
    `manual` if the undercharge matters more than the freshness.

Matching never crosses namespaces. litellm carries most Chinese models under
third-party hosts (cloudflare/, baseten/, azure_ai/, fireworks_ai/); those are
another deployment's facts.

Usage:
    python3 scripts/sync_prices.py                     # apply, then report
    python3 scripts/sync_prices.py --check             # report only, write nothing
    python3 scripts/sync_prices.py --upstream f.json   # compare against a local copy
    python3 scripts/sync_prices.py --out drift.md      # also write the report to a file

Exit codes: 0 nothing needs a human, 1 something does, 2 could not run.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import urllib.request

UPSTREAM = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

# Provider file -> the litellm namespaces carrying that vendor's OWN published
# rates. Presence here makes a provider eligible for delegation; the per-row
# `source` still decides, so a row can always be taken back by hand. A provider
# absent from this table (every reseller, and mimo) has nothing upstream to
# compare against, let alone delegate to.
NAMESPACES = {
    "anthropic": ["anthropic"],
    "codex": ["openai"],
    "google-ai-studio": ["gemini"],
    "deepseek": ["deepseek"],
    "xai": ["xai"],
    "glm": ["zai"],
    "kimi": ["moonshot"],
    "minimax": ["minimax"],
    "qianwen": ["dashscope"],
}

# Surfaces that publish no rates of their own but METER at the vendor's API
# list, matched against another vendor's namespace on the model's base id.
#
# Antigravity is the case this exists for: it sells credits and Google does not
# publish the credit-to-token rate, but its own plan documentation says rate
# limits are "drawn down as per API pricing". So the vendor's list is this
# surface's meter by the surface's own account — a DERIVATION rather than a
# published number, which is why these rows carry `"source": "vendor-api"` and
# not "litellm". The distinction is the whole point: someone auditing a bill
# needs to see which rows are read and which are inferred.
# Kiro is the same shape: it resells the vendors' models under a CodeWhisperer
# subscription and publishes no per-token rate of its own, so the vendor's list
# is the only number there is to bill against.
DERIVED_NAMESPACES = {
    "antigravity": ["anthropic", "gemini"],
    "kiro": ["anthropic", "openai", "gemini", "deepseek", "zai", "minimax", "dashscope"],
    # Cursor's RATES come from Cursor's own published table, not from here — it
    # really does charge its own prices. It is listed only so a cursor row can
    # still pick up the vendor's context window and input modalities, which do
    # not change because a reseller fronts the model.
    "cursor": ["anthropic", "openai", "gemini", "zai", "moonshot"],
}

# Cursor publishes its own per-model table as machine-readable markdown, which
# makes it the one reseller here with a rate to READ rather than derive.
CURSOR_DOCS = "https://cursor.com/docs/models-and-pricing.md"

# Our base id -> the doc's spelling, where normalising both to alphanumerics is
# not enough. Only word-order differences need one; everything else falls out of
# the normalisation.
CURSOR_ALIASES = {
    "claude-opus-4-7": "Claude 4.7 Opus",
}

# Suffixes a surface appends to a model id — reasoning depths, agent modes,
# tiering, speed. None of them changes which MODEL is being served, so they are
# stripped before matching. For the vendor-api surfaces none of them changes the
# rate either ("gemini-3-flash-agent" is priced as gemini-3-flash), which is the
# one assumption those rows rest on. For Cursor, "-fast" does change the rate and
# is handled separately; see cursor_rates.
SURFACE_SUFFIX = re.compile(
    r"-(thinking|agent|tiered|extra-high|extra-low|minimal|none|low|medium|high|xhigh|max|fast)$")

# An Anthropic-style dated release suffix, and nothing else.
DATED_SUFFIX = re.compile(r"^-20\d{6}$")

# Sources this script writes. Everything else is left for a person.
WRITTEN = ("litellm", "vendor-api", "cursor-docs")

# Our field <- litellm's per-token field. The rates are always written for a
# delegated row; the last two are facts rather than prices and are written the
# same way, because a vendor either takes images or does not.
RATES = [
    ("prompt_per_1m", "input_cost_per_token"),
    ("completion_per_1m", "output_cost_per_token"),
    ("cache_read_per_1m", "cache_read_input_token_cost"),
    ("cache_write_per_1m", "cache_creation_input_token_cost"),
]

# Rates are clean decimals on both sides; this only absorbs float noise from the
# per-token → per-1M multiply. A real disagreement (0.310334 against 0.3, the
# frozen CNY conversion) is orders of magnitude above it.
TOLERANCE = 1e-6


def differs(ours, theirs) -> bool:
    scale = max(abs(ours), abs(theirs), 1.0)
    return abs(ours - theirs) > TOLERANCE * scale


def load_upstream(source: str):
    if os.path.exists(source):
        with open(source) as fh:
            return json.load(fh)
    with urllib.request.urlopen(source, timeout=60) as resp:
        return json.load(resp)


def index_upstream(upstream) -> dict:
    """namespace -> bare model id -> (full key, entry)."""
    idx: dict = {}
    for key, entry in upstream.items():
        if not isinstance(entry, dict):
            continue
        bare = key.split("/")[-1].lower()
        # First key wins: litellm lists the dated id before its floating alias
        # ("claude-haiku-4-5-20251001" then "claude-haiku-4-5"), and the dated
        # one is what a price is published against.
        idx.setdefault(entry.get("litellm_provider"), {}).setdefault(bare, (key, entry))
    return idx


def load_cursor_docs(source: str) -> dict:
    """Parse Cursor's published table into normalised name -> the four rates.

    The page is served as text/plain markdown, so this reads columns rather than
    scraping HTML. A layout change therefore shows up as an empty table, which
    the caller treats as a failed run — the one thing it must never do is write
    a blank price over a real one.
    """
    if os.path.exists(source):
        text = open(source).read()
    else:
        with urllib.request.urlopen(source, timeout=60) as resp:
            text = resp.read().decode("utf-8")

    table = {}
    for line in text.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[2].startswith("$"):
            continue
        name = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cells[0]).strip()

        def money(cell):
            cell = cell.replace("$", "").replace(",", "").strip()
            try:
                return float(cell)
            except ValueError:
                return 0.0  # "-" — the vendor charges nothing for this bucket

        table[normalized(name)] = {
            "prompt_per_1m": money(cells[2]),
            "cache_write_per_1m": money(cells[3]),
            "cache_read_per_1m": money(cells[4]),
            "completion_per_1m": money(cells[5]),
        }
    return table


def normalized(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def strip_suffixes(model_id: str) -> str:
    base = model_id.lower()
    previous = None
    while previous != base:
        previous = base
        base = SURFACE_SUFFIX.sub("", base)
    return base


def cursor_rates(model_id: str, table: dict):
    """The four rates Cursor publishes for one of our cursor ids, or None.

    Effort suffixes do not change a price — Cursor charges per token, and the
    depth only changes how many are spent. "-fast" DOES change it, and the doc
    expresses that two different ways:

      an explicit row   "Claude Opus 4.7 (fast mode)" at 30/150, six times the
                        base. Always preferred when present.
      prose only        the Notes say GPT-5 Fast is "2x price", and that Opus
                        4.8's fast mode is "3x lower per-token pricing than Opus
                        4.7 fast mode" — 30/3 and 150/3, which is 2x ITS base.

    So the fallback is 2x, corroborated twice, and it is an inference rather than
    a reading: 60 of our 66 "-fast" ids have no row of their own. It corrects a
    real error, since those rows were carrying the base price.

    Both spellings of the name are tried, and both are needed: the doc names one
    model two ways depending on the row. The base is "Claude 4.7 Opus" while its
    fast row is "Claude Opus 4.7 (fast mode)" — aliasing only the base found the
    base and then silently missed the explicit 30/150 fast row, falling back to
    2x and pricing it at a third of what Cursor charges.
    """
    base = strip_suffixes(model_id)
    keys = [normalized(base)]
    alias = normalized(CURSOR_ALIASES.get(base, ""))
    if alias and alias not in keys:
        keys.append(alias)

    if model_id.lower().endswith("-fast"):
        for key in keys:
            for spelling in (f"{key}fastmode", f"{key}fast"):
                if spelling in table:
                    return table[spelling]
        for key in keys:
            if key in table:
                return {field: value * 2 for field, value in table[key].items()}
        return None
    for key in keys:
        if key in table:
            return table[key]
    return None


def derived_match(provider: str, model_id: str, idx: dict):
    """Find the vendor row a derived surface's id is metered against.

    The id is first stripped of this surface's own suffixes, then tried in both
    spellings of a version — as written, and with dots turned into dashes. Both
    are needed and neither is safe alone: Kiro writes `claude-opus-4.5` where
    Anthropic writes `claude-opus-4-5`, while Google really does write
    `gemini-2.5-flash` with the dot. Respelling unconditionally turned every
    Gemini row into a miss.

    Each spelling is tried three ways, in order of how much it assumes:

      exact               the id itself
      + "-preview"        a real vendor id form (gemini-3.1-pro-preview), not a
                          pointer
      + "-<date>"         Anthropic's dated ids, matched only against an 8-digit
                          date so that claude-sonnet-4 cannot capture
                          claude-sonnet-4-5-20250929

    A "-latest" fallback is deliberately NOT tried: that is a moving alias, and
    resolving to it would price a row from whichever generation litellm's
    snapshot happened to catch. gemini-pro-agent is the row that would have hit
    it, and it would have come out at 2.5 Pro's rate.
    """
    base = strip_suffixes(model_id)
    spellings = [base]
    respelled = re.sub(r"(?<=\d)\.(?=\d)", "-", base)
    if respelled != base:
        spellings.append(respelled)

    for namespace in DERIVED_NAMESPACES.get(provider, []):
        models = idx.get(namespace, {})
        for spelling in spellings:
            for candidate in (spelling, spelling + "-preview"):
                if candidate in models:
                    return models[candidate]
            dated = sorted(k for k in models
                           if k.startswith(spelling + "-") and DATED_SUFFIX.match(k[len(spelling):]))
            if dated:
                # Newest dated release last, which is the one a surface serving
                # the bare name is serving.
                return models[dated[-1]]
    return None


def clean(value: float):
    """Strip the float noise the per-token → per-1M multiply leaves behind.

    litellm stores 2e-7, which multiplies out to 0.19999999999999998. Written
    verbatim that would make every rate an eyesore and every re-run's diff
    suspicious. Integral values come back as ints so the file keeps one spelling
    of a whole number.
    """
    value = float(f"{value:.10g}")
    return int(value) if value == int(value) else value


def per_1m(entry: dict, field: str):
    """The upstream rate in our unit, or None when it publishes none.

    None and 0 are different answers and must stay so: 0 in this registry means
    "no published per-token rate" (the service reads it as unpriced), while an
    upstream silence means nobody filled the field in. Writing a silence in as a
    zero would turn a priced model free.
    """
    value = entry.get(field)
    return None if value is None else clean(value * 1e6)


def upstream_modalities(entry: dict):
    """litellm's input media as our comma-separated form, or None if it says nothing."""
    modalities = entry.get("supported_modalities")
    if modalities:
        keep = [m for m in modalities if m in ("text", "image", "audio", "video")]
        return keep or None
    vision = entry.get("supports_vision")
    if vision is None:
        return None
    return ["text", "image"] if vision else ["text"]


def sync(registry_dir: str, upstream, cursor_table: dict, apply: bool):
    idx = index_upstream(upstream)
    applied, disagree, orphans, unclassified, capability = [], [], [], [], []
    counts = collections.Counter()

    for path in sorted(glob.glob(os.path.join(registry_dir, "providers", "*.json"))):
        with open(path) as fh:
            doc = json.load(fh, object_pairs_hook=collections.OrderedDict)
        provider = doc["name"]
        dirty = False

        for model in doc.get("models", []):
            source = model.get("source")
            mid = model["model"]
            if source is None:
                # Fail safe: an unclassified row is treated as ours, so a new
                # entry is never silently overwritten by an upstream number
                # nobody chose to trust.
                unclassified.append((provider, mid))
                source = "manual"
            counts[source] += 1

            found = None
            for namespace in NAMESPACES.get(provider, []):
                found = idx.get(namespace, {}).get(mid.lower())
                if found:
                    break
            if not found:
                found = derived_match(provider, mid, idx)

            # Cursor's rates come from Cursor's own table; `found`, when there is
            # one, only carries the vendor's capability facts for the same model.
            published = cursor_rates(mid, cursor_table) if source == "cursor-docs" else None

            if source in WRITTEN and not found and published is None:
                # Delegated to a row that no longer exists upstream. Leave every
                # value standing — an id vanishing from litellm is not the vendor
                # withdrawing the model — and make a person look.
                orphans.append((provider, mid))
                continue
            if not found and published is None:
                continue
            key, entry = found if found else ("", {})

            if source in WRITTEN:
                for field, upstream_field in RATES:
                    theirs = clean(published[field]) if published else per_1m(entry, upstream_field)
                    if theirs is None:
                        continue
                    if differs(model.get(field, 0), theirs):
                        applied.append((provider, mid, field, model.get(field, 0), theirs))
                        if apply:
                            model[field] = theirs
                            dirty = True
                window = entry.get("max_input_tokens")
                if window and model.get("context_window") != window:
                    applied.append((provider, mid, "context_window", model.get("context_window"), window))
                    if apply:
                        model["context_window"] = window
                        dirty = True
                modalities = upstream_modalities(entry)
                if modalities and model.get("input_modalities") != modalities:
                    applied.append((provider, mid, "input_modalities",
                                    model.get("input_modalities"), modalities))
                    if apply:
                        model["input_modalities"] = modalities
                        dirty = True
                continue

            # source == "manual": compare, never write.
            if all(not model.get(f, 0) for f, _ in RATES):
                # 0 across the board is this registry's way of saying "no
                # published per-token rate". It is a statement, not a gap.
                continue
            if mid.lower().endswith("-latest"):
                # A floating alias is each side's snapshot of a different
                # generation. Both can be right and they will never agree.
                continue
            for field, upstream_field in RATES:
                theirs = per_1m(entry, upstream_field)
                mine = model.get(field, 0)
                if not theirs:
                    continue
                # A cache rate we do not carry is usually a rate the vendor does
                # not charge; only report where both sides state a number.
                if field.startswith("cache_") and not mine:
                    continue
                if differs(mine, theirs):
                    disagree.append((provider, mid, key, field, mine, theirs))
            if not model.get("input_modalities") and upstream_modalities(entry):
                capability.append((provider, mid, "input_modalities",
                                   ",".join(upstream_modalities(entry))))
            if not model.get("context_window") and entry.get("max_input_tokens"):
                capability.append((provider, mid, "context_window", entry["max_input_tokens"]))

        if dirty and apply:
            with open(path, "w") as fh:
                fh.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

    return applied, disagree, orphans, unclassified, capability, counts


def render(applied, disagree, orphans, unclassified, capability, counts, apply: bool) -> str:
    out = []
    w = out.append
    verb = "applied" if apply else "would apply"
    w("# Registry vs litellm")
    w("")
    w(f"{counts['litellm']} rows read from litellm · "
      f"{counts['vendor-api']} derived from the vendor's API list · "
      f"{counts['manual']} maintained here")
    w("")
    w(f"**{len(applied)} field(s) {verb}** · **{len(disagree)} disagreement(s) on rows we own** · "
      f"{len(orphans)} orphaned · {len(unclassified)} unclassified · "
      f"{len(capability)} capability facts available")
    w("")

    if disagree:
        w("## Rows we own that litellm disagrees with")
        w("")
        w("Nothing here was changed. Decide each one — our number may be the "
          "deliberate one (see the README's provenance section), or it may have "
          "gone stale. If litellm should own the row from now on, flip its "
          "`source` to `litellm`.")
        w("")
        w("| provider | model | field | ours | litellm | litellm key |")
        w("|---|---|---|---|---|---|")
        for provider, model, key, field, mine, theirs in disagree:
            w(f"| {provider} | `{model}` | {field} | {mine:g} | {theirs:g} | `{key}` |")
        w("")

    if orphans:
        w("## Delegated rows litellm no longer carries")
        w("")
        w("Their values were left standing. Either the id moved upstream, or "
          "this row should go back to `\"source\": \"manual\"`.")
        w("")
        for provider, model in orphans:
            w(f"- {provider}: `{model}`")
        w("")

    if unclassified:
        w("## Rows with no `source`")
        w("")
        w("Treated as ours and left alone. Give each one a source so it is "
          "either kept fresh or knowingly hand-held.")
        w("")
        for provider, model in unclassified:
            w(f"- {provider}: `{model}`")
        w("")

    if applied:
        w(f"## Fields {verb}")
        w("")
        w("| provider | model | field | was | now |")
        w("|---|---|---|---|---|")
        for provider, model, field, before, after in applied:
            w(f"| {provider} | `{model}` | {field} | `{before}` | `{after}` |")
        w("")

    if capability:
        w("## Capability facts available for rows we own")
        w("")
        w("No commercial judgement in these — a vendor either takes images or "
          "does not. Copy them in once spot-checked.")
        w("")
        w("| provider | model | field | litellm says |")
        w("|---|---|---|---|")
        for provider, model, field, value in capability:
            w(f"| {provider} | `{model}` | {field} | `{value}` |")
        w("")

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", default=UPSTREAM,
                        help="litellm JSON: a URL, or a path to a local copy")
    parser.add_argument("--registry",
                        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        help="registry checkout to sync (default: this one)")
    parser.add_argument("--cursor-docs", default=CURSOR_DOCS,
                        help="Cursor's published table: a URL, or a path to a local copy")
    parser.add_argument("--check", action="store_true",
                        help="report only; write nothing")
    parser.add_argument("--out", help="also write the report here")
    args = parser.parse_args()

    try:
        upstream = load_upstream(args.upstream)
    except Exception as err:  # network, JSON, permissions — all the same to a caller
        print(f"could not read upstream {args.upstream}: {err}", file=sys.stderr)
        return 2

    try:
        cursor_table = load_cursor_docs(args.cursor_docs)
    except Exception as err:
        print(f"could not read Cursor's table {args.cursor_docs}: {err}", file=sys.stderr)
        return 2
    if not cursor_table:
        # An empty parse means the page changed shape. Writing every cursor row
        # to zero would be far worse than not running.
        print(f"parsed no rows from {args.cursor_docs} — the table's layout changed",
              file=sys.stderr)
        return 2

    applied, disagree, orphans, unclassified, capability, counts = sync(
        args.registry, upstream, cursor_table, apply=not args.check)
    report = render(applied, disagree, orphans, unclassified, capability, counts,
                    apply=not args.check)
    print(report)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(report)
    # An applied write is the normal path and needs nobody. The three lists that
    # do are what sets the exit code.
    return 1 if (disagree or orphans or unclassified) else 0


if __name__ == "__main__":
    sys.exit(main())
