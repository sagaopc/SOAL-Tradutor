"""Fonte do jogo (FontData.US, formato AFNT) e geracao de letras acentuadas.

Estrutura:
    0x00  "AFNT", data, 0x10, 2
    0x10  u32 primeiro codigo (0x20), u32 celulas de meia largura (0x30),
          u32 ?, u32 glifos de largura inteira
    0x20  tabela: para cada celula u16 comprimido(0/1), u16 tamanho, u32 posicao
    ...   celulas de 24x24 pixels, 4 bits por pixel, em blocos 8x8 (formato I4 do
          GameCube); quando comprimida, pares (valor, repeticoes)

As 48 primeiras celulas guardam os caracteres 0x20-0x7F, dois por celula (12
pixels de largura cada). A versao americana nao tem letras acentuadas, entao
para o portugues elas sao desenhadas por cima de simbolos que os dialogos nao
usam (#, $, <, > ...), e o texto traduzido e' gravado com o codigo do simbolo.
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

CELL = 24
HALF = 12
RAW_SIZE = CELL * CELL // 2

Glyph = List[List[int]]      # 24 linhas x 12 colunas, valores 0..15


class FontError(Exception):
    pass


class Font:
    def __init__(self, data: bytes):
        if data[:4] != b"AFNT":
            raise FontError("nao e' um arquivo de fonte AFNT")
        self.head = bytes(data[:0x20])
        self.first_code, self.half_cells = struct.unpack_from(">II", data, 0x10)
        table_end = struct.unpack_from(">I", data, 0x24)[0]
        if table_end > len(data) or (table_end - 0x20) % 8:
            raise FontError("tabela de glifos invalida")
        self.cells: List[bytes] = []          # dados originais de cada celula (como no arquivo)
        self.flags: List[int] = []
        for o in range(0x20, table_end, 8):
            flag, size, pos = struct.unpack_from(">HHI", data, o)
            self.flags.append(flag)
            self.cells.append(bytes(data[pos:pos + size]))
        self._px: Dict[int, List[List[int]]] = {}
        self.dirty: set = set()

    # ------------------------------------------------------------- celulas
    @staticmethod
    def _unrle(raw: bytes) -> bytes:
        out = bytearray()
        for k in range(0, len(raw) - 1, 2):
            out += bytes([raw[k]]) * raw[k + 1]
        return bytes(out)

    @staticmethod
    def _rle(raw: bytes) -> bytes:
        out = bytearray()
        i, n = 0, len(raw)
        while i < n:
            v = raw[i]
            j = i + 1
            while j < n and raw[j] == v and j - i < 255:
                j += 1
            out += bytes([v, j - i])
            i = j
        return bytes(out)

    def cell_pixels(self, idx: int) -> List[List[int]]:
        px = self._px.get(idx)
        if px is not None:
            return px
        raw = self.cells[idx]
        if self.flags[idx]:
            raw = self._unrle(raw)
        if len(raw) != RAW_SIZE:
            raise FontError(f"celula {idx} com tamanho inesperado ({len(raw)})")
        px = [[0] * CELL for _ in range(CELL)]
        p = 0
        for ty in range(0, CELL, 8):
            for tx in range(0, CELL, 8):
                for y in range(8):
                    for xb in range(4):
                        b = raw[p]
                        p += 1
                        px[ty + y][tx + xb * 2] = b >> 4
                        px[ty + y][tx + xb * 2 + 1] = b & 15
        self._px[idx] = px
        return px

    def _pack(self, px: List[List[int]]) -> bytes:
        out = bytearray()
        for ty in range(0, CELL, 8):
            for tx in range(0, CELL, 8):
                for y in range(8):
                    for xb in range(4):
                        out.append((px[ty + y][tx + xb * 2] << 4) | px[ty + y][tx + xb * 2 + 1])
        return bytes(out)

    # -------------------------------------------------- caracteres de meia largura
    def has_code(self, code: int) -> bool:
        return self.first_code <= code < self.first_code + self.half_cells * 2

    def glyph(self, code: int) -> Glyph:
        if not self.has_code(code):
            raise FontError(f"codigo 0x{code:02x} fora da fonte")
        k = code - self.first_code
        px = self.cell_pixels(k // 2)
        x0 = HALF * (k % 2)
        return [row[x0:x0 + HALF] for row in px]

    def set_glyph(self, code: int, g: Glyph):
        if not self.has_code(code):
            raise FontError(f"codigo 0x{code:02x} fora da fonte")
        k = code - self.first_code
        px = self.cell_pixels(k // 2)
        x0 = HALF * (k % 2)
        for y in range(CELL):
            for x in range(HALF):
                px[y][x0 + x] = max(0, min(15, int(g[y][x])))
        self.dirty.add(k // 2)

    # --------------------------------------------------------------- gravar
    def build(self) -> bytes:
        blobs: List[Tuple[int, bytes]] = []
        for i, raw in enumerate(self.cells):
            if i in self.dirty:
                packed = self._pack(self._px[i])
                rle = self._rle(packed)
                blobs.append((1, rle) if len(rle) < len(packed) else (0, packed))
            else:
                blobs.append((self.flags[i], raw))
        table = bytearray()
        pos = 0x20 + 8 * len(blobs)
        body = bytearray()
        for flag, blob in blobs:
            table += struct.pack(">HHI", flag, len(blob), pos)
            body += blob
            pos += len(blob)
        out = bytearray(self.head) + table + body
        out += b"\0" * (-len(out) % 32)
        return bytes(out)


# ------------------------------------------------------------------ acentos
# desenhos de 4 linhas (ficam nas linhas 2-5 da celula, acima das minusculas)
_MARKS = {
    "acute": ["....9F", "...DF7", "..BF7.", "..F7.."],
    "grave": ["F9....", "7FD...", ".7FB..", "..7F.."],
    "circ": ["..9F9.", ".BFDFB", "9F7.7F", "F7...7"],
    "tilde": ["......", ".BF7.F", "FDBFDF", "F..7FB"],
    "diaer": ["......", "FF..FF", "FF..FF", "......"],
}
_CEDILLA = ["..7F..", "...BF.", "...7F.", ".FFF7."]      # linhas 20-23, abaixo da letra

_COMBINING = {
    "́": "acute", "̀": "grave", "̂": "circ", "̃": "tilde",
    "̈": "diaer", "̧": "cedilla",
}


def _ink_box(g: Glyph, y0=0, y1=CELL) -> Optional[Tuple[int, int, int, int]]:
    xs = [x for y in range(y0, y1) for x in range(HALF) if g[y][x] >= 6]
    ys = [y for y in range(y0, y1) for x in range(HALF) if g[y][x] >= 6]
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def _stamp(g: Glyph, pattern: List[str], top: int, center: float):
    w = len(pattern[0])
    left = int(round(center - (w - 1) / 2))
    left = max(0, min(HALF - w, left))
    for dy, row in enumerate(pattern):
        y = top + dy
        if not (0 <= y < CELL):
            continue
        for dx, ch in enumerate(row):
            if ch != ".":
                g[y][left + dx] = max(g[y][left + dx], int(ch, 16))


def _squash(g: Glyph, src_top: int, src_bottom: int, dst_top: int) -> Glyph:
    """Achata verticalmente as linhas [src_top, src_bottom] para caber em [dst_top, src_bottom]."""
    out = [[0] * HALF for _ in range(CELL)]
    for y in range(src_bottom + 1, CELL):
        out[y] = list(g[y])
    src_h = src_bottom - src_top + 1
    dst_h = src_bottom - dst_top + 1
    for dy in range(dst_h):
        a = src_top + dy * src_h / dst_h
        b = src_top + (dy + 1) * src_h / dst_h
        for x in range(HALF):
            acc = 0.0
            y = int(a)
            while y < b and y <= src_bottom:
                lo, hi = max(a, y), min(b, y + 1)
                acc += g[y][x] * (hi - lo)
                y += 1
            v = acc / (b - a)
            # reforca um pouco o traco para nao ficar apagado depois da media
            out[dst_top + dy][x] = max(0, min(15, int(round(v * 1.25))))
    return out


def accented_glyph(font: Font, ch: str) -> Optional[Glyph]:
    """Desenha a letra acentuada ch a partir da letra base que ja' existe na fonte."""
    import unicodedata
    dec = unicodedata.normalize("NFD", ch)
    if len(dec) != 2 or dec[1] not in _COMBINING or not (0x21 <= ord(dec[0]) <= 0x7E):
        return None
    base, mark = dec[0], _COMBINING[dec[1]]
    g = [list(r) for r in font.glyph(ord(base))]
    box = _ink_box(g)
    if box is None:
        return None
    x0, x1, y0, y1 = box
    center = (x0 + x1) / 2
    if mark == "cedilla":
        _stamp(g, _CEDILLA, 20, center + 0.5)
        return g
    if base == "i":
        # tira o pingo
        body = _ink_box(g, 7, CELL)
        for y in range(0, 7):
            for x in range(HALF):
                g[y][x] = 0
        if body:
            center = (body[0] + body[1]) / 2
    elif y0 < 7:
        # maiuscula ou letra alta: achata para abrir espaco em cima
        g = _squash(g, y0, y1, 7)
    for y in range(0, 6):
        for x in range(HALF):
            g[y][x] = 0
    _stamp(g, _MARKS[mark], 2, center)
    return g


def apply_charmap(font: Font, charmap: Dict[str, int]) -> List[str]:
    """Desenha na fonte cada caractere do mapa. Devolve os que nao puderam ser desenhados."""
    failed = []
    for ch, code in charmap.items():
        g = accented_glyph(font, ch)
        if g is None or not font.has_code(code):
            failed.append(ch)
            continue
        font.set_glyph(code, g)
    return failed
