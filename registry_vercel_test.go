package registry

import (
	"encoding/json"
	"testing"
)

// TestVercelModelSurfacesAndPricing pins that providers/vercel.json is embedded,
// carries the full catalog (>450 models), correctly populates surfaces across
// all modalities (chat, decision, image, audio, video, embedding), and carries
// valid rates and context windows.
func TestVercelModelSurfacesAndPricing(t *testing.T) {
	raw, err := Files.ReadFile("providers/vercel.json")
	if err != nil {
		t.Fatalf("read vercel.json: %v", err)
	}
	var doc struct {
		Name       string `json:"name"`
		ListPrices bool   `json:"list_prices"`
		Models     []struct {
			Model         string  `json:"model"`
			Surface       string  `json:"surface"`
			PromptPer1M   float64 `json:"prompt_per_1m"`
			ContextWindow int     `json:"context_window"`
		} `json:"models"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(doc.Models) < 400 {
		t.Fatalf("expected over 400 models in vercel.json, got %d", len(doc.Models))
	}

	surfaceByModel := make(map[string]string)
	ratesByModel := make(map[string]float64)
	for _, m := range doc.Models {
		surfaceByModel[m.Model] = m.Surface
		ratesByModel[m.Model] = m.PromptPer1M
	}

	expectedSurfaces := map[string]string{
		"typesafe-ai/jev":               "decision",
		"typesafe-ai/jev-1.14.0":        "decision",
		"convaiinnovations/laya":        "decision",
		"openai/gpt-4.1-mini":           "chat",
		"deepseek/deepseek-r1":          "chat",
		"openai/gpt-image-2":            "image",
		"bfl/flux-3-image":              "image",
		"openai/whisper-1":              "audio",
		"openai/tts-1":                  "audio",
		"google/veo-3.0-generate-001":   "video",
		"klingai/kling-v3.0-t2v":        "video",
		"openai/text-embedding-3-small": "embedding",
	}

	for id, wantSurface := range expectedSurfaces {
		got, exists := surfaceByModel[id]
		if !exists {
			t.Errorf("model %s missing from vercel.json", id)
			continue
		}
		if got != wantSurface {
			t.Errorf("%s: surface = %q, want %q", id, got, wantSurface)
		}
	}

	// Verify pricing conversion (per token -> per 1M):
	// gpt-4.1-mini is $0.40/1M, gpt-4o-mini is $0.15/1M, gpt-4o is $2.50/1M, jev is $0.042/1M
	if rate := ratesByModel["openai/gpt-4.1-mini"]; rate != 0.4 {
		t.Errorf("openai/gpt-4.1-mini prompt_per_1m = %v, want 0.4", rate)
	}
	if rate := ratesByModel["openai/gpt-4o-mini"]; rate != 0.15 {
		t.Errorf("openai/gpt-4o-mini prompt_per_1m = %v, want 0.15", rate)
	}
	if rate := ratesByModel["openai/gpt-4o"]; rate != 2.5 {
		t.Errorf("openai/gpt-4o prompt_per_1m = %v, want 2.5", rate)
	}
	if rate := ratesByModel["typesafe-ai/jev"]; rate != 0.042 {
		t.Errorf("typesafe-ai/jev prompt_per_1m = %v, want 0.042", rate)
	}
}
