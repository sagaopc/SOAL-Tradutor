"""Texturas GVR do jogo (as imagens: logotipo, placas, telas com texto desenhado).

Os arquivos .mld, .mll e .gvr (quase sempre comprimidos em AKLZ) guardam as imagens como
blocos "GVRT": cabecalho de 16 bytes (formato, largura, altura) e os pixels em ladrilhos,
do jeito do GameCube. Este modulo acha as texturas dentro de um arquivo, transforma cada
uma em imagem comum (para mostrar e exportar em PNG) e faz o caminho de volta, do PNG
editado para o formato original, no mesmo tamanho e no mesmo lugar do arquivo.

Precisa do Pillow (vem junto no .exe).
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

from . import aklz

FORMATS = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8",
           8: "C4", 9: "C8", 14: "CMPR"}
# ladrilho (largura, altura) e bits por pixel de cada formato
TILE = {0: (8, 8, 4), 1: (8, 4, 8), 2: (8, 4, 8), 3: (4, 4, 16), 4: (4, 4, 16), 5: (4, 4, 16),
        6: (4, 4, 32), 8: (8, 8, 4), 9: (8, 4, 8), 14: (8, 8, 4)}
F_MIPS, F_EXT_PAL, F_INT_PAL = 1, 2, 8


class TexError(Exception):
    pass


def have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def level_size(fmt: int, w: int, h: int) -> int:
    tw, th, bpp = TILE[fmt]
    return ((w + tw - 1) // tw) * ((h + th - 1) // th) * tw * th * bpp // 8


class Tex:
    """Uma textura dentro do arquivo."""

    def __init__(self, n, off, fmt, flags, w, h, size, gidx):
        self.n, self.off, self.fmt, self.flags, self.w, self.h = n, off, fmt, flags, w, h
        self.size, self.gidx = size, gidx
        self.pal_fmt = flags >> 4
        self.mips = bool(flags & F_MIPS)
        self.pal_len = 0
        if fmt in (8, 9) and flags & F_INT_PAL:
            self.pal_len = (16 if fmt == 8 else 256) * 2
        self.data_off = off + 16 + self.pal_len

    @property
    def fmt_name(self) -> str:
        return FORMATS.get(self.fmt, "?")

    @property
    def ok(self) -> bool:
        """Da' para mostrar e trocar."""
        if self.fmt not in TILE or not self.w or not self.h:
            return False
        if self.fmt in (8, 9) and not self.pal_len:
            return False                     # paleta em outro lugar
        return True

    def levels(self) -> List[Tuple[int, int, int]]:
        """(largura, altura, bytes) de cada nivel (o primeiro e' a imagem; os outros, mipmaps)."""
        out = [(self.w, self.h, level_size(self.fmt, self.w, self.h))]
        if self.mips:
            w, h = self.w, self.h
            total = out[0][2]
            room = self.size - 8 - self.pal_len
            while w > 1 and h > 1:
                w, h = max(1, w // 2), max(1, h // 2)
                n = level_size(self.fmt, w, h)
                if total + n > room:
                    break
                out.append((w, h, n))
                total += n
        return out

    def info(self) -> dict:
        return {"n": self.n, "w": self.w, "h": self.h, "fmt": self.fmt_name, "ok": self.ok,
                "mips": len(self.levels()) - 1 if self.ok else 0, "alpha": self.fmt in (2, 3, 5, 6, 14) or
                (self.fmt in (8, 9) and self.pal_fmt in (0, 2))}


class TexFile:
    def __init__(self, raw: bytes):
        self.compressed = aklz.is_compressed(raw)
        self.data = bytearray(aklz.decompress(raw) if self.compressed else raw)
        self.tex: List[Tex] = []
        d = self.data
        i = 0
        while True:
            i = d.find(b"GVRT", i)
            if i < 0 or i + 16 > len(d):
                break
            size = struct.unpack_from("<I", d, i + 4)[0]
            flags, fmt = d[i + 10], d[i + 11]
            w, h = struct.unpack_from(">HH", d, i + 12)
            gidx = 0
            if i >= 16 and d[i - 16:i - 12] in (b"GCIX", b"GBIX"):
                gidx = struct.unpack_from(">I", d, i - 8)[0]
            if 8 <= size <= len(d) - i - 8 + 32 and 0 < w <= 2048 and 0 < h <= 2048 and fmt in FORMATS:
                self.tex.append(Tex(len(self.tex), i, fmt, flags, w, h, size, gidx))
                i += 8 + min(size, len(d) - i - 8)
            else:
                i += 4

    def image(self, n: int):
        t = self.tex[n]
        if not t.ok:
            raise TexError("formato de imagem não suportado")
        pal = bytes(self.data[t.off + 16:t.off + 16 + t.pal_len]) if t.pal_len else None
        size = level_size(t.fmt, t.w, t.h)
        return decode(bytes(self.data[t.data_off:t.data_off + size]), t.fmt, t.w, t.h, pal, t.pal_fmt)

    def set_image(self, n: int, img) -> None:
        """Troca a textura n pela imagem (mesmo tamanho). Refaz os mipmaps."""
        from PIL import Image
        t = self.tex[n]
        if not t.ok:
            raise TexError("formato de imagem não suportado")
        if img.size != (t.w, t.h):
            raise TexError(f"a imagem tem {img.size[0]}×{img.size[1]}; a do jogo tem {t.w}×{t.h}")
        img = img.convert("RGBA")
        if img.tobytes() == self.image(n).tobytes():
            return                                   # nada mudou: fica o original, mipmaps inclusive
        o = t.data_off
        pal = bytes(self.data[t.off + 16:t.off + 16 + t.pal_len]) if t.pal_len else None
        for i, (w, h, size) in enumerate(t.levels()):
            lv = img if i == 0 else img.resize((w, h), Image.LANCZOS)
            old = bytes(self.data[o:o + size])
            new = encode(lv, t.fmt, pal, t.pal_fmt, old)
            assert len(new) == size, (len(new), size)
            self.data[o:o + size] = new
            o += size

    def set_blob(self, n: int, blob: bytes) -> None:
        t = self.tex[n]
        total = sum(x[2] for x in t.levels())
        if len(blob) != total:
            raise TexError("a imagem guardada não combina com este arquivo")
        self.data[t.data_off:t.data_off + total] = blob

    def blob(self, n: int) -> bytes:
        t = self.tex[n]
        total = sum(x[2] for x in t.levels())
        return bytes(self.data[t.data_off:t.data_off + total])

    def build(self) -> bytes:
        plain = bytes(self.data)
        return aklz.compress(plain) if self.compressed else plain


# ------------------------------------------------------------------ cores
def _rgb5a3(v: int) -> Tuple[int, int, int, int]:
    if v & 0x8000:
        return ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31, 255
    return ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17, ((v >> 12) & 7) * 255 // 7


def _to_rgb5a3(r: int, g: int, b: int, a: int) -> int:
    if a >= 240:
        return 0x8000 | ((r * 31 + 127) // 255) << 10 | ((g * 31 + 127) // 255) << 5 | ((b * 31 + 127) // 255)
    return ((a * 7 + 127) // 255) << 12 | ((r + 8) // 17) << 8 | ((g + 8) // 17) << 4 | ((b + 8) // 17)


def _rgb565(v: int) -> Tuple[int, int, int, int]:
    return ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255


def _to_rgb565(r: int, g: int, b: int) -> int:
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def _palette(pal: bytes, pal_fmt: int) -> List[Tuple[int, int, int, int]]:
    out = []
    for i in range(0, len(pal), 2):
        v = (pal[i] << 8) | pal[i + 1]
        if pal_fmt == 0:      # IA8: alfa, intensidade
            out.append((pal[i + 1], pal[i + 1], pal[i + 1], pal[i]))
        elif pal_fmt == 1:
            out.append(_rgb565(v))
        else:
            out.append(_rgb5a3(v))
    return out


_REV2 = bytes(((b & 3) << 6) | ((b & 12) << 2) | ((b & 48) >> 2) | ((b & 192) >> 6) for b in range(256))


# ------------------------------------------------------------------ ladrilhos
def _untile(data: bytes, w: int, h: int, tw: int, th: int, bpp: int) -> bytes:
    """Desfaz os ladrilhos: devolve os pixels em linhas (bpp bytes por pixel, bpp >= 1)."""
    W, H = (w + tw - 1) // tw * tw, (h + th - 1) // th * th
    rows = [bytearray(W * bpp) for _ in range(H)]
    o = 0
    step = tw * bpp
    for ty in range(0, H, th):
        for tx in range(0, W, tw):
            p = tx * bpp
            for y in range(th):
                rows[ty + y][p:p + step] = data[o:o + step]
                o += step
    return b"".join(bytes(r[:w * bpp]) for r in rows[:h])


def _tile(lin: bytes, w: int, h: int, tw: int, th: int, bpp: int) -> bytes:
    W, H = (w + tw - 1) // tw * tw, (h + th - 1) // th * th
    rows = []
    for y in range(H):
        r = lin[min(y, h - 1) * w * bpp:(min(y, h - 1) + 1) * w * bpp]
        if W > w:
            r = r + r[-bpp:] * (W - w)
        rows.append(r)
    out = bytearray()
    step = tw * bpp
    for ty in range(0, H, th):
        for tx in range(0, W, tw):
            p = tx * bpp
            for y in range(th):
                out += rows[ty + y][p:p + step]
    return bytes(out)


def _nibbles(data: bytes) -> bytes:
    out = bytearray(len(data) * 2)
    out[0::2] = bytes(b >> 4 for b in data)
    out[1::2] = bytes(b & 15 for b in data)
    return bytes(out)


# ------------------------------------------------------------------ decodificar
def decode(data: bytes, fmt: int, w: int, h: int, pal: Optional[bytes] = None, pal_fmt: int = 0):
    """Pixels do jogo -> imagem RGBA do Pillow."""
    from PIL import Image
    tw, th, bpp = TILE[fmt]
    if fmt == 14:
        return _decode_cmpr(data, w, h)
    if fmt in (0, 8):
        lin = _untile(_nibbles(data), w, h, 8, 8, 1)
    else:
        lin = _untile(data, w, h, tw, th, bpp // 8)
    if fmt == 0:
        g = Image.frombytes("L", (w, h), bytes(v * 17 for v in lin))
        return Image.merge("RGBA", (g, g, g, Image.new("L", (w, h), 255)))
    if fmt == 1:
        g = Image.frombytes("L", (w, h), lin)
        return Image.merge("RGBA", (g, g, g, Image.new("L", (w, h), 255)))
    if fmt == 2:
        g = Image.frombytes("L", (w, h), bytes((v & 15) * 17 for v in lin))
        a = Image.frombytes("L", (w, h), bytes((v >> 4) * 17 for v in lin))
        return Image.merge("RGBA", (g, g, g, a))
    if fmt == 3:
        a = Image.frombytes("L", (w, h), lin[0::2])
        g = Image.frombytes("L", (w, h), lin[1::2])
        return Image.merge("RGBA", (g, g, g, a))
    if fmt in (4, 5):
        f = _rgb565 if fmt == 4 else _rgb5a3
        cache = {}
        out = bytearray(w * h * 4)
        for i in range(w * h):
            v = (lin[2 * i] << 8) | lin[2 * i + 1]
            c = cache.get(v)
            if c is None:
                c = cache[v] = bytes(f(v))
            out[4 * i:4 * i + 4] = c
        return Image.frombytes("RGBA", (w, h), bytes(out))
    if fmt == 6:
        # cada ladrilho 4x4: 16 pares AR, depois 16 pares GB
        W, H = (w + 3) // 4 * 4, (h + 3) // 4 * 4
        out = bytearray(W * H * 4)
        o = 0
        for ty in range(0, H, 4):
            for tx in range(0, W, 4):
                ar, gb = data[o:o + 32], data[o + 32:o + 64]
                o += 64
                for y in range(4):
                    p = ((ty + y) * W + tx) * 4
                    for x in range(4):
                        k = (y * 4 + x) * 2
                        out[p + 4 * x:p + 4 * x + 4] = bytes((ar[k + 1], gb[k], gb[k + 1], ar[k]))
        return Image.frombytes("RGBA", (W, H), bytes(out)).crop((0, 0, w, h))
    if fmt in (8, 9):
        cols = _palette(pal or b"", pal_fmt)
        cols += [(0, 0, 0, 255)] * (256 - len(cols))
        tab = [bytes(c) for c in cols]
        return Image.frombytes("RGBA", (w, h), b"".join(tab[v] for v in lin))
    raise TexError("formato de imagem não suportado")


def _cmpr_to_dxt1(data: bytes, w: int, h: int) -> Tuple[bytes, int, int]:
    W, H = (w + 7) // 8 * 8, (h + 7) // 8 * 8
    bw = W // 4
    out = bytearray(len(data))
    o = 0
    for ty in range(0, H // 4, 2):
        for tx in range(0, bw, 2):
            for sb in range(4):
                b = data[o:o + 8]
                o += 8
                p = ((ty + (sb >> 1)) * bw + tx + (sb & 1)) * 8
                out[p:p + 8] = bytes((b[1], b[0], b[3], b[2])) + b[4:8].translate(_REV2)
    return bytes(out), W, H


def _decode_cmpr(data: bytes, w: int, h: int):
    from PIL import Image
    dxt, W, H = _cmpr_to_dxt1(data, w, h)
    try:
        img = Image.frombytes("RGBA", (W, H), dxt, "bcn", 1)
    except Exception:
        img = Image.frombytes("RGBA", (W, H), bytes(_decode_dxt1_slow(dxt, W, H)))
    return img.crop((0, 0, w, h)) if (W, H) != (w, h) else img


def _decode_dxt1_slow(dxt: bytes, W: int, H: int) -> bytearray:
    out = bytearray(W * H * 4)
    o = 0
    for by in range(0, H, 4):
        for bx in range(0, W, 4):
            c0, c1, bits = struct.unpack_from("<HHI", dxt, o)
            o += 8
            a, b = _rgb565(c0), _rgb565(c1)
            if c0 > c1:
                pal = [a, b, tuple((2 * x + y) // 3 for x, y in zip(a, b)), tuple((x + 2 * y) // 3 for x, y in zip(a, b))]
            else:
                pal = [a, b, tuple((x + y) // 2 for x, y in zip(a, b)), (0, 0, 0, 0)]
            for y in range(4):
                p = ((by + y) * W + bx) * 4
                for x in range(4):
                    out[p + 4 * x:p + 4 * x + 4] = bytes(pal[(bits >> (2 * (y * 4 + x))) & 3])
    return out


# ------------------------------------------------------------------ codificar
def encode(img, fmt: int, pal: Optional[bytes] = None, pal_fmt: int = 0, old: Optional[bytes] = None) -> bytes:
    """Imagem RGBA -> pixels do jogo. `old` sao os pixels originais do mesmo nivel: no CMPR,
    os blocos que nao mudaram ficam identicos ao original (sem perder qualidade)."""
    w, h = img.size
    tw, th, bpp = TILE[fmt]
    px = img.tobytes()
    n = w * h
    if fmt == 14:
        return _encode_cmpr(img, old)
    if fmt in (0, 1, 2, 3):
        la = img.convert("LA").tobytes()
        lum, al = la[0::2], la[1::2]
        if fmt == 0:
            v = bytes((x + 8) // 17 for x in lum)
            t = _tile(v, w, h, 8, 8, 1)
            return bytes((t[i] << 4) | t[i + 1] for i in range(0, len(t), 2))
        if fmt == 1:
            return _tile(lum, w, h, tw, th, 1)
        if fmt == 2:
            return _tile(bytes((((a + 8) // 17) << 4) | ((x + 8) // 17) for x, a in zip(lum, al)), w, h, tw, th, 1)
        lin = bytearray(n * 2)
        lin[0::2], lin[1::2] = al, lum
        return _tile(bytes(lin), w, h, tw, th, 2)
    if fmt in (4, 5):
        f = _rgb565 if fmt == 4 else _rgb5a3
        lin_old = _untile(old, w, h, 4, 4, 2) if old is not None and len(old) == level_size(fmt, w, h) else None
        lin = bytearray(n * 2)
        cache = {}
        dec = {}
        for i in range(n):
            c = px[4 * i:4 * i + 4]
            if lin_old is not None:
                ov = lin_old[2 * i:2 * i + 2]
                d = dec.get(ov)
                if d is None:
                    d = dec[ov] = bytes(f((ov[0] << 8) | ov[1]))
                if d == c or (d[3] == 0 and c[3] == 0):
                    lin[2 * i:2 * i + 2] = ov
                    continue
            v = cache.get(c)
            if v is None:
                v = _to_rgb565(c[0], c[1], c[2]) if fmt == 4 else _to_rgb5a3(c[0], c[1], c[2], c[3])
                cache[c] = v = bytes((v >> 8, v & 255))
            lin[2 * i:2 * i + 2] = v
        return _tile(bytes(lin), w, h, tw, th, 2)
    if fmt == 6:
        W, H = (w + 3) // 4 * 4, (h + 3) // 4 * 4
        lin = _tile(px, w, h, 4, 4, 4)
        out = bytearray()
        for o in range(0, len(lin), 64):
            t = lin[o:o + 64]
            ar, gb = bytearray(32), bytearray(32)
            ar[0::2], ar[1::2], gb[0::2], gb[1::2] = t[3::4], t[0::4], t[1::4], t[2::4]
            out += ar + gb
        return bytes(out)
    if fmt in (8, 9):
        cols = _palette(pal or b"", pal_fmt)
        tab = [bytes(c) for c in cols]
        old_idx = None
        if old is not None and len(old) == level_size(fmt, w, h):
            old_idx = _untile(_nibbles(old), w, h, 8, 8, 1) if fmt == 8 else _untile(old, w, h, tw, th, 1)
        cache = {}
        idx = bytearray(n)
        for i in range(n):
            c = px[4 * i:4 * i + 4]
            if old_idx is not None and old_idx[i] < len(tab):
                d = tab[old_idx[i]]
                if d == c or (d[3] == 0 and c[3] == 0):
                    idx[i] = old_idx[i]
                    continue
            v = cache.get(c)
            if v is None:
                r, g, b, a = c
                best, bd = 0, None
                for k, (pr, pg, pb, pa) in enumerate(cols):
                    d = (pa - a) ** 2 * 2 + ((pr - r) ** 2 + (pg - g) ** 2 + (pb - b) ** 2) * (a + 16) // 271
                    if bd is None or d < bd:
                        best, bd = k, d
                cache[c] = v = best
            idx[i] = v
        if fmt == 8:
            t = _tile(bytes(idx), w, h, 8, 8, 1)
            return bytes((t[i] << 4) | t[i + 1] for i in range(0, len(t), 2))
        return _tile(bytes(idx), w, h, tw, th, 1)
    raise TexError("formato de imagem não suportado")


def _block_dxt1(px: bytes) -> bytes:
    """16 pixels RGBA -> bloco no formato do jogo (cores em big-endian, pixel 0 nos bits altos)."""
    cols = [px[i:i + 4] for i in range(0, 64, 4)]
    solid = [c for c in cols if c[3] >= 128]
    if not solid:
        return b"\x00\x00\xff\xff\xff\xff\xff\xff"
    trans = len(solid) < 16
    uniq = set(solid)
    if len(uniq) == 1:
        c = solid[0]
        v = _to_rgb565(c[0], c[1], c[2])
        if not trans:
            # uma cor so': os dois extremos iguais nao servem (cairia no modo de 3 cores)
            return struct.pack(">HHI", v, v, 0) if True else b""
        return struct.pack(">HH", v, v) + bytes(_pack_idx([0 if c[3] >= 128 else 3 for c in cols]))
    # extremos: os pontos mais distantes ao longo do eixo de maior variacao
    lo = [min(c[k] for c in solid) for k in range(3)]
    hi = [max(c[k] for c in solid) for k in range(3)]
    ax = [hi[k] - lo[k] for k in range(3)]
    proj = [c[0] * ax[0] + c[1] * ax[1] + c[2] * ax[2] for c in solid]
    a = solid[proj.index(max(proj))]
    b = solid[proj.index(min(proj))]
    va, vb = _to_rgb565(a[0], a[1], a[2]), _to_rgb565(b[0], b[1], b[2])
    if va == vb:
        if not trans:
            return struct.pack(">HHI", va, vb, 0)
        return struct.pack(">HH", va, vb) + bytes(_pack_idx([0 if c[3] >= 128 else 3 for c in cols]))
    if trans:
        c0, c1 = min(va, vb), max(va, vb)          # c0 <= c1: 3 cores + transparente
    else:
        c0, c1 = max(va, vb), min(va, vb)          # c0 > c1: 4 cores
    p0, p1 = _rgb565(c0), _rgb565(c1)
    if trans:
        pal = [p0, p1, tuple((x + y) // 2 for x, y in zip(p0, p1))]
    else:
        pal = [p0, p1, tuple((2 * x + y) // 3 for x, y in zip(p0, p1)), tuple((x + 2 * y) // 3 for x, y in zip(p0, p1))]
    cache = {}
    idx = []
    for c in cols:
        if c[3] < 128:
            idx.append(3)
            continue
        k = cache.get(c)
        if k is None:
            bd = None
            for j, p in enumerate(pal):
                d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2
                if bd is None or d < bd:
                    k, bd = j, d
            cache[c] = k
        idx.append(k)
    return struct.pack(">HH", c0, c1) + bytes(_pack_idx(idx))


def _pack_idx(idx: List[int]) -> List[int]:
    return [(idx[r] << 6) | (idx[r + 1] << 4) | (idx[r + 2] << 2) | idx[r + 3] for r in (0, 4, 8, 12)]


def _encode_cmpr(img, old: Optional[bytes]) -> bytes:
    from PIL import Image
    w, h = img.size
    W, H = (w + 7) // 8 * 8, (h + 7) // 8 * 8
    if (W, H) != (w, h):
        big = Image.new("RGBA", (W, H))
        big.paste(img, (0, 0))
        img = big
    px = img.tobytes()
    ref = None
    if old is not None and len(old) == W * H // 2:
        ref = _decode_cmpr(old, W, H).tobytes()
    out = bytearray()
    o = 0
    stride = W * 4
    for ty in range(0, H, 8):
        for tx in range(0, W, 8):
            for sb in range(4):
                x, y = tx + (sb & 1) * 4, ty + (sb >> 1) * 4
                p = y * stride + x * 4
                blk = px[p:p + 16] + px[p + stride:p + stride + 16] + px[p + 2 * stride:p + 2 * stride + 16] + \
                    px[p + 3 * stride:p + 3 * stride + 16]
                if ref is not None:
                    rb = ref[p:p + 16] + ref[p + stride:p + stride + 16] + ref[p + 2 * stride:p + 2 * stride + 16] + \
                        ref[p + 3 * stride:p + 3 * stride + 16]
                    if _same_block(blk, rb):
                        out += old[o:o + 8]
                        o += 8
                        continue
                out += _block_dxt1(blk)
                o += 8
    return bytes(out)


def _same_block(a: bytes, b: bytes) -> bool:
    if a == b:
        return True
    for i in range(0, 64, 4):
        if a[i + 3] < 128 and b[i + 3] < 128:
            continue
        if a[i:i + 4] != b[i:i + 4]:
            return False
    return True
