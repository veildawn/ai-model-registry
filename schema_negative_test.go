package registry_test

import (
	"encoding/json"
	"testing"
)

// The schema checks above read real files, so a green run proves the data is
// clean and says nothing about whether the checks work. These drive the same
// rules over deliberately broken families, so a check that silently stopped
// asserting fails here instead of passing forever.

func familyFrom(t *testing.T, raw string) providerFile {
	t.Helper()
	var doc providerFile
	if err := json.Unmarshal([]byte(raw), &doc); err != nil {
		t.Fatal(err)
	}
	return doc
}

// expandedIDs mirrors what a consumer does with a stored entry, and what
// TestExpandedModelIDsAreUnique counts.
func expandedIDs(doc providerFile) []string {
	var out []string
	for _, m := range doc.Models {
		if m.Variants == nil {
			out = append(out, m.Model)
			continue
		}
		for _, s := range m.Variants.Suffixes {
			out = append(out, m.Model+s)
		}
	}
	return out
}

func TestBrokenFamiliesAreDetectable(t *testing.T) {
	cases := []struct {
		name, doc string
		broken    func(providerFile) bool
	}{
		{
			name: "a suffix listed twice publishes one id as two entries",
			doc: `{"name":"x","models":[{"model":"m","source":"manual",
			       "variants":{"suffixes":["-high","-high"]}}]}`,
			broken: func(d providerFile) bool {
				seen := map[string]bool{}
				for _, s := range d.Models[0].Variants.Suffixes {
					if seen[s] {
						return true
					}
					seen[s] = true
				}
				return false
			},
		},
		{
			name: "an override naming a suffix the family does not publish",
			doc: `{"name":"x","models":[{"model":"m","source":"manual",
			       "variants":{"suffixes":["-high"],
			       "overrides":[{"suffixes":["-fast"],"prompt_per_1m":9}]}}]}`,
			broken: func(d providerFile) bool {
				declared := map[string]bool{}
				for _, s := range d.Models[0].Variants.Suffixes {
					declared[s] = true
				}
				for _, g := range d.Models[0].Variants.Overrides {
					for _, s := range g.Suffixes {
						if !declared[s] {
							return true
						}
					}
				}
				return false
			},
		},
		{
			name: "two families expanding onto the same id",
			doc: `{"name":"x","models":[
			        {"model":"m","source":"manual","variants":{"suffixes":["-a-b"]}},
			        {"model":"m-a","source":"manual","variants":{"suffixes":["-b"]}}]}`,
			broken: func(d providerFile) bool {
				seen := map[string]bool{}
				for _, id := range expandedIDs(d) {
					if seen[id] {
						return true
					}
					seen[id] = true
				}
				return false
			},
		},
		{
			name: "a family publishing nothing",
			doc: `{"name":"x","models":[{"model":"m","source":"manual",
			       "variants":{"suffixes":[]}}]}`,
			broken: func(d providerFile) bool {
				return len(d.Models[0].Variants.Suffixes) == 0
			},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if !tc.broken(familyFrom(t, tc.doc)) {
				t.Fatal("the rule did not flag a document that violates it")
			}
		})
	}
}
