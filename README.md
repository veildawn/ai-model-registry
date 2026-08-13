# ai-model-registry

Provider / model / pricing registry consumed by [ai-proxy-service](https://github.com/veildawn/ai-proxy-service).
The service syncs this data at startup (and on demand via the admin "sync" action);
prices are keyed by **(provider, model)** — the same model id served by different
providers carries its own independent price row.

## Layout

```
index.json            # {"version": 1, "providers": ["anthropic", ...]}
providers/<name>.json # one file per provider
go.mod, registry.go   # the same files, embedded, for offline consumers
```

## Two ways to read this data

Over **HTTP** (raw.githubusercontent), which is how a running deployment stays
current: it syncs at startup, every 24h, and on demand from the admin panel.
This is the path that wins whenever it succeeds.

As a **Go module**, which is the offline fallback a consumer builds in:

```go
import registry "github.com/veildawn/ai-model-registry"

// registry.Files is an embed.FS holding index.json and providers/*.json
// at the same paths they have here.
```

Same files, same layout, one parser on the consumer's side. The module exists so
a consumer never has to vendor a flattened copy into its own tree — a generated
file that diffs like source and can be hand-edited is a second source of truth
waiting to happen, and was one twice: researched effort ladders typed into
ai-proxy-service's snapshot existed only inside a build and were wiped by the
first sync that reached this repo. A module pins its version in the consumer's
`go.mod` and is checksummed in `go.sum`; there is nothing to hand-edit.

Bumping the fallback on the consumer side is `go get
github.com/veildawn/ai-model-registry@main && go mod tidy`. Untagged pseudo-
versions are fine — `main` is the only branch and every commit here is a fact
correction, not an API change.

## Provider file schema

```json
{
  "name": "anthropic",
  "display_name": "Anthropic",
  "models": [
    {
      "model": "claude-sonnet-4-5",
      "pricing_style": "anthropic",
      "prompt_per_1m": 3,
      "completion_per_1m": 15,
      "cache_read_per_1m": 0.3,
      "cache_write_per_1m": 3.75,
      "context_window": 200000,
      "input_modalities": ["text", "image"],
      "source": "litellm"
    }
  ]
}
```

- `pricing_style`: `openai` (cached tokens are a discounted subset of prompt tokens)
  or `anthropic` (input / cache_read / cache_write / output are separate buckets).
- All prices are USD per 1M tokens.
- Model ids are **lowercase**; the service lowercases the account's upstream model
  id before matching, so `MiniMax-M2` upstream matches `minimax-m2` here.
- A model id may appear under multiple providers with different prices.
- `context_window` (optional): the vendor's published input-token budget. A
  deployment that measured its own through an account probe outranks this.
- `input_modalities` (optional): what media the model can **read**, as
  `text` / `image` / `audio` / `video` — see below.
- `effort_levels` (optional): the reasoning depths the model can be asked for —
  see below.
- `source`: who owns this row's numbers — `litellm`, `vendor-api`,
  `cursor-docs` (all rewritten daily, do not hand-edit) or `manual` (ours,
  never touched by the job). See below.

## Who owns a row: `source`

A daily GitHub Action (`.github/workflows/sync-prices.yml`) runs
`scripts/sync_prices.py`, which rewrites every delegated row from
[litellm's public model database](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
and commits the result. Rates, context window and input modalities all come
across. **Editing a delegated row by hand is pointless — the next run reverts
it.** Take the row back by flipping its `source` to `manual` first.

| `source` | rows | what it means |
|---|---|---|
| `litellm` | 64 | the vendor's own litellm namespace carries this exact id. Read, not inferred. |
| `cursor-docs` | 181 | read from Cursor's own published table (see below). Rates from Cursor; context window and modalities from the vendor's row, since those do not change because a reseller fronts the model. |
| `vendor-api` | 34 | a surface that publishes no rates of its own and meters at the vendor's API list — `kiro` (16 of 18) and `antigravity` (18 of 22). Written from the vendor's row after this surface's own suffixes are stripped. **Derived, not read**, which is why it is named apart: an audit needs to see the difference. |
| `manual` | 98 | ours. The job compares and reports, and never writes. |

Delegation is deliberately maximal: an upstream that is occasionally wrong and
always fresh beats a hand-authored file that is occasionally right and always
rotting, which is what this repo was before — its only freshness signal was the
refresh date below, and nothing checked it.

`vendor-api` rests on the surface's own words. Antigravity sells credits and
Google does not publish the credit-to-token rate, but its plan documentation
says rate limits are "drawn down as per API pricing" — so the vendor's list is
that surface's meter by its own account. Kiro is the same shape. What was in
these rows before was an approximation of the same thing, sometimes stale
(antigravity carried 0.25/1.5 for `gemini-2.5-flash` against Google's 0.3/2.5).

The suffix stripping is the one assumption this repo makes: a reasoning depth,
an agent mode or a tiering suffix does not change the vendor's per-token rate,
so `gemini-3-flash-agent` is priced as `gemini-3-flash` and
`claude-opus-4-6-thinking` as `claude-opus-4-6`.

`cursor-docs` reads [Cursor's own table](https://cursor.com/docs/models-and-pricing.md),
which the vendor serves as `text/plain` markdown — so the adapter reads columns
rather than scraping HTML, and a layout change shows up as an empty parse, which
aborts the run rather than writing blank prices. 40 priced rows cover 181 of our
193 cursor ids.

Two things that page does not say in its columns, and the adapter has to know:

- **Effort suffixes do not change a rate.** Cursor bills per token; `-high` only
  changes how many get spent. So `gpt-5.4-high` and `gpt-5.4-low` both take the
  `GPT-5.4` row.
- **`-fast` does change it, and is documented in prose.** Where the table has an
  explicit row it wins — "Claude Opus 4.7 (fast mode)" is 30/150, six times its
  base. Where it does not, the fallback is **2x**, which the Notes corroborate
  twice: GPT-5 Fast is "2x price" (and its explicit row is exactly 2x), and Opus
  4.8's fast mode is "3x lower per-token pricing than Opus 4.7 fast mode" —
  30/3 and 150/3, which is 2x its own base. This is the adapter's one inference,
  and it corrects a real error: those 60 rows were carrying the base price.
  Watch the naming, too — that same model is "Claude 4.7 Opus" in the base row
  and "Claude Opus 4.7" in the fast row.

What stays `manual` is what no upstream answers:

- **Resellers who publish nothing**, where a vendor's rate would be fiction
  rather than derivation: `qoder`, `qoder-intl`, `workbuddy`.
- **Ids nothing upstream carries** — `k3`, `kimi-for-coding*`, every `mimo-*`,
  `grok-imagine-*`, `glm-5-turbo`, `qwen3.6-flash`, `kiro/deepseek-3.2`,
  `kiro/qwen3-coder-next`, `antigravity/gemini-pro-agent`,
  `antigravity/gpt-oss-120b-medium`, Antigravity's two `tab_*` models, and the
  Cursor ids its own table omits (`composer-2.5*`, `cursor-grok-4.5*`,
  `default`, `gpt-5.1*`). `cursor-grok-4.6*` is in that table (as `Grok 4.6`
  / `Grok 4.6 (Fast)`) and is delegated via an alias; litellm does not yet
  carry `grok-4.6`, so the xAI and OpenCode Go rows stay `manual`.

The job never writes a manual row. When litellm disagrees with one it keeps a
single open issue (label `price-drift`) up to date with the list, and closes it
when the list empties. Same for a delegated row whose upstream id disappeared,
and for any row that arrives with no `source` at all — those are treated as ours
and left alone, which is the safe direction.

Run it yourself with `python3 scripts/sync_prices.py --check` (reports, writes
nothing).

### `input_modalities` (optional)

What a model can perceive, so a surface can tell a person whether it will look at
their screenshot. The service's Kiro listings advertise it as the model's input
types, and a Kiro IDE builds its attach control from that answer.

- **Absent means unknown**, and that is a real third state — not `["text"]`. A
  reader falls through an absent value to the operator's own declaration on the
  catalog row, and finally to assuming the model can read images (so nothing
  stops working on an id nobody has described). Only a value that is actually
  here gets printed as a claim, which is the entire point of the field: an
  optimistic default is right for a routing gate and wrong for a badge.
- **Do not guess.** Leaving an id absent costs nothing; writing `["text"]` on a
  model that does read images turns off a working attach button, and writing
  `["text", "image"]` on one that does not walks the user into a 400.
- `text` is implied for every chat model; write it anyway so the list reads as a
  complete statement rather than a delta.

### `effort_levels` (optional)

The reasoning depths this model can be asked for, weakest first, from
`none` / `low` / `medium` / `high` / `xhigh` / `max`. The service publishes it on
`GET /v1/models` and an IDE builds its thinking-effort picker from it, so a rung
listed is a rung the request path has to deliver and a rung withheld is depth the
user is paying for and cannot select.

- **This is the only place a ladder should be written.** The service carries a
  build-time snapshot of this repo, but its boot sync REPLACES that snapshot
  wholesale — a ladder edited into the snapshot alone survives exactly until the
  next boot on any host that can reach GitHub. Facts go here.
- **The ceiling of the MODEL, not of the channel.** Absent means unknown, and the
  service then falls back to what the protocol cell serving it can carry — an
  upper bound. This field is the only input that can NARROW that: DeepSeek Flash
  takes `["low","high","max"]` while the OpenAI cell fronting it would advertise
  `low/medium/high/xhigh`.
- **`["none"]` is a statement, not an empty value** — "this model has no thinking
  depths at all". It is the right answer for every image / audio / video model,
  which would otherwise inherit the chat cell's ladder and advertise a reasoning
  control their endpoint does not take.
- **Write it on every provider serving the id.** A collapsed listing unions the
  pool, and a published ladder stands in for poolmates that publish none — so one
  reseller row without one cannot re-widen the model's ceiling, but a pool where
  NOBODY publishes falls to the wire tier for all of them.
- The daily job never touches this field, on delegated rows or manual ones.

### `hidden_models` (display blacklist, optional)

A provider file may carry a `hidden_models` array in addition to (or instead of)
`models`:

```json
{
  "name": "cursor",
  "display_name": "Cursor",
  "models": [],
  "hidden_models": ["claude-opus-4-7", "gpt-5.5", "gemini-3-flash"]
}
```

- This is the **one display input** the registry has. The service drops these ids
  from the model **listings** — the dashboard and `GET /v1/models` — so a reseller
  that mirrors the whole industry's catalog can be trimmed to its common models
  centrally instead of per deployment.
- It **never un-serves** anything: a hidden id an active account still advertises
  stays routable when a client names it explicitly. Serving is still a probe
  decision; this only affects what is advertised.
- Ids are **lowercase base ids** — the collapsed client-facing id without any
  route prefix or thinking/effort suffix (`claude-opus-4-8`, not
  `cursor/claude-opus-4-8-thinking-high`). Hiding a base hides its whole
  thinking-variant family. It has no effect on pricing.

## Providers

| name | display | notes |
|---|---|---|
| anthropic | Anthropic | canonical `claude-*` ids |
| codex | OpenAI (Codex) | `gpt-5.4` / `gpt-5.5` / `gpt-5.6-*`; `gpt-image-2` is the images route — see below |
| xai | xAI | `grok-*`; the four `grok-imagine-*` entries are **unpriced** — see below |
| kimi | Kimi (Moonshot) | `k3` priced; the two `kimi-for-coding*` are **unpriced** — see below |
| deepseek | DeepSeek | `deepseek-v4-flash` / `deepseek-v4-pro` |
| glm | GLM (Zhipu) | `glm-4.5` and `glm-4.6` are **unpriced** — see below |
| minimax | MiniMax | `MiniMax-M2`…`M3` upstream ids, lowercased here |
| mimo | MiMo (Xiaomi) | all six entries are **unpriced** — see below |
| cursor | Cursor | **prices none** — reseller; `hidden_models` only, trims uncommon `claude-*` / `gpt-5.*` / `gemini-*` |
| antigravity | Antigravity | **prices none** — reseller; `hidden_models` only, trims non-current Gemini/Claude |
| google-ai-studio | Google AI Studio | `hidden_models` trims niche Gemini (tts / music / robotics / research / gemma); the image family is **listed** — see below |
| opencode-go | OpenCode Go | curated open-model subscription (`opencode.ai/zen/go`); DeepSeek Flash/Pro use the official effort ladders |
| qoder-intl | Qoder International | same opaque `*model` aliases as `qoder`, priced from the intl edition's own model set; `auto` hidden (router alias) |

The registry only supplies rates and (via `hidden_models`) a listing blacklist; it
never adds or removes catalog models. What a deployment serves is decided by its
account pool's probes.

## Provenance and known limitations

**Everything in this section describes the `manual` rows only.** Delegated rows
are re-read from litellm every day and none of the caveats below apply to them;
where a caveat used to cover a row that is now delegated, it says so.

Last full hand refresh: **2026-07-17**. Every manual rate below was taken from
the vendor's own pricing page on that date. Read this section before trusting a
number — several entries encode a judgement call, not a fact.

### Currency

`glm`, `kimi`, and `minimax` publish in **CNY**. This file is USD-only, so those
rates were converted at:

> **USD/CNY = 6.7669** — ECB reference rate, 2026-07-16
> (cross-checked against open.er-api.com 6.78034 and fawazahmed0/currency-api 6.767994)

**This rate is frozen and nothing re-checks it.** Those USD figures drift out of
date from the day they were written. Re-derive them from the CNY source when the
rate moves materially. The durable fix is a `currency` field in this schema plus
conversion at billing time — not a hand-refreshed constant.

Delegation retired most of this. The `glm`, `minimax` and matched `qianwen` rows
now carry the vendor's own **international USD list** from litellm instead of a
conversion of its CN list — `zai/glm-4.7` at 0.6/2.2 where the CNY list gave
0.591/2.364. Those are two price lists, not two conversions of one, so the swap
is a real change in what gets billed, taken knowingly in exchange for never
having to re-derive them again. The frozen rate now survives only on the rows
litellm cannot match: `kimi` (`k3`, `k3-256k`), `glm-5-turbo`, `glm-5.2`,
`qwen3.6-flash`, `qwen3.8-max-preview`, and the resold copies of all of those.

### Tiered pricing is flattened

The four rate fields cannot express prices that vary by prompt length. Where a
vendor tiers, one tier was chosen:

| provider | tiers | chosen |
|---|---|---|
| glm | input <32K vs 32K+ (some models also tier on output length) | **32K+ (higher)** — this deployment's traffic is agentic and routinely exceeds 32K, so the base tier would systematically undercharge (up to 2× on `glm-4.7`) |
| xai | <200K vs ≥200K prompt (2× above) | base (<200K) |
| codex | <272K context | base |
| minimax | M3: ≤512K vs >512K input (2× above) | base (≤512K) |

### Image models: one input rate for two kinds of input token

`gpt-image-2` (added 2026-07-26 from developers.openai.com/api/docs/pricing) is
billed by OpenAI on **five** rates, not four:

| kind | rate |
|---|---|
| text input | $5.00 |
| cached text input | $1.25 |
| image input | $8.00 |
| cached image input | $2.00 |
| image output | $30.00 |

The four fields here cannot hold that, and the service reads a single
`input_tokens` figure off the upstream anyway — no text/image split reaches
billing. So the **text** rates were taken for input (5 / 1.25) and the **image
output** rate for output (30, the only kind these routes emit).

The consequence: `/v1/images/generations`, whose input is the text prompt, is
exact. `/v1/images/edits` charges the uploaded images' tokens at the text rate,
undercharging that bucket by 37.5%. Input is the small bucket for image work —
one 1024×1024 output is ~1.5K tokens at $30/1M — so this is a rounding error,
not a systematic leak. Batch rates (exactly half of every row above) do not
apply: nothing here goes through the Batch API.

**This reading is no longer in force.** `gpt-image-2` is delegated, and litellm
publishes the **text** output rate (10), so output went 30 → 10 and image
generation is now billed at a third of what it costs. That is the price of not
hand-holding the row. If it matters more than the freshness, set that one entry
back to `"source": "manual"` and restore 30 — the job will leave it alone.

### Unpriced entries (all rates 0)

A zero here means **"no published per-token rate"**, not "free". The service reads
these rows as unpriced (`catalog.Unpriced`), so they produce no cost.

| entries | why |
|---|---|
| `grok-imagine-image`, `grok-imagine-image-quality` | billed per image ($0.02 / $0.05), not per token |
| `grok-imagine-video`, `grok-imagine-video-1.5` | billed per second ($0.050 / $0.080), not per token |
| `mimo-v2.5*` (all 6) | Xiaomi's `token-plan-cn` endpoint is a subscription plan; no public per-token list price. `-asr` / `-tts*` are billed per character or second regardless |
| `kimi-for-coding`, `kimi-for-coding-highspeed` | coding-plan aliases; no public per-token price. (`kimi-k2.7-code` **is** published at ¥1.30/¥6.50/¥27.00, but that is a different model id and was not substituted) |

`glm-4.5` and `glm-4.6` used to be here — delisted from open.bigmodel.cn as of
2026-07-17 and therefore zeroed. They are delegated now and carry z.ai's
international rates (0.6/2.2) again, so a deployment still serving them bills
something rather than nothing.

### Image models are listed, not hidden (2026-07-29)

Every image-generation id was in `hidden_models` until the service grew an
`/v1/images/generations` route for the Gemini family and xAI. They are now
advertised: `gemini-*-image*` and `nano-banana-pro-preview` under
`google-ai-studio`, `gemini-3.1-flash-image` under `antigravity`, and
`grok-imagine-image` / `grok-imagine-image-quality` under `xai`.

The Gemini ids carry real per-token rates, so they bill correctly. **The two xAI
ids do not** — they are billed per image ($0.02 / $0.05), which this schema
cannot express, so a deployment now advertises two image models it charges
nothing for. Price them on the catalog row per deployment, or accept the give.

The `grok-imagine-video*` pair stays hidden: there is no video route to serve
them, and they are unpriceable for the same reason.

### Time-limited rates

These will silently become wrong. Nothing in this repo will warn you.

| entry | expires | reverts to |
|---|---|---|
| `claude-sonnet-5` | **2026-08-31** | 3 / 15 / 0.3 / 3.75 (currently the 2 / 10 / 0.2 / 2.5 intro rate) |
| Cursor `cursor-grok-4.6*` | **2026-08-19** | listed 2 / 6 / 0.5 (fast 4 / 12 / 1). Cursor's table notes a 50% launch discount for one week from 2026-08-12; this registry stores the published columns, not the promo. |
| `glm-*` `cache_write_per_1m` | unannounced | GLM's cache-storage charge is currently 限时免费 (free for a limited time), hence 0 |
| `minimax-m3` | unannounced | MiniMax lists 2.10/8.40/0.42 CNY as a 永久五折 rate against a 4.20/16.80/0.84 list price |

### Input modalities: 280 declared, 77 left absent (2026-08-03)

Delegated rows take theirs from litellm's `supported_modalities` /
`supports_vision` and are not covered by this section. What follows is the hand
pass over everything else — which is most of the file, since the resellers carry
no upstream at all.

The first pass declared only the families whose input media are a settled,
published fact, by id prefix rather than one id at a time:

| declared | as | evidence |
|---|---|---|
| `claude-*` (every provider's spelling) | text + image | the whole Claude 3+ line reads images |
| `gemini-*`, `nano-banana-*` | text + image | natively multimodal; the `*-tts` heads are text-only and were written that way |
| `gpt-5*` | text + image | the GPT-5 line reads images |
| `gpt-oss-120b*` | text | the open-weight model is text-only |
| `grok-4*`, `cursor-grok-4*` | text + image | Grok 4 reads images |
| `deepseek-3.2`, `deepseek-v3*` | text | DeepSeek's chat line is text-only; vision ships as separate `-VL` models |
| `qwen3-coder*` | text | the coder line is text-only; vision ships as `qwen-vl` |
| `glm-4.5`, `glm-4.5-air`, `glm-4.6` | text | text-only; the vision variants are the `-V` models |
| `minimax-m2` | text | text-only |

**The other 77 are absent on purpose** — nobody writing this could vouch for
them, and a wrong declaration is worse here than no declaration:

| provider | absent |
|---|---|
| glm | `glm-4.7`, `glm-5`, `glm-5-turbo`, `glm-5.1`, `glm-5.2` |
| minimax | `minimax-m2.1`…`m2.7` (incl. `-highspeed`), `minimax-m3` |
| kimi | `k3`, `k3-256k`, `kimi-for-coding*` |
| deepseek | `deepseek-v4-flash`, `deepseek-v4-pro` |
| qianwen | `qwen3.6-flash`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.8-max-preview`, + resold `deepseek-v4-pro` / `glm-5.2` |
| qoder, qoder-intl, workbuddy | every entry (all resold CN models above, plus `hy3`, `kimi-k2.6/2.7/k3`) |
| cursor | `composer-2.5*`, `default`, `glm-5.2-*`, `kimi-k2.7-code` |
| antigravity | `tab_flash_lite_preview`, `tab_jump_flash_lite_preview` |
| google-ai-studio | `deep-research-*` (3) |
| xai | `grok-build-0.1`, `grok-imagine-*` (4) |
| codex | `gpt-image-2` |
| mimo | all 6 |
| kiro | `glm-5`, `minimax-m2.1`, `minimax-m2.5` |

Fill these in as they are confirmed — one line each, and every deployment picks
it up on its next sync. A deployment that knows better before then declares it on
the catalog row, which outranks this file.

## Editing

**Check the row's `source` first.** A `litellm` row is rewritten by the daily job
and a hand edit to it will be gone by morning; flip it to `manual` in the same
commit if you mean to hold it yourself.

For a `manual` row: edit the relevant `providers/<name>.json`, keep model ids
unique within a file, then commit. Running deployments pick the change up on
their next sync.

When a CNY-priced rate changes, update it from the **vendor's CNY figure** and
re-convert — do not edit the USD number directly, or the next person cannot tell
what the source said.

A new entry with no `source` is treated as `manual` and reported until someone
classifies it, so adding a row never risks it being silently overwritten.

Adding or removing a provider means editing **both** `index.json` and
`providers/<name>.json`. `go test ./...` here checks the two agree — the Go
module embeds `providers/*.json` by glob, so a file the index does not list
compiles fine and is simply never read.
