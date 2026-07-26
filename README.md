# ai-model-registry

Provider / model / pricing registry consumed by [ai-proxy-service](https://github.com/veildawn/ai-proxy-service).
The service syncs this data at startup (and on demand via the admin "sync" action);
prices are keyed by **(provider, model)** — the same model id served by different
providers carries its own independent price row.

## Layout

```
index.json            # {"version": 1, "providers": ["anthropic", ...]}
providers/<name>.json # one file per provider
```

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
      "cache_write_per_1m": 3.75
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
| google-ai-studio | Google AI Studio | **prices none**; `hidden_models` only, trims niche Gemini (tts / image / robotics / research / gemma) |

The registry only supplies rates and (via `hidden_models`) a listing blacklist; it
never adds or removes catalog models. What a deployment serves is decided by its
account pool's probes.

## Provenance and known limitations

Last full refresh: **2026-07-17**. Every rate below was taken from the vendor's own
pricing page on that date. Read this section before trusting a number — several
entries encode a judgement call, not a fact.

### Currency

`glm`, `kimi`, and `minimax` publish in **CNY**. This file is USD-only, so those
rates were converted at:

> **USD/CNY = 6.7669** — ECB reference rate, 2026-07-16
> (cross-checked against open.er-api.com 6.78034 and fawazahmed0/currency-api 6.767994)

**This rate is frozen and nothing re-checks it.** Those USD figures drift out of
date from the day they were written. Re-derive them from the CNY source when the
rate moves materially. The durable fix is a `currency` field in this schema plus
conversion at billing time — not a hand-refreshed constant.

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

### Unpriced entries (all rates 0)

A zero here means **"no published per-token rate"**, not "free". The service reads
these rows as unpriced (`catalog.Unpriced`), so they produce no cost.

| entries | why |
|---|---|
| `grok-imagine-image`, `grok-imagine-image-quality` | billed per image ($0.02 / $0.05), not per token |
| `grok-imagine-video`, `grok-imagine-video-1.5` | billed per second ($0.050 / $0.080), not per token |
| `mimo-v2.5*` (all 6) | Xiaomi's `token-plan-cn` endpoint is a subscription plan; no public per-token list price. `-asr` / `-tts*` are billed per character or second regardless |
| `kimi-for-coding`, `kimi-for-coding-highspeed` | coding-plan aliases; no public per-token price. (`kimi-k2.7-code` **is** published at ¥1.30/¥6.50/¥27.00, but that is a different model id and was not substituted) |
| `glm-4.5`, `glm-4.6` | no longer listed on open.bigmodel.cn/pricing as of 2026-07-17, though their doc pages remain |

### Time-limited rates

These will silently become wrong. Nothing in this repo will warn you.

| entry | expires | reverts to |
|---|---|---|
| `claude-sonnet-5` | **2026-08-31** | 3 / 15 / 0.3 / 3.75 (currently the 2 / 10 / 0.2 / 2.5 intro rate) |
| `glm-*` `cache_write_per_1m` | unannounced | GLM's cache-storage charge is currently 限时免费 (free for a limited time), hence 0 |
| `minimax-m3` | unannounced | MiniMax lists 2.10/8.40/0.42 CNY as a 永久五折 rate against a 4.20/16.80/0.84 list price |

## Editing

Edit the relevant `providers/<name>.json`, keep model ids unique within a file,
then commit. Running deployments pick the change up on their next sync.

When a CNY-priced rate changes, update it from the **vendor's CNY figure** and
re-convert — do not edit the USD number directly, or the next person cannot tell
what the source said.
