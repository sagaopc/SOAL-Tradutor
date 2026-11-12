"""Leitura e reconstrucao dos arquivos de script .sct do Skies of Arcadia Legends.

Estrutura de um .sct (depois de descomprimir o AKLZ):

    0x00  8 bytes   cabecalho
    0x08  u32       quantidade de secoes (N)
    0x0C  N x 0x14  indice: u32 deslocamento (relativo ao fim do indice) + nome (16 bytes)
    ...             corpo: secoes de codigo e secoes de texto intercaladas
    ...             rodape: nomes de arquivos e outros textos soltos, separados por NUL

Uma secao de texto e' um rotulo (instrucao 9 + parametro) seguido do texto,
terminado em NUL e alinhado em 4 bytes. O codigo aponta para textos, para o
rodape e para outros trechos de codigo com deslocamentos RELATIVOS a posicao da
propria palavra que guarda o deslocamento. Por isso, quando um texto muda de
tamanho, tudo que vem depois anda e todos esses deslocamentos precisam ser
recalculados. Para achar todos eles o codigo e' percorrido instrucao por
instrucao, usando a tabela de parametros em data/instructions.json (derivada do
projeto SALSA, de jahorta, GPL-3.0).
"""

from __future__ import annotations

import json
import os
import struct
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import aklz

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_TABLE: Optional[Dict[int, dict]] = None

MAX_INST = 265
_STOP = 0x1D
_SINGLE_WORD_SCPT = (0x7F7FFFFF, 0x7FFFFFFF, 0x00800000, _STOP)

I_JUMP_IF_FALSE = 0
I_SWITCH = 3
I_LABEL = 9
I_JUMP = 10
I_CALL = 11
I_RETURN = 12
I_NO_REFRESH = 13
I_SCHEDULE = 129


def instruction_table() -> Dict[int, dict]:
    global _TABLE
    if _TABLE is None:
        with open(os.path.join(_DATA_DIR, "instructions.json"), encoding="utf-8") as fh:
            raw = json.load(fh)["instructions"]
        _TABLE = {int(k): v for k, v in raw.items()}
    return _TABLE


class SctError(Exception):
    pass


@dataclass
class Link:
    origin: int          # posicao (no corpo) da palavra que guarda o deslocamento
    target: int          # posicao (no corpo) apontada
    kind: str            # string | footer | jump | switch | call
    inst: int            # instrucao dona do link
    little: bool = False  # palavra gravada em little-endian


@dataclass
class Section:
    index: int
    name: str
    raw_name: bytes
    start: int
    end: int
    kind: str = "code"            # code | string
    text_start: int = -1          # so' para secoes de texto
    text_end: int = -1            # posicao do NUL final
    padded_end: int = -1          # fim do texto ja' com NUL e alinhamento
    insts: List[Tuple[int, int, int]] = field(default_factory=list)   # (inicio, fim, id)
    unknown: List[Tuple[int, int]] = field(default_factory=list)      # trechos nao percorridos
    warnings: List[str] = field(default_factory=list)


@dataclass
class FooterString:
    start: int
    end: int          # posicao do NUL
    refs: int = 0
    dialog: bool = False


class SctFile:
    """Um .sct carregado, com secoes, textos e links localizados."""

    def __init__(self, data: bytes, name: str = ""):
        self.name = name
        self.was_compressed = aklz.is_compressed(data)
        raw = aklz.decompress(data)
        self.raw = raw
        if len(raw) < 12:
            raise SctError("arquivo pequeno demais para ser um .sct")
        self.header = raw[:8]
        count = struct.unpack_from(">I", raw, 8)[0]
        if count > 0x10000 or 12 + count * 0x14 > len(raw):
            raise SctError("indice de secoes invalido")
        self.base = 12 + count * 0x14
        self.body = raw[self.base:]
        self.sections: List[Section] = []
        self.links: List[Link] = []
        self.footer: List[FooterString] = []
        self.footer_start = len(self.body)
        self.problems: List[str] = []

        offs = []
        for i in range(count):
            o = 12 + i * 0x14
            off = struct.unpack_from(">I", raw, o)[0]
            rn = raw[o + 4:o + 0x14]
            nm = rn.split(b"\0")[0].decode("shift_jis", "replace")
            offs.append((off, rn, nm))
        blen = len(self.body)
        for i, (off, rn, nm) in enumerate(offs):
            end = offs[i + 1][0] if i + 1 < count else blen
            if off > blen or end > blen or end < off:
                raise SctError(f"secao {nm!r} com limites invalidos")
            self.sections.append(Section(i, nm, rn, off, end))
        self._analyse()

    # ------------------------------------------------------------------ leitura
    def _be(self, pos: int) -> int:
        return struct.unpack_from(">I", self.body, pos)[0]

    def _le(self, pos: int) -> int:
        return struct.unpack_from("<I", self.body, pos)[0]

    def _rd(self, pos: int, little: bool) -> int:
        if pos + 4 > len(self.body):
            raise SctError(f"leitura alem do fim do arquivo em 0x{pos:x}")
        return self._le(pos) if little else self._be(pos)

    @staticmethod
    def _signed(v: int) -> int:
        return v - 0x100000000 if v & 0x80000000 else v

    # -------------------------------------------------------- percurso do codigo
    def _skip_scpt(self, pos: int, little: bool) -> Tuple[int, Optional[float]]:
        """Avanca sobre um parametro SCPT. Devolve (nova posicao, valor literal ou None)."""
        first = self._rd(pos, little)
        if first in _SINGLE_WORD_SCPT:
            return pos + 4, None
        start = pos
        tokens = 0
        literal = None
        while True:
            w = self._rd(pos, little)
            if w == _STOP:
                pos += 4
                break
            tokens += 1
            if tokens > 2048:
                raise SctError(f"parametro SCPT longo demais em 0x{start:x}")
            if 0x04000000 <= w < 0x08000000:
                raw = self.body[pos + 4:pos + 8]
                if len(raw) < 4:
                    raise SctError(f"parametro SCPT truncado em 0x{start:x}")
                if tokens == 1:
                    literal = struct.unpack("<f" if little else ">f", raw)[0]
                pos += 8
            else:
                pos += 4
        if tokens != 1:
            literal = None
        return pos, literal

    def _decode_inst(self, inst_id: int, pos: int, little: bool, sec: Section):
        """pos aponta para a palavra da instrucao. Devolve (fim, links)."""
        spec = instruction_table()[inst_id]
        types = spec["params"]
        loop = spec.get("loop") or []
        loop_set = set(loop)
        link_param = spec.get("link")
        masks = spec.get("mask") or {}
        links: List[Link] = []
        values: Dict[int, Optional[float]] = {}
        pos += 4

        def one(pid: int, pos: int) -> int:
            t = types[pid]
            if t.startswith("scpt"):
                pos, lit = self._skip_scpt(pos, little)
                values[pid] = lit
                return pos
            raw = self._rd(pos, little)
            m = masks.get(str(pid))
            val = raw & m if m is not None else raw
            values[pid] = val
            if pid == link_param:
                sval = self._signed(val)
                kind = _link_kind(t)
                links.append(Link(pos, pos + sval, kind, inst_id, little))
            return pos + 4

        pid = 0
        n = len(types)
        while pid < n and pid not in loop_set:
            pos = one(pid, pos)
            pid += 1
        if loop:
            cond = spec.get("loop_cond")
            iters = values.get(spec["loop_iter"]) or 0
            do_loop = True
            if cond and cond["Location"] == "External":
                if values.get(cond["Parameter"]) == cond["Value"]:
                    do_loop = False
            if do_loop:
                if iters > 4096:
                    raise SctError(f"laco com {iters} repeticoes em 0x{pos:x} (instrucao {inst_id})")
                for _ in range(int(iters)):
                    for lp in loop:
                        pos = one(lp, pos)
                    if cond and cond["Location"] == "Internal":
                        v = values.get(cond["Parameter"])
                        if v is not None and int(v) & 0xFFFF == cond["Value"]:
                            break
            for pid in range(n):
                if pid not in loop_set and pid not in values:
                    pos = one(pid, pos)
        return pos, links

    def _walk(self, sec: Section, pos: int, end: int, done: Dict[int, int], pending: List[int]):
        """Percorre linearmente a partir de pos ate' um retorno, salto ou trecho ja' conhecido."""
        while pos < end:
            if pos in done:
                return
            if pos % 4:
                raise SctError(f"posicao desalinhada 0x{pos:x} em {sec.name}")
            little = False
            w = self._be(pos)
            if w > MAX_INST:
                w = self._le(pos)
                little = True
                if w > MAX_INST:
                    raise SctError(f"instrucao desconhecida 0x{self._be(pos):08x} em {sec.name}+0x{pos - sec.start:x}")
            ipos = pos
            if w == I_NO_REFRESH:
                pos += 4
                w = self._rd(pos, little)
                if w > MAX_INST:
                    raise SctError(f"instrucao desconhecida apos prefixo 13 em {sec.name}+0x{pos - sec.start:x}")
            if w == I_SCHEDULE:
                pos, _ = self._decode_inst(I_SCHEDULE, pos, little, sec)
                w = self._rd(pos, little)
                if w > MAX_INST:
                    raise SctError(f"instrucao desconhecida apos agendamento em {sec.name}+0x{pos - sec.start:x}")
            inst_id = w
            pos, links = self._decode_inst(inst_id, pos, little, sec)

            if inst_id == I_SWITCH:
                # entradas com deslocamento zero sao sobras: a tabela termina antes delas
                good = [l for l in links]
                for k, l in enumerate(links):
                    if l.target == l.origin:
                        good = links[:k]
                        pos = links[k].origin - 4
                        break
                links = good
                if links:
                    first_case = min(l.target for l in links)
                    if first_case > pos:
                        sec.unknown.append((pos, first_case))
                    elif first_case < pos and first_case > ipos:
                        raise SctError(f"switch incompleto em {sec.name}+0x{ipos - sec.start:x}")

            if pos > end:
                raise SctError(f"instrucao {inst_id} ultrapassa o fim de {sec.name}")
            done[ipos] = pos
            sec.insts.append((ipos, pos, inst_id))
            for l in links:
                self.links.append(l)
                if l.kind in ("jump", "switch", "call"):
                    pending.append(l.target)
            if inst_id == I_RETURN or inst_id == I_JUMP:
                return
            if inst_id == I_SWITCH and links:
                return

    def _string_layout(self, sec: Section) -> bool:
        """Reconhece uma secao de texto: rotulo (9 + parametro) seguido de bytes que nao sao instrucao."""
        b = self.body
        if sec.end - sec.start < 8 or self._be(sec.start) != I_LABEL:
            return False
        try:
            p, _ = self._skip_scpt(sec.start + 4, False)
        except SctError:
            return False
        if p >= sec.end:
            return False
        if p + 4 <= sec.end and self._be(p) <= MAX_INST:
            return False
        nul = b.find(b"\0", p, sec.end)
        if nul < 0:
            nul = sec.end
        padded = min(sec.end, (nul + 4) & ~3)
        sec.kind = "string"
        sec.text_start = p
        sec.text_end = nul
        sec.padded_end = padded
        return True

    def _analyse(self):
        body = self.body
        code_secs = []
        for sec in self.sections:
            if sec.end == sec.start:
                continue
            if not self._string_layout(sec):
                code_secs.append(sec)

        starts = [s.start for s in self.sections]
        for sec in code_secs:
            done: Dict[int, int] = {}
            pending: List[int] = [sec.start]
            sec._done = done          # type: ignore[attr-defined]
            sec._pending = pending    # type: ignore[attr-defined]

        by_start = {s.start: s for s in self.sections}

        def owner(pos: int) -> Optional[Section]:
            k = bisect_right(starts, pos) - 1
            # secoes vazias dividem o mesmo inicio; pega a ultima nao vazia que contem pos
            while k >= 0:
                s = self.sections[k]
                if s.start <= pos < s.end:
                    return s
                k -= 1
            return None

        # percorre por alcance: cada inicio de secao e cada destino de salto e' um ponto de entrada
        work = [(s, s.start) for s in code_secs]
        guard = 0
        while work:
            sec, pos = work.pop()
            guard += 1
            if guard > 2_000_000:
                raise SctError("percurso nao terminou")
            pending: List[int] = []
            try:
                self._walk(sec, pos, sec.end, sec._done, pending)  # type: ignore[attr-defined]
            except SctError as exc:
                sec.warnings.append(str(exc))
                self.problems.append(f"{sec.name}: {exc}")
            for tgt in pending:
                tsec = owner(tgt)
                if tsec is None:
                    self.problems.append(f"{sec.name}: salto para fora do arquivo (0x{tgt:x})")
                    continue
                if tsec.kind == "string":
                    continue
                if tgt not in tsec._done:  # type: ignore[attr-defined]
                    work.append((tsec, tgt))

        # trechos de codigo nao percorridos
        for sec in code_secs:
            sec.insts.sort()
            cur = sec.start
            gaps = []
            for a, b_, _ in sec.insts:
                if a > cur:
                    gaps.append((cur, a))
                cur = max(cur, b_)
            if cur < sec.end:
                gaps.append((cur, sec.end))
            sec.unknown = self._dead_code(sec, gaps, sec.index == len(self.sections) - 1)
            del sec._done, sec._pending  # type: ignore[attr-defined]

        # rodape: comeca depois da ultima instrucao percorrida da ultima secao
        if self.sections:
            last = self.sections[-1]
            if last.kind == "string":
                self.footer_start = last.padded_end
            elif last.insts:
                self.footer_start = max(b_ for _, b_, _ in last.insts)
            else:
                self.footer_start = last.start
        self._scan_footer()

    def _dead_code(self, sec: Section, gaps, is_last: bool):
        """Depois de um salto ou retorno costuma sobrar codigo que nunca e' executado (muitas
        vezes um salto em little-endian, heranca do Dreamcast). Quando o trecho inteiro pode
        ser lido como instrucoes validas ele e' registrado mesmo assim, para que continue
        apontando para o lugar certo quando os textos mudarem de tamanho. Trechos que nao
        fecham como codigo (tabelas de dados) ficam intocados."""
        left = []
        n = len(self.body)
        for a, b in gaps:
            if is_last and b == sec.end:
                left.append((a, b))      # fim da ultima secao: e' o rodape
                continue
            n_links = len(self.links)
            n_insts = len(sec.insts)
            done: Dict[int, int] = {}
            ok = True
            pos = a
            try:
                while pos < b:
                    before = len(sec.insts)
                    self._walk(sec, pos, b, done, [])
                    if len(sec.insts) == before:
                        ok = False
                        break
                    pos = max(e for _, e, _ in sec.insts[before:])
                if ok:
                    for l in self.links[n_links:]:
                        if not (0 <= l.target < n) or l.target % 4:
                            ok = False
                            break
            except (SctError, struct.error, KeyError):
                ok = False
            if not ok or pos != b:
                del self.links[n_links:]
                del sec.insts[n_insts:]
                left.append((a, b))
        sec.insts.sort()
        return left

    def _scan_footer(self):
        body = self.body
        refs: Dict[int, int] = {}
        for l in self.links:
            if l.kind in ("footer", "string") and l.target >= self.footer_start:
                refs[l.target] = refs.get(l.target, 0) + 1
        pos = self.footer_start
        n = len(body)
        # so' confia no que e' apontado pelo codigo; o resto do rodape fica como bytes soltos
        for tgt in sorted(refs):
            if tgt >= n:
                self.problems.append(f"link de rodape alem do fim do arquivo (0x{tgt:x})")
                continue
            nul = body.find(b"\0", tgt)
            if nul < 0:
                nul = n
            txt = body[tgt:nul]
            fs = FooterString(tgt, nul, refs[tgt], (b"\\e" in txt or b"\\c" in txt))
            self.footer.append(fs)

    # ------------------------------------------------------------------ consulta
    def string_sections(self) -> List[Section]:
        return [s for s in self.sections if s.kind == "string"]

    def text_bytes(self, sec: Section) -> bytes:
        return self.body[sec.text_start:sec.text_end]

    def footer_bytes(self, fs: FooterString) -> bytes:
        return self.body[fs.start:fs.end]

    # ---------------------------------------------------------------- reconstrucao
    def rebuild(self, new_texts: Optional[Dict[int, bytes]] = None,
                new_footer: Optional[Dict[int, bytes]] = None, compress: Optional[bool] = None) -> bytes:
        """Gera o arquivo com os textos trocados.

        new_texts: indice da secao -> bytes do texto (sem NUL).
        new_footer: posicao original do texto de rodape -> bytes (sem NUL).
        """
        new_texts = new_texts or {}
        new_footer = new_footer or {}
        body = self.body
        repl: List[Tuple[int, int, bytes]] = []
        for sec in self.sections:
            if sec.kind != "string" or sec.index not in new_texts:
                continue
            txt = bytes(new_texts[sec.index])
            if b"\0" in txt:
                raise SctError(f"texto de {sec.name} contem byte NUL")
            if txt == body[sec.text_start:sec.text_end]:
                continue
            padded = txt + b"\0" * (4 - len(txt) % 4)
            repl.append((sec.text_start, sec.padded_end, padded))
        fmap = {f.start: f for f in self.footer}
        for start, txt in new_footer.items():
            fs = fmap.get(start)
            if fs is None:
                raise SctError(f"texto de rodape desconhecido em 0x{start:x}")
            txt = bytes(txt)
            if b"\0" in txt:
                raise SctError("texto de rodape contem byte NUL")
            if txt != body[fs.start:fs.end]:
                repl.append((fs.start, fs.end, txt))
        repl.sort()
        for (a1, b1, _), (a2, b2, _) in zip(repl, repl[1:]):
            if a2 < b1:
                raise SctError("trechos de texto sobrepostos")

        out = bytearray()
        bp_pos: List[int] = [0]
        bp_shift: List[int] = [0]
        cur = 0
        shift = 0
        for a, b_, data in repl:
            out += body[cur:a]
            out += data
            cur = b_
            shift += len(data) - (b_ - a)
            bp_pos.append(b_)
            bp_shift.append(shift)
        out += body[cur:]

        def remap(p: int) -> int:
            return p + bp_shift[bisect_right(bp_pos, p) - 1]

        if repl:
            for l in self.links:
                no, nt = remap(l.origin), remap(l.target)
                old = l.target - l.origin
                new = nt - no
                if new != old:
                    cur_raw = struct.unpack_from("<I" if l.little else ">I", out, no)[0]
                    keep = cur_raw & 0x3 if l.inst == I_JUMP else 0
                    struct.pack_into("<I" if l.little else ">I", out, no, (new & 0xFFFFFFFF) | keep)

        head = bytearray(self.header)
        head += struct.pack(">I", len(self.sections))
        for sec in self.sections:
            head += struct.pack(">I", remap(sec.start) if repl else sec.start)
            head += sec.raw_name
        result = bytes(head) + bytes(out)
        if compress is None:
            compress = self.was_compressed
        return aklz.compress(result) if compress else result


def _link_kind(param_type: str) -> str:
    if "footer" in param_type:
        return "footer"
    if "string" in param_type:
        return "string"
    if "subscript" in param_type:
        return "call"
    return "jump"


def load(path: str) -> SctFile:
    with open(path, "rb") as fh:
        return SctFile(fh.read(), os.path.basename(path))
