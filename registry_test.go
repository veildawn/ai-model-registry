package registry_test

import (
	"encoding/json"
	"io/fs"
	"path"
	"strings"
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

func TestStepFunOfficialModels(t *testing.T) {
	body, err := registry.Files.ReadFile("providers/stepfun.json")
	if err != nil {
		t.Fatal(err)
	}
	var provider struct {
		Models []struct {
			Model           string   `json:"model"`
			PromptPer1M     float64  `json:"prompt_per_1m"`
			CompletionPer1M float64  `json:"completion_per_1m"`
			CacheReadPer1M  float64  `json:"cache_read_per_1m"`
			CacheWritePer1M float64  `json:"cache_write_per_1m"`
			Source          string   `json:"source"`
			Surface         string   `json:"surface"`
			EffortLevels    []string `json:"effort_levels"`
		} `json:"models"`
	}
	if err := json.Unmarshal(body, &provider); err != nil {
		t.Fatal(err)
	}

	type facts struct {
		prompt, completion, cacheRead, cacheWrite float64
		surface                                   string
	}
	want := map[string]facts{
		"step-5-preview":         {1.034447, 2.955563, 0.051722, 0, "chat"},
		"step-3.7-flash":         {0.199501, 1.197003, 0.0399, 0, "chat"},
		"step-3.5-flash-2603":    {0.103445, 0.310334, 0.020689, 0, "chat"},
		"step-3.5-flash":         {0.103445, 0.310334, 0.020689, 0, "chat"},
		"step-router-v1":         {0, 0, 0, 0, "chat"},
		"stepaudio-2.5-chat":     {1.477782, 3.694454, 0.295556, 0, "chat"},
		"stepaudio-2.5-realtime": {1.477782, 10.344471, 0.295556, 0, "audio"},
		"stepaudio-2.5-tts":      {0, 0, 0, 0, "audio"},
		"stepaudio-2.5-asr":      {0, 0, 0, 0, "audio"},
		"step-image-edit-2":      {0, 0, 0, 0, "image"},
	}
	wantEffort := map[string]string{
		"step-5-preview":         "low,medium,high",
		"step-3.7-flash":         "low,medium,high",
		"step-3.5-flash-2603":    "low,high",
		"step-3.5-flash":         "low,medium,high",
		"stepaudio-2.5-realtime": "none",
		"stepaudio-2.5-tts":      "none",
		"stepaudio-2.5-asr":      "none",
		"step-image-edit-2":      "none",
	}

	for _, model := range provider.Models {
		expected, ok := want[model.Model]
		if !ok {
			t.Errorf("unexpected StepFun model %q", model.Model)
			continue
		}
		delete(want, model.Model)
		if model.Source != "manual" {
			t.Errorf("%s source = %q, want manual so the official rates are not overwritten", model.Model, model.Source)
		}
		got := facts{model.PromptPer1M, model.CompletionPer1M, model.CacheReadPer1M, model.CacheWritePer1M, model.Surface}
		if got != expected {
			t.Errorf("%s facts = %#v, want %#v", model.Model, got, expected)
		}
		if expectedEffort, ok := wantEffort[model.Model]; ok {
			gotEffort := strings.Join(model.EffortLevels, ",")
			if gotEffort != expectedEffort {
				t.Errorf("%s effort_levels = %q, want %q", model.Model, gotEffort, expectedEffort)
			}
		} else if len(model.EffortLevels) != 0 {
			t.Errorf("%s effort_levels = %q, want absent (official docs do not publish a ladder)", model.Model, strings.Join(model.EffortLevels, ","))
		}
	}
	for model := range want {
		t.Errorf("missing StepFun model %q", model)
	}
}
