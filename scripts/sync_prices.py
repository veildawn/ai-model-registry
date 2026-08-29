#!/usr/bin/env python3
"""Sync the rows an upstream owns; report on the rows we own.

Every model entry carries a `source`, and it decides who writes its RATES
(capability facts are filled on every row regardless — see the README):

    "litellm"     the vendor's own namespace carries this exact id. This script
                  overwrites the row's rates from litellm on every run. Nobody
                  edits these by hand — an edit would be reverted the next
                  morning, which is the point: the row is delegated.
    "vendor-api"  a surface that publishes no rates of its own and meters at the
                  vendor's API list (kiro, antigravity). Written the same way,
                  from the vendor's row, after this surface's own suffixes are
                  stripped. Named apart from "litellm" because it is DERIVED:
                  someone auditing a bill needs to see which rows were read and
                  which were inferred.
    "manual"      this script NEVER writes the row's rates. It only reports when
                  the upstream disagrees, so a stale hand-authored rate stops
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
    `grok-imagine-*` pairs, `glm-5-turbo`, `gpt-oss-120b-medium`, and
    Antigravity's two `tab_*` completion models.

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

A SECOND upstream, models.dev, supplies the two fields litellm has no column
for: the reasoning ladder (`effort_levels`) and, where a model's only output is
an image or video or audio, the serving `surface`. It is a supplement in the
strict sense — it fills a field a row leaves EMPTY and never rewrites one that
is set, so it can overrule neither litellm nor a person. It is also the one
upstream whose absence is survivable: a failure there is logged and the run
continues, because it must not be able to stop a price sync. Within it, the
vendor's own namespace outranks the aggregators: where one publishes a ladder
it wins outright, and unanimity across the remaining hosts decides only for
ids the vendor is silent on.

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
import urllib.parse
import urllib.request

UPSTREAM = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

# models.dev is the SECOND upstream, and it is here for what litellm has no
# column for at all: the reasoning ladder a model accepts. litellm publishes
# rates and windows and says nothing about effort levels, so every ladder in this
# registry was hand-written and coverage sat at a quarter of the rows — which is
# the state delegation exists to get out of.
#
# It is a SUPPLEMENT, never an override. It fills a field a row does not have and
# never rewrites one that does. Its per-model data is community-curated and its
# provider list is an order of magnitude wider than the vendors tracked here, so
# it is trusted for the fields nobody else publishes and for nothing else;
# litellm remains the authority for every field it carries.
MODELS_DEV = "https://models.dev/api.json"

# models.dev namespaces that are the model's FIRST-PARTY publisher or one of its
# own metering arms — google/google-vertex for Gemini, zai/zhipuai for GLM,
# minimax, deepseek, moonshotai, alibaba, nvidia, and the rest below. A reasoning
# ladder is a fact about the MODEL, and the vendor's row is that fact from its
# source, which is the same authority `vendor-api` pricing rests on.
#
# The unanimity rule that governed every host equally was dropping the ladders
# that mattered most: one aggregator misreading an id outvoted the vendor's own
# row, and a family split across aggregator spellings (llmgateway,
# llmgateway-providers, requesty, kilo, each with its own opinion) contested the
# id away entirely — minimax-m2.5 lost its ladder to four mutually inconsistent
# copies while the vendor's row sat right there. Where the vendor speaks, it
# wins; the aggregators decide only what the vendor has not.
VENDOR_HOSTS = frozenset({
    "alibaba", "alibaba-cn", "alibaba-coding-plan", "alibaba-coding-plan-cn",
    "alibaba-token-plan", "alibaba-token-plan-cn",
    "amazon-bedrock", "anthropic", "cohere", "deepseek",
    "google", "google-vertex", "google-vertex-anthropic",
    "meta", "microsoft", "minimax", "minimax-cn", "minimax-coding-plan",
    "minimax-cn-coding-plan", "mistral", "moonshotai", "moonshotai-cn",
    "nvidia", "openai", "tencent-coding-plan", "tencent-token-plan",
    "tencent-tokenhub", "xai", "zai", "zai-coding-plan", "zhipuai",
    "zhipuai-coding-plan",
})

# Our `surface` <- litellm's `mode`. The surface is which API ROUTE serves a
# model — the question a gateway answers before it can dispatch, and one no rate
# implies. Without it a consumer has only the model's NAME to go on, which is a
# strong convention for well-known ids and says nothing at all about a
# reseller's private one.
#
# Only modes naming a route this registry's consumers serve are mapped. The rest
# (search, ocr, moderation, guardrail, vector_store) are deliberately unmapped:
# an unmapped mode writes no surface, and a consumer finding none falls through
# to its own classifier. Inventing a surface for a route nobody serves would be a
# claim rather than a fact.
SURFACES = {
    "chat": "chat",
    "completion": "chat",
    "responses": "chat",
    "image_generation": "image",
    "image_edit": "image",
    "embedding": "embedding",
    "audio_transcription": "audio",
    "audio_speech": "audio",
    "realtime": "audio",
    "video_generation": "video",
    "rerank": "rerank",
}

# The reasoning levels this registry publishes, weakest first. A ladder read from
# an upstream is filtered to these and re-ordered into this sequence, so one
# vocabulary is stored no matter which upstream a row was filled from.
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

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
}

# Suffixes a surface appends to a model id — reasoning depths, agent modes,
# tiering, speed. None of them changes which MODEL is being served, so they are
# stripped before matching. For the vendor-api surfaces none of them changes the
# rate either ("gemini-3-flash-agent" is priced as gemini-3-flash), which is the
# one assumption those rows rest on.
SURFACE_SUFFIX = re.compile(
    r"-(thinking|agent|tiered|extra-high|extra-low|minimal|none|low|medium|high|xhigh|max|fast)$")

# An Anthropic-style dated release suffix, and nothing else.
DATED_SUFFIX = re.compile(r"^-20\d{6}$")

# Sources this script writes. Everything else is left for a person.
WRITTEN = ("litellm", "vendor-api")

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
    return fetch_json(source)


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


def strip_suffixes(model_id: str) -> str:
    base = model_id.lower()
    previous = None
    while previous != base:
        previous = base
        base = SURFACE_SUFFIX.sub("", base)
    return base


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


def upstream_surface(entry: dict):
    """litellm's `mode` as our surface, or None when it names a route we do not map."""
    return SURFACES.get(entry.get("mode"))


def capability_facts(entry: dict):
    """The vendor FACTS litellm states about a model, as (field, value) pairs.

    Held apart from RATES because the two are governed differently: a rate is a
    commercial term that `source` decides the ownership of, while these are true
    of the model whoever sells it. A value of None means the upstream says
    nothing and the caller leaves the field alone.
    """
    window = entry.get("max_input_tokens")
    return (
        ("context_window", window if window else None),
        ("input_modalities", upstream_modalities(entry)),
        ("surface", upstream_surface(entry)),
    )


def ladder(values) -> list:
    """An upstream's effort values in our vocabulary and our order.

    Unknown names are dropped rather than stored, for the reason every other
    filter here does it: a consumer reading a level this registry has never
    published cannot act on it, and a ladder is only useful if one vocabulary
    spans every row.
    """
    if not values:
        return []
    have = {str(v).strip().lower() for v in values}
    return [level for level in EFFORTS if level in have]


# Hosts this script will fetch from. The upstream URLs are arguments, so they are
# checked against this before a request is made rather than trusted because a
# default happens to be safe: a sync job reaching an arbitrary host is how a
# build server ends up reading a cloud metadata endpoint.
FETCH_HOSTS = frozenset({"models.dev", "raw.githubusercontent.com"})


def fetch_json(source: str, agent: str = "ai-model-registry-sync"):
    """Read a JSON document from a local path, or over HTTPS from a known host."""
    if os.path.exists(source):
        with open(source) as fh:
            return json.load(fh)
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme != "https" or parsed.hostname not in FETCH_HOSTS:
        raise ValueError(f"refusing to fetch {source!r}: not an https URL on a known host")
    request = urllib.request.Request(source, headers={"User-Agent": agent})
    with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310 — guarded above
        return json.load(resp)


def index_models_dev(document) -> dict:
    """bare model id -> the facts models.dev yields for it, vendor row first.

    Keyed by the BARE id across providers rather than per namespace, because that
    is what this upstream is being asked for: a reasoning ladder is a property of
    the model, and models.dev carries the same model under every host that serves
    it. Two accuracies, in order:

    1. A vendor row (VENDOR_HOSTS) — the publisher's own statement, the same
       authority `vendor-api` pricing rests on. Where one speaks it wins
       outright, whatever the aggregators say and however many of them say it.
       All voting vendor hosts must agree; a vendor-vs-vendor split is still a
       collision, and the id drops rather than picking a side.
    2. Unanimity among the remaining hosts — kept for the ids whose vendor is
       silent here (a reseller-only id, a release the vendor's rows do not list
       yet). Where every aggregator that publishes a ladder publishes the same
       one, that is the best reading there is; where they split, the
       disagreement is dropped for a person, as before.

    A ladder no rule yields is dropped rather than arbitrated — the same
    discipline this registry's consumers apply to a model-id-alone lookup,
    because a disagreement is the signature of a name collision, and guessing
    between the two is worse than leaving the row for a person.
    """
    vendor_ladders: dict = {}
    vendor_contested: set = set()
    ladders: dict = {}
    surfaces: dict = {}
    contested_ladder, contested_surface = set(), set()

    for provider_name, provider in document.items():
        if not isinstance(provider, dict):
            continue
        for mid, model in (provider.get("models") or {}).items():
            if not isinstance(model, dict):
                continue
            bare = mid.split("/")[-1].lower()

            levels = []
            for option in model.get("reasoning_options") or []:
                if isinstance(option, dict) and option.get("type") == "effort":
                    levels = ladder(option.get("values"))
                    break
            if levels:
                if provider_name in VENDOR_HOSTS:
                    if bare in vendor_ladders and vendor_ladders[bare] != levels:
                        vendor_contested.add(bare)
                    vendor_ladders.setdefault(bare, levels)
                elif bare not in contested_ladder:
                    if ladders.setdefault(bare, levels) != levels:
                        contested_ladder.add(bare)

            # An OUTPUT modality is the surface stated the other way round: a
            # model whose only output is an image is served by the images route
            # whatever it is called.
            #
            # A text-only output is read as a POSITIVE vote for chat, not as
            # silence, and that is what makes the agreement check work. models.dev
            # carries one entry per host that serves a model — gpt-5.4 appears
            # under 39 of them — so a single mislabelled aggregator (poe calls
            # that one an image model) would otherwise stand unopposed, because
            # the 38 hosts that have it right produce no surface to disagree
            # with. Counting them costs 4 ids across the whole upstream and
            # removes the entire class of one-bad-row errors.
            #
            # A mixed output (text AND image) is left unmapped: that is a chat
            # model that can also draw, which is a different claim from either.
            output = tuple((model.get("modalities") or {}).get("output") or ())
            surface = {("text",): "chat", ("image",): "image",
                       ("video",): "video", ("audio",): "audio"}.get(output)
            if surface and bare not in contested_surface:
                if surfaces.setdefault(bare, surface) != surface:
                    contested_surface.add(bare)

    for bare in contested_ladder:
        ladders.pop(bare, None)
    for bare in contested_surface:
        surfaces.pop(bare, None)
    # A vendor split disqualifies the id outright: falling back to the
    # aggregators would let the noisiest copy of a contested fact win.
    for bare in vendor_contested:
        ladders.pop(bare, None)

    out: dict = {}
    for bare, levels in vendor_ladders.items():
        out.setdefault(bare, {})["effort_levels"] = levels
    for bare, levels in ladders.items():
        out.setdefault(bare, {})["effort_levels"] = levels
    for bare, surface in surfaces.items():
        out.setdefault(bare, {})["surface"] = surface
    return out


# Fields a variant may differ from its family's base on. Only rates: a reasoning
# depth or a speed tier changes what a call COSTS and never what the model is, so
# a context window or a surface that varied inside a family would be a mistake
# rather than a fact — which is exactly the class of mistake collapsing removes,
# by leaving those facts only one place to live.
VARIANT_OVERRIDABLE = tuple(field for field, _ in RATES)


def expand_family(entry: dict) -> list:
    """One stored entry as the per-id entries the rest of this script works on.

    An entry with no `variants` is itself, which is most of the registry. A
    family yields one entry per suffix, carrying the base's facts with its
    override group's rates applied on top.
    """
    variants = entry.get("variants")
    if not variants:
        return [entry]

    patches = {}
    for group in variants.get("overrides", []):
        patch = {k: v for k, v in group.items() if k != "suffixes"}
        for suffix in group.get("suffixes", []):
            patches[suffix] = patch

    shared = collections.OrderedDict(
        (k, v) for k, v in entry.items() if k not in ("variants", "model"))
    out = []
    for suffix in variants.get("suffixes", []):
        row = collections.OrderedDict()
        row["model"] = entry["model"] + suffix
        row.update(shared)
        row.update(patches.get(suffix, {}))
        # Remembered so collapse_models can put the family back together without
        # re-deriving the split from the ids, which would need a suffix grammar.
        row["_family"] = entry["model"]
        row["_suffix"] = suffix
        out.append(row)
    return out


def collapse_models(models: list) -> list:
    """The inverse of expand_family: per-id entries back into stored form.

    Rows that were never part of a family pass through untouched and in order.
    A family is written as its base facts plus one override group per distinct
    rate card; the LARGEST group supplies the base, so the common case is the
    one that costs no override at all.
    """
    out, seen = [], set()
    byfamily = collections.OrderedDict()
    for row in models:
        family = row.get("_family")
        if family is None:
            out.append(row)
            continue
        byfamily.setdefault(family, []).append(row)
        if family not in seen:
            seen.add(family)
            out.append(family)  # placeholder, replaced below

    rebuilt = []
    for item in out:
        if not isinstance(item, str):
            rebuilt.append(clean_row(item))
            continue
        rows = byfamily[item]
        groups = collections.OrderedDict()
        for row in rows:
            key = tuple(row.get(f, 0) for f in VARIANT_OVERRIDABLE)
            groups.setdefault(key, []).append(row)
        # Largest first: its rates become the family's own, so the override list
        # holds only the exceptions.
        ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
        base = clean_row(ordered[0][1][0])
        base["model"] = item
        variants = collections.OrderedDict()
        variants["suffixes"] = [r["_suffix"] for r in rows]
        overrides = []
        for key, members in ordered[1:]:
            group = collections.OrderedDict()
            group["suffixes"] = [r["_suffix"] for r in members]
            for field, value in zip(VARIANT_OVERRIDABLE, key):
                group[field] = value
            overrides.append(group)
        if overrides:
            variants["overrides"] = overrides
        base["variants"] = variants
        rebuilt.append(base)
    return rebuilt


def clean_row(row: dict) -> collections.OrderedDict:
    """A row without this script's bookkeeping keys."""
    return collections.OrderedDict(
        (k, v) for k, v in row.items() if not k.startswith("_"))


def discover_families(models: list) -> list:
    """Tag flat rows that belong to one variant family.

    This is the only place a suffix grammar decides family membership, and it
    runs on every sync rather than once, so a newly added id folds into its
    family instead of sitting flat until someone notices. What keeps that safe
    is that the grammar only decides how the file is WRITTEN: expand → discover →
    collapse is a round trip over the same facts, and scripts/flatten.py proves
    it by diffing them.

    A group is only collapsed when it is unambiguously one model sold at several
    depths:

      - more than one member, each id being exactly its base plus the leftover
        suffix;
      - every member agreeing on every field that is not a rate. A family that
        disagreed on a context window is either a naming coincidence or a bug,
        and collapsing it would silently pick one answer — so it is left flat
        for a person.
    """
    groups = collections.OrderedDict()
    for row in models:
        groups.setdefault(strip_suffixes(row["model"]), []).append(row)

    out = []
    for base, rows in groups.items():
        suffixes = [r["model"][len(base):] for r in rows]
        shared_ok = True
        for field in set().union(*(set(r) for r in rows)):
            if field in VARIANT_OVERRIDABLE or field == "model" or field.startswith("_"):
                continue
            if len({json.dumps(r.get(field), sort_keys=True) for r in rows}) > 1:
                shared_ok = False
                break
        if len(rows) < 2 or not shared_ok or not all(
                r["model"] == base + s for r, s in zip(rows, suffixes)):
            for row in rows:
                row.pop("_family", None)
                row.pop("_suffix", None)
            out.extend(rows)
            continue
        for row, suffix in zip(rows, suffixes):
            row["_family"] = base
            row["_suffix"] = suffix
        out.extend(rows)
    return out


def contested_model_facts(rows: list) -> list:
    """Bare model ids that two providers publish DIFFERENT facts for.

    Every consumer with a model-id-alone fallback drops these silently: a
    context window or a surface that two publishers disagree about is treated as
    unpublished, because guessing between them is worse than falling through. A
    silent drop is the right RUNTIME behaviour and a bad reporting one — the
    fact looks published, and nothing says why it never arrives.
    """
    facts = ("context_window", "surface")
    byid = collections.defaultdict(lambda: collections.defaultdict(dict))
    for provider, row in rows:
        for field in facts:
            value = row.get(field)
            if value:
                byid[row["model"].lower()][field][provider] = value

    out = []
    for mid in sorted(byid):
        for field in facts:
            claims = byid[mid][field]
            if len({json.dumps(v, sort_keys=True) for v in claims.values()}) > 1:
                out.append((mid, field, dict(sorted(claims.items()))))
    return out


def sync(registry_dir: str, upstream, models_dev: dict, apply: bool):
    idx = index_upstream(upstream)
    applied, disagree, orphans, unclassified, capability = [], [], [], [], []
    counts = collections.Counter()
    # Every row this pass saw, for the cross-provider checks that can only be
    # made once the whole registry is in hand.
    everything = []
    # Whether any provider file was rewritten, which is what makes all.json
    # stale — see regenerate_bundle below.
    wrote = False

    for path in sorted(glob.glob(os.path.join(registry_dir, "providers", "*.json"))):
        with open(path) as fh:
            doc = json.load(fh, object_pairs_hook=collections.OrderedDict)
        provider = doc["name"]
        dirty = False

        # Everything below works on one entry per SERVED id, exactly as it did
        # before variant families existed. The stored shape is put back at the
        # write, so the matching logic never has to know a family from a row.
        models = discover_families(
            [row for entry in doc.get("models", []) for row in expand_family(entry)])

        for model in models:
            source = model.get("source")
            mid = model["model"]
            if source is None:
                # Fail safe: an unclassified row is treated as ours, so a new
                # entry is never silently overwritten by an upstream number
                # nobody chose to trust.
                unclassified.append((provider, mid))
                source = "manual"
            counts[source] += 1
            # Fields the litellm pass has already spoken for on this row. Under
            # --check nothing is written, so without this the models.dev
            # supplement would still see an empty field and report a second
            # proposal for one the report already lists.
            proposed = set()

            found = None
            for namespace in NAMESPACES.get(provider, []):
                found = idx.get(namespace, {}).get(mid.lower())
                if found:
                    break
            if not found:
                found = derived_match(provider, mid, idx)
            matched = bool(found)

            if source in WRITTEN and not matched:
                # Delegated to a row that no longer exists upstream. Leave every
                # value standing — an id vanishing from litellm is not the vendor
                # withdrawing the model — and make a person look.
                orphans.append((provider, mid))
            elif matched:
                key, entry = found

                if source in WRITTEN:
                    for field, upstream_field in RATES:
                        theirs = per_1m(entry, upstream_field)
                        if theirs is None:
                            continue
                        if differs(model.get(field, 0), theirs):
                            applied.append((provider, mid, field, model.get(field, 0), theirs))
                            if apply:
                                model[field] = theirs
                                dirty = True
                else:
                    # source == "manual": rates are compared, never written.
                    comparable = (not all(not model.get(f, 0) for f, _ in RATES)
                                  # 0 across the board is this registry's way of
                                  # saying "no published per-token rate". It is a
                                  # statement, not a gap.
                                  and not mid.lower().endswith("-latest"))
                    # A floating alias is each side's snapshot of a different
                    # generation. Both can be right and they will never agree.
                    if comparable:
                        for field, upstream_field in RATES:
                            theirs = per_1m(entry, upstream_field)
                            mine = model.get(field, 0)
                            if not theirs:
                                continue
                            # A cache rate we do not carry is usually a rate the
                            # vendor does not charge; only report where both
                            # sides state a number.
                            if field.startswith("cache_") and not mine:
                                continue
                            if differs(mine, theirs):
                                disagree.append((provider, mid, key, field, mine,
                                                 theirs, model.get("price_reviewed", "")))

                # Capability facts are written on EVERY row, whoever owns its
                # price. `source` protects a commercial judgement, and there is
                # none in these — a vendor either takes images or does not, and a
                # context window is the same number whoever fronts the model. The
                # older reading, that `manual` freezes the whole row, left these
                # accumulating in the report for a person to copy by hand: 131 of
                # them, which is a backlog rather than a decision.
                #
                # What still differs is who may OVERWRITE. On a delegated row the
                # upstream owns the field outright. On a row we own it may only
                # fill a blank, so a value someone put there by hand stands.
                for field, value in capability_facts(entry):
                    if not value:
                        continue
                    current = model.get(field)
                    if current == value or (current and source not in WRITTEN):
                        continue
                    applied.append((provider, mid, field, current, value))
                    proposed.add(field)
                    if apply:
                        model[field] = value
                        dirty = True

            # The models.dev supplement runs for every row, matched upstream or
            # not: it carries ids litellm has never listed, and a row that missed
            # the match above would otherwise never reach it. It only ever fills a
            # field that is EMPTY, so it can overrule neither litellm nor a
            # person — which is why it may write on a row we own as freely as on
            # a delegated one. Everything it supplies is a capability fact.
            #
            # Looked up under the base id as well, for the reason the litellm
            # match strips suffixes: a reasoning depth or a speed tier does not
            # change WHICH model is being served, and the surface suffixes are a
            # surface's own spelling that no upstream carries. Without the second
            # lookup a family fills unevenly — `claude-4.5-sonnet` would take a
            # surface while `claude-4.5-sonnet-thinking`, the same model, took
            # none.
            supplement = models_dev.get(mid.lower()) or models_dev.get(strip_suffixes(mid)) or {}
            for field, value in sorted(supplement.items()):
                if model.get(field) or field in proposed:
                    continue
                applied.append((provider, mid, field, model.get(field), value))
                if apply:
                    model[field] = value
                    dirty = True

        # Collected after the fills above, so the cross-provider check sees the
        # facts this run produced rather than the ones it started with.
        everything.extend((provider, model) for model in models)

        # The canonical stored shape for these rows. A file that is merely not in
        # it yet — the state every file is in before variant families existed —
        # counts as needing a write, so the migration rides the ordinary sync
        # instead of being a separate mode somebody has to remember to run.
        canonical = collapse_models(models)
        if canonical != doc.get("models", []):
            dirty = True

        if dirty and apply:
            wrote = True
            doc["models"] = canonical
            with open(path, "w") as fh:
                fh.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

    # all.json is a copy of everything written above, so a run that rewrote a
    # provider file and stopped would leave the registry publishing two answers
    # — the files, and a bundle a day behind them. Regenerating here rather than
    # in the workflow means the two cannot separate even when somebody runs the
    # sync by hand.
    if wrote:
        regenerate_bundle(registry_dir)

    return (applied, disagree, orphans, unclassified, capability, counts,
            contested_model_facts(everything))


def regenerate_bundle(registry_dir: str) -> None:
    """Rebuild all.json through scripts/bundle.py, which owns that file.

    Called rather than reimplemented so there is one writer for the bundle and
    one definition of its shape; see scripts/bundle.py for both. bundle.py
    derives its paths from its own location, so it can only ever rewrite THIS
    checkout — a --registry pointing somewhere else is left alone and told so,
    since silently rebuilding the wrong repo's bundle is worse than skipping.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.realpath(os.path.dirname(here))
    if os.path.realpath(registry_dir) != root:
        print(f"provider files changed in {registry_dir}; run "
              f"'python3 scripts/bundle.py' there to refresh all.json",
              file=sys.stderr)
        return
    if here not in sys.path:
        sys.path.insert(0, here)
    import bundle  # noqa: E402 — a sibling script, resolved from this file's dir

    bundle.write(bundle.build())


def render(applied, disagree, orphans, unclassified, capability, counts, contested,
           apply: bool) -> str:
    out = []
    w = out.append
    verb = "applied" if apply else "would apply"
    w("# Registry vs litellm")
    w("")
    w(f"{counts['litellm']} rows read from litellm · "
      f"{counts['vendor-api']} derived from the vendor's API list · "
      f"{counts['manual']} maintained here")
    w("")
    fresh = [d for d in disagree if not d[6]]
    reviewed = [d for d in disagree if d[6]]

    w(f"**{len(applied)} field(s) {verb}** · **{len(fresh)} new disagreement(s) on rows we own** · "
      f"{len(reviewed)} reviewed and kept · "
      f"{len(orphans)} orphaned · {len(unclassified)} unclassified · "
      f"{len(capability)} capability facts available · "
      f"{len(contested)} fact(s) contested across providers")
    w("")

    if contested:
        w("## Facts two providers disagree about")
        w("")
        w("A consumer resolving one of these by MODEL ID alone — which is how a "
          "relay serving the vendor's ids is answered — drops them rather than "
          "arbitrating, so the fact reads as published here and never arrives "
          "there. Correct the wrong side, or accept that the id resolves to "
          "nothing.")
        w("")
        w("| model | field | who says what |")
        w("|---|---|---|")
        for mid, field, claims in contested:
            says = ", ".join(f"{p}={json.dumps(v)}" for p, v in claims.items())
            w(f"| `{mid}` | {field} | {says} |")
        w("")

    if fresh:
        w("## Rows we own that litellm disagrees with")
        w("")
        w("Nothing here was changed. Decide each one — our number may be the "
          "deliberate one (see the README's provenance section), or it may have "
          "gone stale. If litellm should own the row from now on, flip its "
          "`source` to `litellm`. If OUR number is right and should stay, add a "
          "`price_reviewed` note to the row and it moves to the section below "
          "instead of being re-reported every morning.")
        w("")
        w("| provider | model | field | ours | litellm | litellm key |")
        w("|---|---|---|---|---|---|")
        for provider, model, key, field, mine, theirs, _ in fresh:
            w(f"| {provider} | `{model}` | {field} | {mine:g} | {theirs:g} | `{key}` |")
        w("")

    if reviewed:
        w("<details>")
        w(f"<summary>{len(reviewed)} disagreement(s) already reviewed and kept</summary>")
        w("")
        w("A person compared these and decided our number stands. They are listed "
          "so the decision stays visible, and folded so the section above is only "
          "ever what nobody has looked at yet.")
        w("")
        w("| provider | model | field | ours | litellm | reviewed |")
        w("|---|---|---|---|---|---|")
        for provider, model, _, field, mine, theirs, note in reviewed:
            w(f"| {provider} | `{model}` | {field} | {mine:g} | {theirs:g} | {note} |")
        w("")
        w("</details>")
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
        w("| provider | model | field | value | upstream |")
        w("|---|---|---|---|---|")
        for provider, model, field, value, origin in capability:
            w(f"| {provider} | `{model}` | {field} | `{value}` | {origin} |")
        w("")

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", default=UPSTREAM,
                        help="litellm JSON: a URL, or a path to a local copy")
    parser.add_argument("--registry",
                        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        help="registry checkout to sync (default: this one)")
    parser.add_argument("--models-dev", default=MODELS_DEV,
                        help="models.dev's api.json: a URL, or a path to a local copy")
    parser.add_argument("--check", action="store_true",
                        help="report only; write nothing")
    parser.add_argument("--out", help="also write the report here")
    args = parser.parse_args()

    try:
        upstream = load_upstream(args.upstream)
    except Exception as err:  # network, JSON, permissions — all the same to a caller
        print(f"could not read upstream {args.upstream}: {err}", file=sys.stderr)
        return 2

    # A models.dev failure is NOT fatal, unlike the one above. It supplies only
    # fields nobody else publishes and only where a row has none, so losing it
    # costs this run some fills and nothing else — while making it fatal would
    # let a third party's outage stop the price sync that is this job's actual
    # purpose.
    try:
        models_dev = index_models_dev(fetch_json(args.models_dev))
    except Exception as err:
        print(f"models.dev unavailable, continuing without it: {err}", file=sys.stderr)
        models_dev = {}

    applied, disagree, orphans, unclassified, capability, counts, contested = sync(
        args.registry, upstream, models_dev, apply=not args.check)
    report = render(applied, disagree, orphans, unclassified, capability, counts,
                    contested, apply=not args.check)
    print(report)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(report)
    # An applied write is the normal path and needs nobody. So does a
    # disagreement somebody has already reviewed and kept — re-raising it every
    # morning is how a report stops being read. What sets the exit code is only
    # what nobody has looked at yet.
    unreviewed = [d for d in disagree if not d[6]]
    return 1 if (unreviewed or orphans or unclassified) else 0


if __name__ == "__main__":
    sys.exit(main())
