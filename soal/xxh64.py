"""XXH64 (o hash que o Dolphin usa para dar nome as texturas de pacotes HD), em Python puro."""

import struct

M = 0xFFFFFFFFFFFFFFFF
P1, P2, P3, P4, P5 = (0x9E3779B185EBCA87, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9,
                      0x85EBCA77C2B2AE63, 0x27D4EB2F165667C5)


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & M


def _round(acc, v):
    acc = (acc + v * P2) & M
    return (_rotl(acc, 31) * P1) & M


def _merge(acc, v):
    acc ^= _round(0, v)
    return (acc * P1 + P4) & M


def xxh64(data: bytes, seed: int = 0) -> int:
    n = len(data)
    p = 0
    if n >= 32:
        v1 = (seed + P1 + P2) & M
        v2 = (seed + P2) & M
        v3 = seed & M
        v4 = (seed - P1) & M
        limit = n - 32
        unpack = struct.Struct("<4Q").unpack_from
        while p <= limit:
            a, b, c, d = unpack(data, p)
            v1 = (_rotl((v1 + a * P2) & M, 31) * P1) & M
            v2 = (_rotl((v2 + b * P2) & M, 31) * P1) & M
            v3 = (_rotl((v3 + c * P2) & M, 31) * P1) & M
            v4 = (_rotl((v4 + d * P2) & M, 31) * P1) & M
            p += 32
        h = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & M
        h = _merge(h, v1)
        h = _merge(h, v2)
        h = _merge(h, v3)
        h = _merge(h, v4)
    else:
        h = (seed + P5) & M
    h = (h + n) & M
    while p + 8 <= n:
        k = struct.unpack_from("<Q", data, p)[0]
        h ^= _round(0, k)
        h = (_rotl(h, 27) * P1 + P4) & M
        p += 8
    if p + 4 <= n:
        h ^= (struct.unpack_from("<I", data, p)[0] * P1) & M
        h = (_rotl(h, 23) * P2 + P3) & M
        p += 4
    while p < n:
        h ^= (data[p] * P5) & M
        h = (_rotl(h, 11) * P1) & M
        p += 1
    h ^= h >> 33
    h = (h * P2) & M
    h ^= h >> 29
    h = (h * P3) & M
    h ^= h >> 32
    return h
