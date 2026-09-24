#!/usr/bin/env python3
"""Ed25519 signing and verification, from the standard library only.

The registry signs its bundle so a consumer can tell the published prices
apart from anything else that answers on that URL. The consumer is Go and
verifies with crypto/ed25519; this side signs. Keeping this repository free
of third-party packages matters more than the ~90 lines it costs: the sync
workflow runs on a bare runner, and a dependency here is a dependency the
daily price job cannot start without.

RFC 8032, the reference implementation, with no shortcuts taken on the
clamping or the hash inputs. Run `--selftest` to check it against a vector
produced by Go's crypto/ed25519 — the implementation the consuming proxy
verifies with, which is the one that has to agree.

    python3 scripts/ed25519.py --selftest
"""
import hashlib
import sys

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)

_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = None


def _recover_x(y, sign):
    """The x coordinate on the curve for a y and a parity bit, or None."""
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return 0 if sign == 0 else None
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)  # extended coordinates: X, Y, Z, T


def _point_add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _point_mul(s, p):
    q = (0, 1, 1, 0)  # the neutral element
    while s > 0:
        if s & 1:
            q = _point_add(q, p)
        p = _point_add(p, p)
        s >>= 1
    return q


def _point_compress(p):
    zinv = pow(p[2], _P - 2, _P)
    x = p[0] * zinv % _P
    y = p[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _point_decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _point_equal(p, q):
    if (p[0] * q[2] - q[0] * p[2]) % _P != 0:
        return False
    if (p[1] * q[2] - q[1] * p[2]) % _P != 0:
        return False
    return True


def _expand(secret):
    """The clamped scalar and the prefix, from a 32-byte seed."""
    if len(secret) != 32:
        raise ValueError("an ed25519 seed is 32 bytes")
    digest = hashlib.sha512(secret).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def public_key(secret):
    """The 32-byte public key for a 32-byte seed."""
    a, _ = _expand(secret)
    return _point_compress(_point_mul(a, _G))


def key_id(public):
    """The stable identifier for a public key: the first 8 bytes, hex.

    The same shape the proxy's plugin signatures use, so one reader can
    recognise both kinds of key on sight.
    """
    return "ed25519:" + public[:8].hex()


def sign(secret, message):
    """The 64-byte signature of message under a 32-byte seed."""
    a, prefix = _expand(secret)
    public = _point_compress(_point_mul(a, _G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _L
    r_point = _point_mul(r, _G)
    r_bytes = _point_compress(r_point)
    h = int.from_bytes(hashlib.sha512(r_bytes + public + message).digest(), "little") % _L
    s = (r + h * a) % _L
    return r_bytes + int.to_bytes(s, 32, "little")


def verify(public, message, signature):
    """True when signature is message's signature under public."""
    if len(public) != 32 or len(signature) != 64:
        return False
    point = _point_decompress(public)
    if point is None:
        return False
    r_bytes = signature[:32]
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    r_point = _point_decompress(r_bytes)
    if r_point is None:
        return False
    h = int.from_bytes(hashlib.sha512(r_bytes + public + message).digest(), "little") % _L
    return _point_equal(_point_mul(s, _G), _point_add(r_point, _point_mul(h, point)))


# A vector produced by Go's crypto/ed25519 — which is what the proxy verifies
# with — and checked in here so a broken curve implementation cannot ship. It
# pins three things at once: the public key derivation, the exact signature
# bytes, and the fact that the signature verifies under the derived key. A
# hand-rolled implementation that gets the hash inputs or the clamping wrong
# fails on the bytes long before it fails on anything else.
_SELFTEST = {
    "secret": "b180130cde97d5707fdc6fd74b89b61175d894f16463c778e5ce032318182c6b",
    "public": "6f0082d786e8425cbdf12f0eb9c2cadbc27d7f16b65121591e8f7a3940c2cafc",
    "message": "all.json\nabc123\n",
    "signature": "1579982ede2159bfdc16c7d2d3a61170a6d64ddbf5e983ce1baf22ced64c5f35"
                 "acae8b8cadff3105e655047a481a43ba40c45ce58994182bab032649f1915e06",
}


def selftest():
    secret = bytes.fromhex(_SELFTEST["secret"])
    public = bytes.fromhex(_SELFTEST["public"])
    message = _SELFTEST["message"].encode()
    want = bytes.fromhex(_SELFTEST["signature"])

    derived = public_key(secret)
    if derived != public:
        return (f"public key mismatch:\n  want {public.hex()}\n  got  {derived.hex()}")
    got = sign(secret, message)
    if got != want:
        return f"signature mismatch:\n  want {want.hex()}\n  got  {got.hex()}"
    if not verify(public, message, got):
        return "verification rejected the signature it just produced"
    if verify(public, b"tampered", got):
        return "verification accepted a signature over a different message"
    if verify(public_key(b"\x01" * 32), message, got):
        return "verification accepted the signature under a different key"
    return None


if __name__ == "__main__":
    problem = selftest()
    if problem:
        print(f"ed25519 self-test FAILED: {problem}", file=sys.stderr)
        sys.exit(1)
    print("ed25519 self-test passed (Go crypto/ed25519 vector)")
