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

Na versao europeia (``eu=True``) as letras acentuadas sao um byte so' (Latin-1, com
0x85 = reticencias), o nome de quem fala costuma vir entre « » (0xAB/0xBB) e o que
sobrou em japones continua em Shift-JIS.
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
    brackets: bool           # nome entre 《 》 (ou « » na versao europeia)
    body: str
    end: str                 # "e", "c" ou ""
    style: str = "jp"        # delimitador do nome: "jp" = 《 》, "eu" = « »


EU_ELLIPSIS = 0x85
EU_LQ, EU_RQ = chr(0xAB), chr(0xBB)
EU_NBSP = chr(0x202F)      # representa o 0xA0 (espaco fino do frances) da versao europeia


def _eu_sjis(raw: bytes, i: int) -> Optional[str]:
    """Par Shift-JIS que sobrou no texto europeu (cabecalho 《》, linhas de teste)."""
    c = raw[i]
    if not (0x81 <= c <= 0x84 or 0x87 <= c <= 0x9F) or i + 1 >= len(raw):
        return None
    t = raw[i + 1]
    if t == 0x7F or not (0x40 <= t <= 0xFC):
        return None
    try:
        ch = raw[i:i + 2].decode("shift_jis")
    except UnicodeDecodeError:
        return None
    if len(ch) != 1 or ord(ch) < 0x100:
        return None
    return ch


def _to_unicode_eu(raw: bytes) -> str:
    out: List[str] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == SPACE_BYTE:
            out.append(" ")
        elif c == 0x5C and i + 1 < n and raw[i + 1] == 0x6E:
            out.append("\n")
            i += 2
            continue
        elif c == 0x20:
            out.append(NBSP)
        elif c == 0x5B:
            out.append(LQUOTE)
        elif c == 0x5D:
            out.append(RQUOTE)
        elif 0x21 <= c <= 0x7E:
            out.append(chr(c))
        elif c == EU_ELLIPSIS:
            out.append(ELLIPSIS)
        elif c == 0xA0:
            out.append(EU_NBSP)
        elif 0xA1 <= c <= 0xFF:
            out.append(chr(c))
        else:
            ch = _eu_sjis(raw, i)
            if ch is None:
                raise TextError(f"byte inesperado 0x{c:02x}")
            out.append(ch)
            i += 2
            continue
        i += 1
    return "".join(out)


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


def decode(raw: bytes, eu: bool = False) -> GameText:
    """Bytes do jogo -> texto do editor. Levanta TextError se nao der para voltar igual."""
    u = _to_unicode_eu(raw) if eu else _to_unicode(raw)
    head: Optional[str] = None
    brackets = False
    style = "jp"
    rest = u
    if u.startswith("\\h("):
        close = u.find(")", 3)
        if close < 0:
            raise TextError("cabecalho \\h( sem fechar")
        inner = u[3:close]
        rest = u[close + 1:]
        if len(inner) >= 2 and inner[0] == OPEN and inner[-1] == CLOSE:
            head, brackets = inner[1:-1], True
        elif eu and len(inner) >= 2 and inner[0] == EU_LQ and inner[-1] == EU_RQ:
            head, brackets, style = inner[1:-1], True, "eu"
        else:
            head = inner
    end = ""
    if rest.endswith("\\e"):
        end, rest = "e", rest[:-2]
    elif rest.endswith("\\c"):
        end, rest = "c", rest[:-2]
    return GameText(head, brackets, rest, end, style)


class Encoder:
    """Codifica texto do editor em bytes do jogo usando a tabela de caracteres do projeto."""

    def __init__(self, charmap: Optional[Dict[str, int]] = None, strip_unknown: bool = True,
                 eu: bool = False):
        self.eu = eu
        self.charmap = dict(charmap or {})
        self.strip_unknown = strip_unknown
        self.missing: Dict[str, int] = {}     # caractere sem glifo -> quantas vezes
        self.stripped: Dict[str, int] = {}    # acento removido por falta de espaco na fonte
        self._open_quote = False

    def _char(self, ch: str) -> bytes:
        if self.eu and ch in (EU_LQ, EU_RQ):
            return bytes([ord(ch)])
        if self.eu and ch == ELLIPSIS:
            return bytes([EU_ELLIPSIS])
        if self.eu and ch == EU_NBSP:
            return b"\xa0"
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
        if self.eu:
            # a fonte europeia tem as letras de 0xA1 a 0xFF (Latin-1), acentos inclusive
            if 0xA1 <= o <= 0xFF:
                return bytes([o])
            try:
                b = ch.encode("shift_jis")
            except UnicodeEncodeError:
                b = b""
            if len(b) == 2 and (0x81 <= b[0] <= 0x84 or 0x87 <= b[0] <= 0x9F):
                return b
            base = unicodedata.normalize("NFD", ch)
            if len(base) > 1 and 0x21 <= ord(base[0]) <= 0x7E:
                self.stripped[ch] = self.stripped.get(ch, 0) + 1
                return bytes([ord(base[0])])
            self.missing[ch] = self.missing.get(ch, 0) + 1
            return b"?"
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
            if gt.brackets and self.eu and getattr(gt, "style", "jp") == "eu":
                out += b"\xab" + self.text(gt.head) + b"\xbb"
            elif gt.brackets:
                out += OPEN.encode("shift_jis") + self.text(gt.head) + CLOSE.encode("shift_jis")
            else:
                out += self.text(gt.head)
            out += b")"
        out += self.text(gt.body)
        if gt.end:
            out += b"\\" + gt.end.encode("ascii")
        return bytes(out)


def columns(line: str, charmap: Optional[Dict[str, int]] = None, eu: bool = False) -> int:
    """Largura de uma linha em colunas da caixa de dialogo (caractere de meia largura = 1)."""
    w = 0
    cm = charmap or {}
    if eu:
        cm = dict(cm)
        for c in line:
            if ord(c) <= 0xFF or c in (ELLIPSIS, LQUOTE, RQUOTE, EU_NBSP):
                cm[c] = 1
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


def _wrap_width(s: str, charmap: Optional[Dict[str, int]], eu: bool = False) -> int:
    # um \c no meio da fala e' um valor que o jogo preenche (numero, nome): reserva 8 colunas
    return columns(s.replace("\\c", "XXXXXXXX"), charmap, eu)


def is_menu(original: str) -> bool:
    """Lista de opcoes: cada linha e' uma escolha entre aspas."""
    lines = original.split("\n")
    return len(lines) > 1 and all(l.strip().startswith(("“", '"')) for l in lines)


def wrap(body: str, cols: int, max_lines: int, charmap: Optional[Dict[str, int]] = None,
         eu: bool = False) -> Tuple[str, bool]:
    """Ajusta as quebras de linha para caber na caixa de dialogo.

    Cada pagina (separada por \\e) que ja' cabe fica como o tradutor escreveu. Se alguma
    linha passa de `cols` colunas ou a pagina passa de `max_lines` linhas, a pagina e'
    refeita juntando as linhas e quebrando nas palavras. Devolve (texto, mudou)."""
    parts = body.split("\\e")
    changed = False
    out = []
    for page in parts:
        lines = page.split("\n")
        fits = len(lines) <= max_lines and all(_wrap_width(l, charmap, eu) <= cols for l in lines)
        if fits:
            out.append(page)
            continue
        words = " ".join(l.strip() for l in lines).split()
        new: List[str] = []
        cur = ""
        for w in words:
            cand = w if not cur else cur + " " + w
            if not cur or _wrap_width(cand, charmap, eu) <= cols:
                cur = cand
            else:
                new.append(cur)
                cur = w
        if cur:
            new.append(cur)
        rebuilt = "\n".join(new)
        if rebuilt != page:
            changed = True
        out.append(rebuilt)
    return "\\e".join(out), changed
