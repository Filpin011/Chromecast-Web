"""Minimal pure-Python AES-128-CBC decryption.

Only used to peek at the first few KB of an HLS ``METHOD=AES-128`` segment so its
container can be sniffed (the whole segment is encrypted, so its bytes say nothing
otherwise). Speed is irrelevant at that size; no third-party crypto dependency needed.
"""

from __future__ import annotations


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _build_sbox() -> tuple[list[int], list[int]]:
    sbox = [0] * 256
    for i in range(256):
        # multiplicative inverse in GF(2^8), then the affine transform
        inv = 0 if i == 0 else next(x for x in range(1, 256) if _mul(i, x) == 1)
        s = inv
        for shift in range(1, 5):
            s ^= ((inv << shift) | (inv >> (8 - shift))) & 0xFF
        sbox[i] = s ^ 0x63
    inv_sbox = [0] * 256
    for i, s in enumerate(sbox):
        inv_sbox[s] = i
    return sbox, inv_sbox


SBOX, INV_SBOX = _build_sbox()
RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _expand_key(key: bytes) -> list[list[int]]:
    """11 round keys of 16 bytes (AES-128)."""
    if len(key) != 16:
        raise ValueError("AES-128 needs a 16-byte key")
    words = [list(key[i : i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        w = list(words[i - 1])
        if i % 4 == 0:
            w = w[1:] + w[:1]
            w = [SBOX[b] for b in w]
            w[0] ^= RCON[i // 4 - 1]
        words.append([a ^ b for a, b in zip(words[i - 4], w, strict=True)])
    return [[b for w in words[r * 4 : r * 4 + 4] for b in w] for r in range(11)]


def _decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    s = [b ^ k for b, k in zip(block, round_keys[10], strict=True)]
    for rnd in range(9, -1, -1):
        # inverse ShiftRows (state is column-major: index = col * 4 + row)
        s = [s[((c - r) % 4) * 4 + r] for c in range(4) for r in range(4)]
        s = [INV_SBOX[b] for b in s]
        s = [b ^ k for b, k in zip(s, round_keys[rnd], strict=True)]
        if rnd:
            out = []
            for c in range(4):
                a0, a1, a2, a3 = s[c * 4 : c * 4 + 4]
                out += [
                    _mul(a0, 14) ^ _mul(a1, 11) ^ _mul(a2, 13) ^ _mul(a3, 9),
                    _mul(a0, 9) ^ _mul(a1, 14) ^ _mul(a2, 11) ^ _mul(a3, 13),
                    _mul(a0, 13) ^ _mul(a1, 9) ^ _mul(a2, 14) ^ _mul(a3, 11),
                    _mul(a0, 11) ^ _mul(a1, 13) ^ _mul(a2, 9) ^ _mul(a3, 14),
                ]
            s = out
    return bytes(s)


def cbc_decrypt_prefix(data: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt the whole 16-byte blocks of ``data`` (a prefix of an AES-128-CBC
    ciphertext); a trailing partial block is dropped, padding is not removed."""
    if len(iv) != 16:
        raise ValueError("AES-128-CBC needs a 16-byte IV")
    round_keys = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data) - len(data) % 16, 16):
        block = data[i : i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(block, round_keys), prev, strict=True))
        prev = block
    return bytes(out)
