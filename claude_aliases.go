package registry

// ClaudeDatedAliases maps the short alias a client names to the dated upstream
// id Anthropic serves it as. Clients send the short spelling while a catalog
// row is keyed by the dated one, so a gateway resolves between the two when
// matching a client's model against what it serves.
//
// It is Go code rather than a providers/*.json entry because the registry's
// data schema has no concept of "another name for the same model", and adding
// one would drag the sync tooling and the signed bundle into what is a fixed,
// hand-verified list: a row changes only when Anthropic retires a dated id,
// never with a pricing sync.
var ClaudeDatedAliases = map[string]string{
	"claude-sonnet-4-5": "claude-sonnet-4-5-20250929",
	"claude-sonnet-4-6": "claude-sonnet-4-6-20251114",
	"claude-opus-4-5":   "claude-opus-4-5-20251101",
	"claude-opus-4-6":   "claude-opus-4-6-20251101",
	"claude-haiku-4-5":  "claude-haiku-4-5-20251001",
	"claude-opus-4-1":   "claude-opus-4-1-20250805",
	"claude-sonnet-4":   "claude-sonnet-4-20250514",
	"claude-opus-4":     "claude-opus-4-20250514",
}
