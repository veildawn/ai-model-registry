package registry_test

import (
	"encoding/json"
	"testing"

	registry "github.com/veildawn/ai-model-registry"
)

func TestOllamaRetirementKeepsCurrentCatalog(t *testing.T) {
	bundle := readBundle(t)
	raw, err := registry.Files.ReadFile("providers/ollama.json")
	if err != nil {
		t.Fatal(err)
	}
	for label, body := range map[string][]byte{"provider": raw, "bundle": bundle.Files["providers/ollama.json"]} {
		var doc struct {
			Models []struct {
				Model string `json:"model"`
			} `json:"models"`
		}
		if err := json.Unmarshal(body, &doc); err != nil {
			t.Fatal(err)
		}
		found := map[string]bool{}
		for _, model := range doc.Models {
			found[model.Model] = true
		}
		if found["deepseek-v4-flash"] || found["deepseek-v4-flash:0731"] {
			t.Errorf("%s still carries retired Ollama flash", label)
		}
		for _, name := range []string{"deepseek-v4.1-flash", "deepseek-v4-pro"} {
			if !found[name] {
				t.Errorf("%s lost current model %s", label, name)
			}
		}
	}
}
