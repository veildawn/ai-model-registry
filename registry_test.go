package registry_test

import (
	"encoding/json"
	"io/fs"
	"path"
	"testing"

	registry "github.com/veildawn/ai-model-registry"
)

// The embed pattern is `providers/*.json`, which silently matches whatever is
// there — so a provider added to index.json without its file, or a file added
// without listing it, both compile. The consumer only finds out at boot, on the
// offline path, where it has no second source to fall back to.
func TestEmbeddedFilesMatchIndex(t *testing.T) {
	raw, err := registry.Files.ReadFile("index.json")
	if err != nil {
		t.Fatal(err)
	}
	var idx struct {
		Version   int      `json:"version"`
		Providers []string `json:"providers"`
	}
	if err := json.Unmarshal(raw, &idx); err != nil {
		t.Fatal(err)
	}
	if idx.Version != 1 {
		t.Fatalf("index version = %d, want 1", idx.Version)
	}
	if len(idx.Providers) == 0 {
		t.Fatal("index lists no providers")
	}

	listed := make(map[string]bool, len(idx.Providers))
	for _, name := range idx.Providers {
		listed[name] = true
		var prov struct {
			Models []struct {
				Model string `json:"model"`
			} `json:"models"`
		}
		file := path.Join("providers", name+".json")
		body, err := registry.Files.ReadFile(file)
		if err != nil {
			t.Errorf("index lists %q but %s is not embedded: %v", name, file, err)
			continue
		}
		if err := json.Unmarshal(body, &prov); err != nil {
			t.Errorf("%s: %v", file, err)
		}
	}

	embedded, err := fs.Glob(registry.Files, "providers/*.json")
	if err != nil {
		t.Fatal(err)
	}
	for _, file := range embedded {
		name := path.Base(file)
		name = name[:len(name)-len(".json")]
		if !listed[name] {
			t.Errorf("%s is embedded but index.json does not list %q, so no consumer reads it", file, name)
		}
	}
}

func TestDeepSeekOfficialOffPeakPricing(t *testing.T) {
	body, err := registry.Files.ReadFile("providers/deepseek.json")
	if err != nil {
		t.Fatal(err)
	}
	var provider struct {
		Models []struct {
			Model           string  `json:"model"`
			PromptPer1M     float64 `json:"prompt_per_1m"`
			CompletionPer1M float64 `json:"completion_per_1m"`
			CacheReadPer1M  float64 `json:"cache_read_per_1m"`
			CacheWritePer1M float64 `json:"cache_write_per_1m"`
			Source          string  `json:"source"`
		} `json:"models"`
	}
	if err := json.Unmarshal(body, &provider); err != nil {
		t.Fatal(err)
	}

	type rates struct {
		prompt, completion, cacheRead, cacheWrite float64
	}
	want := map[string]rates{
		"deepseek-v4-flash": {0.22, 0.66, 0.007, 0},
		"deepseek-v4-pro":   {0.66, 1.98, 0.022, 0},
	}
	for _, model := range provider.Models {
		expected, ok := want[model.Model]
		if !ok {
			t.Errorf("unexpected DeepSeek model %q", model.Model)
			continue
		}
		delete(want, model.Model)
		if model.Source != "manual" {
			t.Errorf("%s source = %q, want manual so the official rates are not overwritten", model.Model, model.Source)
		}
		if got := (rates{model.PromptPer1M, model.CompletionPer1M, model.CacheReadPer1M, model.CacheWritePer1M}); got != expected {
			t.Errorf("%s rates = %#v, want %#v", model.Model, got, expected)
		}
	}
	for model := range want {
		t.Errorf("missing DeepSeek model %q", model)
	}
}
