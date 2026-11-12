"""Conversao entre os bytes de texto do jogo e o texto mostrado no editor.

No jogo (versao americana) um dialogo e' gravado assim:

    \\h(《Vyse》)Hey<7F>Fina.\\nHow<7F>are<7F>you<7F>feeling?\\e

* ``\\h(...)``  cabecalho com o nome de quem fala (entre 《 》 quando e' um nome)
* ``0x7F``      espaco
* ``\\n``       quebra de linha (barra invertida + n, literalmente)
* ``\\e``       fim da fala; ``\\c`` fim da pagina, a fala continua no texto seguinte
* demais bytes em Shift-JIS (… e' 0x8163, por exemplo)

No editor isso vira nome + corpo com espacos e quebras de linha normais. O
codigo final (\\e ou \\c) e' guardado a parte e recolocado na hora de gravar.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SPACE_BYTE = 0x7F
NBSP = chr(0xA0)                       # representa um 0x20 "de verdade", que o jogo quase nunca usa
OPEN, CLOSE = chr(0x300A), chr(0x300B)    # sinais que cercam o nome de quem fala
LQUOTE, RQUOTE = chr(0x201C), chr(0x201D)  # na fonte do jogo, [ e ] sao desenhados como aspas curvas
ELLIPSIS = chr(0x2026)

# trocas feitas antes de codificar: pontuacao que a fonte do jogo nao tem
NORMALIZE = {
    chr(0x2018): "'", chr(0x2019): "'", chr(0x2013): "-", chr(0x2014): "-", chr(9): " ",
    chr(0xAB): LQUOTE, chr(0xBB): RQUOTE, "[": LQUOTE, "]": RQUOTE,
}


class TextError(Exception):
    pass


@dataclass
class GameText:
    head: Optional[str]      # None = sem cabecalho \h()
    brackets: bool           # nome entre 《 》
    body: str
    end: str                 # "e", "c" ou ""


def _to_unicode(raw: bytes) -> str:
    out: List[str] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == SPACE_BYTE:
            out.append(" ")
            i += 1
        elif c == 0x5C and i + 1 < n and raw[i + 1] == 0x6E:
            out.append("\n")
            i += 2
        elif c == 0x20:
            out.append(NBSP)
            i += 1
        elif c == 0x5B:
            out.append(LQUOTE)
            i += 1
        elif c == 0x5D:
            out.append(RQUOTE)
            i += 1
        elif 0x21 <= c <= 0x7E:
            out.append(chr(c))
            i += 1
        elif (0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC) and i + 1 < n:
            try:
                ch = raw[i:i + 2].decode("shift_jis")
            except UnicodeDecodeError as exc:
                raise TextError(f"par Shift-JIS invalido {raw[i:i + 2].hex()}") from exc
            if len(ch) != 1 or ch in (" ", "\n", "\\", NBSP) or ord(ch) < 0x80:
                raise TextError(f"par Shift-JIS ambiguo {raw[i:i + 2].hex()}")
            out.append(ch)
            i += 2
        elif 0xA1 <= c <= 0xDF:
            out.append(bytes([c]).decode("shift_jis"))
            i += 1
        else:
            raise TextError(f"byte inesperado 0x{c:02x}")
    return "".join(out)


def decode(raw: bytes) -> GameText:
    """Bytes do jogo -> texto do editor. Levanta TextError se nao der para voltar igual."""
    u = _to_unicode(raw)
    head: Optional[str] = None
    brackets = False
    rest = u
    if u.startswith("\\h("):
        close = u.find(")", 3)
        if close < 0:
            raise TextError("cabecalho \\h( sem fechar")
        inner = u[3:close]
        rest = u[close + 1:]
        if len(inner) >= 2 and inner[0] == OPEN and inner[-1] == CLOSE:
            head, brackets = inner[1:-1], True
        else:
            head = inner
    end = ""
    if rest.endswith("\\e"):
        end, rest = "e", rest[:-2]
    elif rest.endswith("\\c"):
        end, rest = "c", rest[:-2]
    return GameText(head, brackets, rest, end)


class Encoder:
    """Codifica texto do editor em bytes do jogo usando a tabela de caracteres do projeto."""

    def __init__(self, charmap: Optional[Dict[str, int]] = None, strip_unknown: bool = True):
        self.charmap = dict(charmap or {})
        self.strip_unknown = strip_unknown
        self.missing: Dict[str, int] = {}     # caractere sem glifo -> quantas vezes
        self.stripped: Dict[str, int] = {}    # acento removido por falta de espaco na fonte
        self._open_quote = False

    def _char(self, ch: str) -> bytes:
        ch = NORMALIZE.get(ch, ch)
        if ch == '"' and '"' not in self.charmap:
            # aspas retas viram abre/fecha alternadamente
            self._open_quote = not self._open_quote
            return b"[" if self._open_quote else b"]"
        if ch == LQUOTE:
            return b"["
        if ch == RQUOTE:
            return b"]"
        if ch == " ":
            return bytes([SPACE_BYTE])
        if ch == NBSP:
            return b" "
        if ch == "\n":
            return b"\\n"
        code = self.charmap.get(ch)
        if code is not None:
            return bytes([code])
        o = ord(ch)
        if 0x21 <= o <= 0x7E:
            return bytes([o])
        base = unicodedata.normalize("NFD", ch)
        if len(base) > 1 and 0x21 <= ord(base[0]) <= 0x7E and all(unicodedata.combining(c) for c in base[1:]):
            # letra acentuada sem lugar na fonte: vai sem acento e fica registrada
            self.stripped[ch] = self.stripped.get(ch, 0) + 1
            return bytes([ord(base[0])])
        try:
            b = ch.encode("shift_jis")
        except UnicodeEncodeError:
            b = b""
        if len(b) == 2 or (len(b) == 1 and 0xA1 <= b[0] <= 0xDF):
            return b
        self.missing[ch] = self.missing.get(ch, 0) + 1
        return b"?"

    def text(self, s: str) -> bytes:
        self._open_quote = False
        return b"".join(self._char(c) for c in s)

    def encode(self, gt: GameText) -> bytes:
        out = bytearray()
        if gt.head is not None:
            out += b"\\h("
            if gt.brackets:
                out += OPEN.encode("shift_jis") + self.text(gt.head) + CLOSE.encode("shift_jis")
            else:
                out += self.text(gt.head)
            out += b")"
        out += self.text(gt.body)
        if gt.end:
            out += b"\\" + gt.end.encode("ascii")
        return bytes(out)


def columns(line: str, charmap: Optional[Dict[str, int]] = None) -> int:
    """Largura de uma linha em colunas da caixa de dialogo (caractere de meia largura = 1)."""
    w = 0
    cm = charmap or {}
    i = 0
    while i < len(line):
        ch = NORMALIZE.get(line[i], line[i])
        if ch == "\\" and i + 1 < len(line) and line[i + 1] in "ech":
            i += 2
            continue
        if ch in cm or ord(ch) < 0x7F or ch == NBSP:
            w += 1
        else:
            base = unicodedata.normalize("NFD", ch)
            if len(base) > 1 and ord(base[0]) < 0x7F:
                w += 1
            else:
                w += 2
        i += 1
    return w


def has_japanese(s: str) -> bool:
    for ch in s:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xFF61 <= o <= 0xFF9F:
            return True
    return False
