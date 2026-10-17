package registry

import (
	"encoding/json"
	"testing"
)

// The vercel file's decision surfaces are load-bearing for route planning:
// filterByModality reads them through modelregistry.Surface. This pins that the
// embedded snapshot carries them and that they parse.
func TestVercelDecisionSurfacesPresent(t *testing.T) {
	raw, err := Files.ReadFile("providers/vercel.json")
	if err != nil {
		t.Fatalf("read vercel.json: %v", err)
	}
	var doc struct {
		Models []struct {
			Model   string `json:"model"`
			Surface string `json:"surface"`
		} `json:"models"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("parse: %v", err)
	}
	decision := 0
	for _, m := range doc.Models {
		if m.Surface != "decision" {
			t.Errorf("%s: surface = %q, want decision", m.Model, m.Surface)
		}
		decision++
	}
	if decision == 0 {
		t.Fatal("vercel.json carries no models")
	}
}
