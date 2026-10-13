package registry

import (
	"strings"
	"testing"
)

// The table's shape is its contract: lowercase on both sides, the alias always
// the dated id minus its -YYYYMMDD suffix, one alias per dated id, and no rows
// lost since the count was pinned.
func TestClaudeDatedAliases(t *testing.T) {
	datedByID := map[string]string{}
	for short, dated := range ClaudeDatedAliases {
		if short == "" || dated == "" {
			t.Fatalf("empty pair %q -> %q", short, dated)
		}
		if strings.ToLower(short) != short || strings.ToLower(dated) != dated {
			t.Fatalf("pair %q -> %q must be lowercase on both sides", short, dated)
		}
		i := strings.LastIndex(dated, "-")
		if i < 0 || !isDateSuffix(dated[i+1:]) {
			t.Fatalf("dated id %q does not end in -YYYYMMDD", dated)
		}
		if bare := dated[:i]; bare != short {
			t.Fatalf("alias %q is not %q minus its date suffix (got %q)", short, dated, bare)
		}
		if prev, dup := datedByID[dated]; dup {
			t.Fatalf("dated id %q carries two aliases: %q and %q", dated, prev, short)
		}
		datedByID[dated] = short
	}
	if len(ClaudeDatedAliases) < 8 {
		t.Fatalf("only %d aliases remain; rows went missing", len(ClaudeDatedAliases))
	}
}

func isDateSuffix(s string) bool {
	if len(s) != 8 {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}
