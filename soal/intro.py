"""Introducao do jogo ("In a world shrouded in mystery..."): 11 paginas de texto que sao
imagens, nao texto. Ficam em field/a297a.mld (versao americana) e em
field/a297ae.mld, a297af.mld, a297ag.mld e a297as.mld (versao europeia, um por idioma).

O .mld (comprimido em AKLZ) tem 11 texturas GVR de 512x512 no formato CMPR (DXT1 do
GameCube), uma por pagina, com o texto preto sobre fundo cinza-claro. A traducao e'
desenhada com uma fonte livre parecida com a original, na mesma altura da pagina, e a
textura e' trocada no lugar; o resto do arquivo nao muda.

Precisa do Pillow (vem junto no .exe).
"""

from __future__ import annotations

import io
import os
import struct
from typing import Dict, List, Optional, Tuple

from . import aklz

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FONTS = {
    "uncial": ("UncialAntiqua-Regular.ttf", 0.62, "Uncial (parecida com a americana)"),
    "gotica": ("UnifrakturMaguntia-Book.ttf", 0.86, "Gótica (parecida com a europeia)"),
}
# o texto original, so' para mostrar no editor e mandar para a traducao automatica
PAGES_EN = [
    "In a world shrouded\nin mystery…",
    "…the winds of change\nbegin to blow.",
    "Adventurers\ntake to the sky",
    "with dreams\nand hopes",
    "in search of fame\nand fortune.",
    "It is a time of great\nexploration…",
    "The world is\nthere for the taking,",
    "as brave souls challenge\nthe unknown.",
    "The answers to your\nwildest dreams await you!",
    "So, set your sails\nagainst the wind…",
    "…for the adventure is\njust beginning!",
]
EU_FILES = {"en": "a297ae.mld", "fr": "a297af.mld", "de": "a297ag.mld", "es": "a297as.mld"}
US_FILE = "a297a.mld"
KNOWN_SHA1 = {
    "a297a.mld": "be621547c7ff24826e3e621e2648ef00dff99082",
    "a297ae.mld": "34d7cda1fdaf4b2916ccdbe4433b49cd298a5f09",
    "a297as.mld": "d6c99e47c83ec16c1cd9145bb5c5059923764a47",
}
FILE_NAME = "introducao"     # nome do arquivo virtual na lista
W = H = 512


class IntroError(Exception):
    pass


def have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def file_for(eu: bool, slot: str = "en") -> str:
    return EU_FILES.get(slot or "en", EU_FILES["en"]) if eu else US_FILE


class Mld:
    def __init__(self, raw: bytes):
        self.compressed = aklz.is_compressed(raw)
        self.data = bytearray(aklz.decompress(raw) if self.compressed else raw)
        self.tex: List[int] = []           # posicao dos dados de cada pagina
        i = 0
        while True:
            i = self.data.find(b"GVRT", i)
            if i < 0:
                break
            fmt = self.data[i + 0xB]
            w, h = struct.unpack_from(">HH", self.data, i + 12)
            if fmt == 14 and (w, h) == (W, H):
                self.tex.append(i + 16)
            i += 8
        if len(self.tex) != len(PAGES_EN):
            raise IntroError(f"esperava {len(PAGES_EN)} paginas na introducao, achei {len(self.tex)}")

    def page(self, n: int) -> bytes:
        o = self.tex[n]
        return bytes(self.data[o:o + W * H // 2])

    def set_page(self, n: int, cmpr: bytes):
        o = self.tex[n]
        assert len(cmpr) == W * H // 2
        self.data[o:o + len(cmpr)] = cmpr

    def build(self) -> bytes:
        plain = bytes(self.data)
        return aklz.compress(plain) if self.compressed else plain


# ------------------------------------------------------------------ CMPR
def _c565(v):
    return ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31


def decode_cmpr(data: bytes) -> bytearray:
    """CMPR 512x512 -> RGB (3 bytes por pixel)."""
    out = bytearray(W * H * 3)
    o = 0
    for by in range(0, H, 8):
        for bx in range(0, W, 8):
            for sb in range(4):
                sx, sy = bx + (sb & 1) * 4, by + (sb >> 1) * 4
                c0, c1, bits = struct.unpack_from(">HHI", data, o)
                o += 8
                a, b = _c565(c0), _c565(c1)
                if c0 > c1:
                    pal = [a, b, tuple((2 * x + y) // 3 for x, y in zip(a, b)), tuple((x + 2 * y) // 3 for x, y in zip(a, b))]
                else:
                    pal = [a, b, tuple((x + y) // 2 for x, y in zip(a, b)), (0, 0, 0)]
                for y in range(4):
                    row = ((sy + y) * W + sx) * 3
                    for x in range(4):
                        c = pal[(bits >> (30 - 2 * (y * 4 + x))) & 3]
                        p = row + x * 3
                        out[p:p + 3] = bytes(c)
    return out


def _to565(c) -> int:
    r, g, b = c
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def encode_cmpr(rgb: bytes) -> bytes:
    """RGB 512x512 -> CMPR. Cada bloco 4x4 usa o pixel mais escuro e o mais claro como
    extremos; serve bem para texto escuro sobre fundo liso."""
    out = bytearray()
    for by in range(0, H, 8):
        for bx in range(0, W, 8):
            for sb in range(4):
                sx, sy = bx + (sb & 1) * 4, by + (sb >> 1) * 4
                px = []
                for y in range(4):
                    row = ((sy + y) * W + sx) * 3
                    for x in range(4):
                        p = row + x * 3
                        px.append((rgb[p], rgb[p + 1], rgb[p + 2]))
                lum = [r * 3 + g * 6 + b for r, g, b in px]
                hi = px[lum.index(max(lum))]
                lo = px[lum.index(min(lum))]
                c0, c1 = _to565(hi), _to565(lo)
                if c0 == c1:
                    out += struct.pack(">HHI", c0, c1, 0)
                    continue
                if c0 < c1:
                    c0, c1 = c1, c0
                a, b = _c565(c0), _c565(c1)
                pal = [a, b, tuple((2 * x + y) // 3 for x, y in zip(a, b)), tuple((x + 2 * y) // 3 for x, y in zip(a, b))]
                bits = 0
                for i, c in enumerate(px):
                    best = min(range(4), key=lambda k: sum((c[j] - pal[k][j]) ** 2 for j in range(3)))
                    bits |= best << (30 - 2 * i)
                out += struct.pack(">HHI", c0, c1, bits)
    return bytes(out)


# ------------------------------------------------------------------ paginas
def page_png(mld: Mld, n: int, crop: bool = True) -> bytes:
    from PIL import Image
    rgb = decode_cmpr(mld.page(n))
    im = Image.frombytes("RGB", (W, H), bytes(rgb))
    if crop:
        im = im.crop((0, 120, W, 392))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _layout(rgb: bytes) -> Tuple[Tuple[int, int, int], int, int, int, int]:
    """Cor do fundo, centro vertical do texto original, altura de uma linha, distancia
    entre linhas e largura do texto."""
    from collections import Counter
    cnt = Counter(bytes(rgb[i:i + 3]) for i in range(0, len(rgb), 3 * 7))
    bg = tuple(cnt.most_common(1)[0][0])
    dark = []
    left, right = W, 0
    for y in range(H):
        row = rgb[y * W * 3:(y + 1) * W * 3]
        xs = [i // 3 for i in range(0, len(row), 3) if row[i] < 100]
        dark.append(bool(xs))
        if xs:
            left, right = min(left, xs[0]), max(right, xs[-1])
    runs, s = [], None
    for y, v in enumerate(dark):
        if v and s is None:
            s = y
        if not v and s is not None:
            if y - s > 6:
                runs.append((s, y))
            s = None
    if not runs:
        return bg, 256, 58, 74, 400
    top, bot = runs[0][0], runs[-1][1]
    lh = max(r[1] - r[0] for r in runs)
    gap = (runs[-1][0] - runs[0][0]) // (len(runs) - 1) if len(runs) > 1 else 74
    return bg, (top + bot) // 2, lh, gap, right - left


def render_page(orig_cmpr: bytes, text: str, font: str = "uncial") -> bytes:
    """Desenha `text` (linhas separadas por \\n) no lugar do texto original da pagina e
    devolve a textura CMPR nova."""
    from PIL import Image, ImageDraw, ImageFont
    fname, squeeze, _label = FONTS.get(font, FONTS["uncial"])
    rgb = decode_cmpr(orig_cmpr)
    bg, center, lh, gap, ow = _layout(rgb)
    lines = [l.strip() for l in text.replace("\r", "").split("\n") if l.strip()] or [""]
    size = max(30, int(lh * 0.95))
    if len(lines) > 2:
        gap = int(gap * 0.82)
        size = int(size * 0.85)
    fnt = ImageFont.truetype(os.path.join(DATA_DIR, "fontes", fname), size)
    rendered = []
    for line in lines:
        L = Image.new("L", (2400, size * 2), 0)
        ImageDraw.Draw(L).text((10, int(size * 1.4)), line, font=fnt, fill=255, anchor="ls")
        bb = L.getbbox() or (0, 0, 1, 1)
        L = L.crop((bb[0], 0, bb[2], size * 2))
        rendered.append(L)
    # mesma largura do texto original (com folga), sem apertar demais as letras
    maxw = min(470, max(int(ow * 1.15), 280))
    widest = max(r.width for r in rendered) * squeeze
    sx = squeeze if widest <= maxw else squeeze * maxw / widest
    if sx < squeeze * 0.72:
        # apertar mais deforma as letras: diminui o tamanho em vez disso
        shrink = sx / (squeeze * 0.72)
        sx = squeeze * 0.72
        rendered = [r.resize((max(1, int(r.width * shrink)), max(1, int(r.height * shrink))), Image.LANCZOS)
                    for r in rendered]
        size = int(size * shrink)
    mask = Image.new("L", (W, H), 0)
    total = gap * (len(lines) - 1)
    first_base = center - total // 2 + lh // 2 - 4
    for i, L in enumerate(rendered):
        L = L.resize((max(1, int(L.width * sx)), L.height), Image.LANCZOS)
        base = first_base + i * gap
        y = base - int(size * 1.4)
        mask.paste(L, ((W - L.width) // 2, y), L)
    out = Image.new("RGB", (W, H), bg)
    out.paste((0, 0, 0), (0, 0), mask)
    return encode_cmpr(out.tobytes())


def preview_png(orig_cmpr: bytes, text: str, font: str = "uncial") -> bytes:
    from PIL import Image
    rgb = decode_cmpr(render_page(orig_cmpr, text, font))
    im = Image.frombytes("RGB", (W, H), bytes(rgb)).crop((0, 120, W, 392))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def entries() -> List[dict]:
    out = []
    for i, t in enumerate(PAGES_EN):
        out.append({"k": f"pagina{i + 1:02d}", "sec": f"página {i + 1}", "i": -1, "head": None, "br": False,
                    "body": t, "end": "", "page": i, "lim": {"bytes": None, "cols": 40, "lines": 3}})
    return [{"name": FILE_NAME, "label": "Introdução", "cat": "intro", "virt": "intro",
             "entries": out, "error": None}]


def build(raw: bytes, tr: Dict[int, str], font: str = "uncial") -> bytes:
    m = Mld(raw)
    for n, t in tr.items():
        m.set_page(n, render_page(m.page(n), t, font))
    out = m.build()
    chk = Mld(out)
    if len(chk.tex) != len(m.tex):
        raise IntroError("a introducao gravada nao passou na conferencia")
    return out
