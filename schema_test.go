package registry_test

import (
	"encoding/json"
	"io/fs"
	"strings"
	"testing"

	registry "github.com/veildawn/ai-model-registry"
)

// Schema validation for the whole registry, which the index/file cross-check in
// registry_test.go does not attempt. It exists mainly for variant families: a
// family is the one shape here that can express something a flat file could not
// get wrong — a suffix listed twice, an override naming a suffix the family does
// not have, or two families expanding onto the same id. Every one of those is
// silent in the JSON and wrong in the consumer.

type variantOverride struct {
	Suffixes        []string `json:"suffixes"`
	PromptPer1M     float64  `json:"prompt_per_1m"`
	CompletionPer1M float64  `json:"completion_per_1m"`
	CacheReadPer1M  float64  `json:"cache_read_per_1m"`
	CacheWritePer1M float64  `json:"cache_write_per_1m"`
}

type variantFamily struct {
	Suffixes  []string          `json:"suffixes"`
	Overrides []variantOverride `json:"overrides"`
}

type model struct {
	Model    string         `json:"model"`
	Source   string         `json:"source"`
	Variants *variantFamily `json:"variants"`
}

type providerFile struct {
	Name         string   `json:"name"`
	DisplayName  string   `json:"display_name"`
	ListPrices   bool     `json:"list_prices"`
	Models       []model  `json:"models"`
	HiddenModels []string `json:"hidden_models"`
}

// topLevelKeys is the whole file-level vocabulary. A key outside it is either a
// typo or a field somebody added without teaching any consumer to read it, and
// both are invisible until something quietly does not work.
var topLevelKeys = map[string]bool{
	"name": true, "display_name": true, "list_prices": true,
	"models": true, "hidden_models": true,
}

func providerFiles(t *testing.T) map[string][]byte {
	t.Helper()
	paths, err := fs.Glob(registry.Files, "providers/*.json")
	if err != nil {
		t.Fatal(err)
	}
	out := make(map[string][]byte, len(paths))
	for _, p := range paths {
		body, err := registry.Files.ReadFile(p)
		if err != nil {
			t.Fatal(err)
		}
		out[p] = body
	}
	return out
}

func TestProviderFilesUseKnownTopLevelKeys(t *testing.T) {
	for path, body := range providerFiles(t) {
		var raw map[string]json.RawMessage
		if err := json.Unmarshal(body, &raw); err != nil {
			t.Errorf("%s: %v", path, err)
			continue
		}
		for key := range raw {
			if !topLevelKeys[key] {
				t.Errorf("%s: unknown top-level key %q", path, key)
			}
		}
	}
}

func TestVariantFamiliesAreWellFormed(t *testing.T) {
	for path, body := range providerFiles(t) {
		var doc providerFile
		if err := json.Unmarshal(body, &doc); err != nil {
			t.Errorf("%s: %v", path, err)
			continue
		}
		for _, m := range doc.Models {
			if m.Variants == nil {
				continue
			}
			if len(m.Variants.Suffixes) == 0 {
				t.Errorf("%s: %s carries an empty variant family; a family with no "+
					"suffix publishes no model at all", path, m.Model)
			}
			declared := map[string]bool{}
			for _, s := range m.Variants.Suffixes {
				if declared[s] {
					t.Errorf("%s: %s lists suffix %q twice, which would publish one id "+
						"as two entries", path, m.Model, s)
				}
				declared[s] = true
			}
			claimed := map[string]string{}
			for i, group := range m.Variants.Overrides {
				if len(group.Suffixes) == 0 {
					t.Errorf("%s: %s override %d applies to no suffix", path, m.Model, i)
				}
				for _, s := range group.Suffixes {
					if !declared[s] {
						t.Errorf("%s: %s override %d names suffix %q, which the family "+
							"does not publish", path, m.Model, i, s)
					}
					if previous, dup := claimed[s]; dup {
						t.Errorf("%s: %s suffix %q takes rates from two override groups "+
							"(%s and %d)", path, m.Model, s, previous, i)
					}
					claimed[s] = string(rune('0' + i))
				}
			}
		}
	}
}

// TestExpandedModelIDsAreUnique is the check the collapse makes necessary: two
// families, or a family and a flat row, can now name one id without the JSON
// looking wrong anywhere.
func TestExpandedModelIDsAreUnique(t *testing.T) {
	for path, body := range providerFiles(t) {
		var doc providerFile
		if err := json.Unmarshal(body, &doc); err != nil {
			continue // reported by the tests above
		}
		seen := map[string]string{}
		for _, m := range doc.Models {
			ids := []string{m.Model}
			if m.Variants != nil {
				ids = ids[:0]
				for _, s := range m.Variants.Suffixes {
					ids = append(ids, m.Model+s)
				}
			}
			for _, id := range ids {
				lower := strings.ToLower(id)
				if from, dup := seen[lower]; dup {
					t.Errorf("%s: %q is published by both %q and %q", path, id, from, m.Model)
				}
				seen[lower] = m.Model
			}
		}
	}
}

// TestEveryModelDeclaresASource keeps the ownership question answered. An
// unclassified row is treated as ours by the sync job, so it silently stops
// being kept fresh.
func TestEveryModelDeclaresASource(t *testing.T) {
	known := map[string]bool{"litellm": true, "vendor-api": true, "manual": true}
	for path, body := range providerFiles(t) {
		var doc providerFile
		if err := json.Unmarshal(body, &doc); err != nil {
			continue
		}
		for _, m := range doc.Models {
			if !known[m.Source] {
				t.Errorf("%s: %s has source %q, which no consumer or sync rule knows",
					path, m.Model, m.Source)
			}
		}
	}
}
