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
- A model id may appear under multiple providers with different prices
  (e.g. `gpt-5.2` under both `codex` and `cursor`).

## Providers

| name | display | notes |
|---|---|---|
| anthropic | Anthropic | canonical `claude-*` ids |
| codex | OpenAI (Codex) | `gpt-*`, `o1/o3/o4*`, `chatgpt-*` |
| xai | xAI | `grok-*` |
| kiro | Kiro (CodeWhisperer) | accepts canonical and dotted (`claude-sonnet-4.5`) ids, billed at Anthropic rates |
| kimi | Kimi (Moonshot) | `kimi-k2*` family |
| cursor | Cursor | full IDE catalog incl. effort/speed/thinking variants (`-low/-high/-max/-fast/-thinking`); variants share the base model rate |
| deepseek | DeepSeek | `deepseek-chat`, `deepseek-v4-*` |

## Editing

Edit the relevant `providers/<name>.json`, keep model ids unique within a file,
then commit. Running deployments pick the change up on their next sync.
