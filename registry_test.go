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
