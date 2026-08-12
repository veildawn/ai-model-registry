// Package registry ships this repository's JSON files as an embedded
// filesystem, so a Go consumer can carry a build-time copy of the registry
// without vendoring a second copy into its own tree.
//
// That second copy is the whole reason this package exists. A consumer needs
// data on disk for the first boot on a host that cannot reach GitHub, and the
// obvious way to get it — generate a flattened JSON into the consumer's repo and
// commit it — produces a file that looks authoritative, diffs like source, and
// can be hand-edited. It had been, twice: two researched effort ladders were
// typed straight into the snapshot, existed only inside a build, and were wiped
// by the first sync that reached this repo. A module dependency cannot be
// hand-edited in place, pins its version in the consumer's go.mod, and is
// checksummed in go.sum.
//
// The bytes here are the same ones served over HTTP from raw.githubusercontent —
// same files, same layout — so a consumer parses one format either way and the
// offline copy can never drift into a second dialect.
package registry

import "embed"

// Files holds index.json and every providers/*.json at the paths they have in
// this repository. Read index.json first: it lists which provider files exist.
//
//go:embed index.json providers/*.json
var Files embed.FS
