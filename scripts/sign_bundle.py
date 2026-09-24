#!/usr/bin/env python3
"""Sign all.json, and prove the signature is current.

The proxy fetches this registry over HTTP from a mutable ref
(raw.githubusercontent.com/.../main), which means the bytes it bills against
are whatever that URL answers at the moment of the fetch. The Go module it
also embeds is pinned in go.mod and checksummed in go.sum, so the offline copy
cannot be tampered with — but the live sync could, and a price is a billing
fact: a changed rate is money, not cosmetics.

So the bundle carries a signature, and the consumer refuses a bundle whose
signature does not verify against the key pinned in its own binary. What that
buys, concretely: whoever can push to this repository cannot change what a
deployment bills at unless they also hold the signing seed, and a mirror or a
CDN cache that answers something else is rejected outright rather than
believed.

What is signed is the digest of all.json, bound to the artifact's name:

    "all.json\\n<sha256 of all.json, hex>\\n"

The name is inside the signed message so a signature over one artifact cannot
be replayed as a signature over another, which matters the moment there is a
second signed artifact to protect.

The signature file is all.json.sig, and it is deterministic: same bundle, same
key, same bytes. No timestamp, deliberately — a timestamp would make every
regeneration differ, and `--check` compares bytes.

    python3 scripts/sign_bundle.py --keygen      # a new seed, printed once
    python3 scripts/sign_bundle.py --pubkey      # the public key for a seed
    AI_PROXY_REGISTRY_SIGNING_SEED=<hex> python3 scripts/sign_bundle.py
    AI_PROXY_REGISTRY_SIGNING_SEED=<hex> python3 scripts/sign_bundle.py --check

The seed is an environment variable and is never written to disk, never
committed, and never printed except by --keygen, whose output exists to be
pasted into a repository secret exactly once.
"""
import argparse
import hashlib
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ed25519  # noqa: E402

ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLE = os.path.join(ROOT, "all.json")
SIGNATURE = os.path.join(ROOT, "all.json.sig")
SEED_ENV = "AI_PROXY_REGISTRY_SIGNING_SEED"

# The artifact name inside the signed message. Changing it invalidates every
# signature ever made, which is the point of naming it.
ARTIFACT = "all.json"


def _seed_from_env():
    raw = os.environ.get(SEED_ENV, "").strip()
    if not raw:
        return None
    try:
        seed = bytes.fromhex(raw)
    except ValueError:
        raise SystemExit(f"{SEED_ENV} is not hex")
    if len(seed) != 32:
        raise SystemExit(f"{SEED_ENV} is {len(seed)} bytes, want 32")
    return seed


def signing_message(digest_hex):
    """The exact bytes the signature covers."""
    return f"{ARTIFACT}\n{digest_hex}\n".encode()


def build(seed):
    """The signature document's exact bytes for the bundle on disk."""
    with open(BUNDLE, "rb") as fh:
        bundle = fh.read()
    digest = hashlib.sha256(bundle).hexdigest()
    public = ed25519.public_key(seed)
    signature = ed25519.sign(seed, signing_message(digest))
    doc = {
        "algorithm": "ed25519",
        "artifact": ARTIFACT,
        "sha256": digest,
        "key_id": ed25519.key_id(public),
        "sig": signature.hex(),
    }
    # Key order is fixed by this literal, so the file is reproducible.
    return json.dumps(doc, indent=2) + "\n", digest


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 when the signature is missing or stale")
    parser.add_argument("--keygen", action="store_true",
                        help="print a new seed (hex) and its public key, then stop")
    parser.add_argument("--pubkey", action="store_true",
                        help="print the public key for the seed in the environment")
    args = parser.parse_args()

    if args.keygen:
        seed = secrets.token_bytes(32)
        print(f"seed (store as the {SEED_ENV} secret, then discard): {seed.hex()}")
        print(f"public key (commit as keys/registry-signing.pub):        {ed25519.public_key(seed).hex()}")
        return 0

    seed = _seed_from_env()
    if seed is None:
        raise SystemExit(
            f"{SEED_ENV} is not set; it holds the 32-byte hex seed this registry signs with"
        )

    if args.pubkey:
        print(ed25519.public_key(seed).hex())
        return 0

    if not os.path.isfile(BUNDLE):
        raise SystemExit(f"{BUNDLE} is missing; run python3 scripts/bundle.py first")

    want, digest = build(seed)
    if args.check:
        try:
            with open(SIGNATURE) as fh:
                have = fh.read()
        except FileNotFoundError:
            print("all.json.sig is missing; run sign_bundle.py", file=sys.stderr)
            return 1
        if have != want:
            print("all.json.sig is stale (the bundle changed, or it was signed "
                  "with another key); run sign_bundle.py", file=sys.stderr)
            return 1
        print(f"all.json.sig is current (sha256 {digest[:16]}…)")
        return 0

    with open(SIGNATURE, "w") as fh:
        fh.write(want)
    print(f"wrote all.json.sig (sha256 {digest[:16]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
