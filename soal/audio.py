"""Audio do jogo: DSP ADPCM da Nintendo (fluxos _l/_r.dsp) e bancos MusyX (.info + .samp).

Os fluxos sao arquivos .dsp com o cabecalho padrao de 0x60 bytes, um por canal. Os bancos sao
pares .info/.samp: o .info traz a tabela de amostras do MusyX (sdir, entradas de 0x20 bytes,
terminada em FFFFFFFF, com os coeficientes ADPCM depois dela) e o .samp traz as amostras.

Decodifica para PCM 16 bits e codifica de volta (para a dublagem), sem bibliotecas de fora.
"""
import array
import math
import struct
import wave
from typing import List, Optional, Tuple

FRAME_SAMPLES = 14
FRAME_BYTES = 8

_NIB = [n - 16 if n >= 8 else n for n in range(16)]


# ---------------------------------------------------------------- DSP ADPCM
def decode(data: bytes, nsamples: int, coefs: List[int], hist1: int = 0, hist2: int = 0) -> array.array:
    """Decodifica nsamples amostras de DSP ADPCM. coefs: 16 inteiros (8 pares)."""
    out = array.array("h", bytes(2 * nsamples))
    pairs = [(coefs[2 * i], coefs[2 * i + 1]) for i in range(8)]
    nib = _NIB
    n = 0
    pos = 0
    end = len(data)
    while n < nsamples and pos < end:
        ps = data[pos]
        c1, c2 = pairs[(ps >> 4) & 7]
        sc = (1 << (ps & 15)) << 11
        for b in data[pos + 1:pos + 8]:
            for s in (nib[b >> 4], nib[b & 15]):
                v = (s * sc + 1024 + c1 * hist1 + c2 * hist2) >> 11
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                hist2 = hist1
                hist1 = v
                if n < nsamples:
                    out[n] = v
                n += 1
        pos += 8
    return out


def nibbles_for(nsamples: int) -> int:
    frames, rest = divmod(nsamples, FRAME_SAMPLES)
    return frames * 16 + (rest + 2 if rest else 0)


def bytes_for(nsamples: int) -> int:
    return (nsamples + FRAME_SAMPLES - 1) // FRAME_SAMPLES * FRAME_BYTES


def _solve2(r11, r12, r22, b1, b2):
    det = r11 * r22 - r12 * r12
    if abs(det) < 1e-9:
        return None
    return ((b1 * r22 - b2 * r12) / det, (r11 * b2 - r12 * b1) / det)


def compute_coefs(pcm) -> List[int]:
    """Escolhe 8 pares de coeficientes de predicao (formato 5.11) para o sinal. Calcula o melhor
    preditor de 2a ordem de cada quadro e agrupa os quadros parecidos (k-means ponderado pela
    energia do erro). Sempre inclui o preditor nulo e os classicos de 1a e 2a ordem."""
    n = len(pcm)
    cands = []
    for f in range(0, n, FRAME_SAMPLES):
        r11 = r12 = r22 = b1 = b2 = 0.0
        e = 0.0
        for i in range(max(f, 2), min(f + FRAME_SAMPLES, n)):
            x, y1, y2 = pcm[i], pcm[i - 1], pcm[i - 2]
            r11 += y1 * y1
            r12 += y1 * y2
            r22 += y2 * y2
            b1 += x * y1
            b2 += x * y2
            e += x * x
        if e < 1.0:
            continue
        sol = _solve2(r11, r12, r22, b1, b2)
        if sol is None:
            continue
        a1, a2 = sol
        # quadro estavel e dentro do alcance do formato 5.11
        if abs(a2) >= 1.0 or abs(a1) >= 2.0 or abs(a1) >= 1 - a2 + 1:
            continue
        cands.append((a1, a2, math.log1p(e)))
    fixed = [(0.0, 0.0), (1.0, 0.0), (1.9, -0.92)]
    k = 8 - len(fixed)
    cents: List[Tuple[float, float]] = []
    if cands:
        cands.sort(key=lambda c: -c[2])
        step = max(1, len(cands) // k)
        cents = [(c[0], c[1]) for c in cands[::step][:k]]
        for _ in range(12):
            acc = [[0.0, 0.0, 0.0] for _ in cents]
            for a1, a2, w in cands:
                j = min(range(len(cents)), key=lambda q: (cents[q][0] - a1) ** 2 + (cents[q][1] - a2) ** 2)
                acc[j][0] += a1 * w
                acc[j][1] += a2 * w
                acc[j][2] += w
            cents = [(a[0] / a[2], a[1] / a[2]) if a[2] else cents[i] for i, a in enumerate(acc)]
    while len(cents) < k:
        cents.append((1.6, -0.7))
    out = []
    for a1, a2 in fixed + cents:
        out += [max(-32768, min(32767, int(round(a1 * 2048)))), max(-32768, min(32767, int(round(a2 * 2048))))]
    return out


def encode(pcm, coefs: List[int]) -> Tuple[bytes, int]:
    """Codifica PCM 16 bits em DSP ADPCM com os coeficientes dados. Devolve (dados, ps inicial)."""
    pairs = [(coefs[2 * i], coefs[2 * i + 1]) for i in range(8)]
    n = len(pcm)
    out = bytearray()
    h1 = h2 = 0
    first_ps = None
    for f in range(0, n, FRAME_SAMPLES):
        fr = list(pcm[f:f + FRAME_SAMPLES])
        fr += [0] * (FRAME_SAMPLES - len(fr))
        best = None
        for ci, (c1, c2) in enumerate(pairs):
            # erro maximo com o historico real, para estimar a escala
            p1, p2 = h1, h2
            mx = 0
            for x in fr:
                pred = (c1 * p1 + c2 * p2 + 1024) >> 11
                d = x - pred
                if abs(d) > mx:
                    mx = abs(d)
                p2, p1 = p1, x
            sc = 0
            while sc < 12 and (7 << sc) < mx:
                sc += 1
            for s in ((sc - 1, sc, sc + 1) if sc else (0, 1)):
                if s < 0 or s > 12:
                    continue
                step = (1 << s) << 11
                p1, p2 = h1, h2
                err = 0
                nibs = []
                for x in fr:
                    base = c1 * p1 + c2 * p2 + 1024
                    q = ((x << 11) - base + (step >> 1)) // step if step else 0
                    if q > 7:
                        q = 7
                    elif q < -8:
                        q = -8
                    v = (q * step + base) >> 11
                    if v > 32767:
                        v = 32767
                    elif v < -32768:
                        v = -32768
                    e = x - v
                    err += e * e
                    if best is not None and err >= best[0]:
                        break
                    nibs.append(q)
                    p2, p1 = p1, v
                else:
                    best = (err, ci, s, nibs, p1, p2)
        _, ci, s, nibs, h1, h2 = best
        ps = (ci << 4) | s
        if first_ps is None:
            first_ps = ps
        out.append(ps)
        for i in range(0, 14, 2):
            out.append(((nibs[i] & 15) << 4) | (nibs[i + 1] & 15))
    return bytes(out), (first_ps or 0)


# ---------------------------------------------------------------- arquivos .dsp
class DspStream:
    """Um canal de fluxo .dsp (cabecalho padrao da Nintendo, 0x60 bytes)."""

    def __init__(self, data: bytes):
        if len(data) < 0x60:
            raise ValueError("arquivo .dsp curto demais")
        (self.nsamples, self.nnibbles, self.rate, self.loop, self.fmt,
         self.loop_start, self.loop_end, self.cur) = struct.unpack(">IIIHHIII", data[:0x1C])
        self.coefs = list(struct.unpack(">16h", data[0x1C:0x3C]))
        self.gain, self.ps, self.hist1, self.hist2 = struct.unpack(">HHhh", data[0x3C:0x44])
        self.header = bytes(data[:0x60])
        self.body = bytes(data[0x60:])
        if self.fmt != 0 or not (1000 <= self.rate <= 96000):
            raise ValueError("formato .dsp desconhecido")

    def pcm(self) -> array.array:
        return decode(self.body, self.nsamples, self.coefs, self.hist1, self.hist2)

    @staticmethod
    def build(pcm, rate: int, template: Optional[bytes] = None) -> bytes:
        coefs = compute_coefs(pcm)
        body, ps = encode(pcm, coefs)
        n = len(pcm)
        head = bytearray(template[:0x60] if template else bytes(0x60))
        struct.pack_into(">IIIHHIII", head, 0, n, nibbles_for(n), rate, 0, 0, 2, nibbles_for(n), 2)
        struct.pack_into(">16h", head, 0x1C, *coefs)
        struct.pack_into(">HHhh", head, 0x3C, 0, ps, 0, 0)
        struct.pack_into(">Hhh", head, 0x44, 0, 0, 0)
        return bytes(head) + body


class Encoded:
    """Um som ja' codificado em DSP ADPCM (para usar em varios bancos sem codificar de novo)."""
    __slots__ = ("body", "coefs", "ps", "n", "rate")

    @classmethod
    def of(cls, pcm, rate: int) -> "Encoded":
        e = cls()
        e.coefs = compute_coefs(pcm)
        e.body, e.ps = encode(pcm, e.coefs)
        e.n, e.rate = len(pcm), rate
        return e


# ---------------------------------------------------------------- bancos MusyX
class Sample:
    __slots__ = ("id", "index", "off", "rate", "pitch", "nsamples", "fmt", "loop_start", "loop_len",
                 "adpcm", "coefs", "ps", "hist1", "hist2", "entry_at")


class Bank:
    """Par .info/.samp. So' a tabela de amostras e' lida; o resto do .info (macros e mapas de
    som do MusyX) fica como esta."""

    def __init__(self, info: bytes, samp: bytes):
        self.info = bytearray(info)
        self.samp = bytes(samp)
        self.sdir = self._find_sdir()
        if self.sdir is None:
            raise ValueError("tabela de amostras não encontrada")
        self.samples: List[Sample] = []
        o = self.sdir
        while self.info[o:o + 4] != b"\xff\xff\xff\xff":
            s = Sample()
            (s.id, _, s.off, _, s.pitch, _, s.rate, ns, s.loop_start, s.loop_len,
             s.adpcm) = struct.unpack(">HHIIBBHIIII", self.info[o:o + 0x20])
            s.fmt, s.nsamples = ns >> 24, ns & 0xFFFFFF
            s.entry_at = o
            s.index = len(self.samples)
            a = self.sdir + s.adpcm
            if s.fmt == 0:
                _, s.ps, _, s.hist2, s.hist1 = struct.unpack(">HBBhh", self.info[a:a + 8])
                s.coefs = list(struct.unpack(">16h", self.info[a + 8:a + 0x28]))
            self.samples.append(s)
            o += 0x20

    def _find_sdir(self) -> Optional[int]:
        d = self.info
        n = len(d)
        for st in range(0x40, n - 0x24, 4):
            o = st
            count = 0
            last = -1
            while o + 0x20 <= n:
                if d[o:o + 4] == b"\xff\xff\xff\xff":
                    break
                _, pad, off, _, pitch, pad2, rate, ns, _, _, ao = struct.unpack(">HHIIBBHIIII", d[o:o + 0x20])
                if pad or pad2 or pitch > 127 or not rate or off < last or not (ns & 0xFFFFFF):
                    count = -1
                    break
                if st + ao + 0x28 > n or d[st + ao:st + ao + 2] != b"\x00\x08":
                    count = -1
                    break
                last = off
                count += 1
                o += 0x20
            if count > 0 and d[o:o + 4] == b"\xff\xff\xff\xff":
                return st
        return None

    def data_of(self, s: Sample) -> bytes:
        return self.samp[s.off:s.off + bytes_for(s.nsamples)]

    def pcm(self, s: Sample) -> Optional[array.array]:
        if s.fmt != 0:
            return None
        return decode(self.data_of(s), s.nsamples, s.coefs, s.hist1, s.hist2)

    def rebuild(self, new: dict) -> Tuple[bytes, bytes]:
        """new: indice da amostra -> (pcm, taxa) ou Encoded (ja' codificada). Monta o .samp de
        novo (amostras alinhadas a 32 bytes) e atualiza a tabela. Amostras trocadas perdem o
        loop."""
        info = bytearray(self.info)
        out = bytearray()
        order = sorted(self.samples, key=lambda s: s.off)
        placed = {}
        for s in order:
            if s.off in placed and s.index not in new:
                continue
            if s.index in new:
                e = new[s.index]
                if not isinstance(e, Encoded):
                    e = Encoded.of(*e)
                body = e.body
                meta = (e.n, e.rate, e.coefs, e.ps)
            else:
                body = self.samp[s.off:s.off + bytes_for(s.nsamples)]
                meta = None
            out += bytes((-len(out)) % 32)
            pos = len(out)
            out += body
            if meta is None:
                placed[s.off] = pos
            e = s.entry_at
            struct.pack_into(">I", info, e + 4, pos)
            if meta:
                n, rate, coefs, ps = meta
                struct.pack_into(">H", info, e + 0xE, rate)
                struct.pack_into(">IIII", info, e + 0x10, (s.fmt << 24) | n, 0, 0, s.adpcm)
                a = self.sdir + s.adpcm
                struct.pack_into(">HBBhh", info, a, 8, ps, 0, 0, 0)
                struct.pack_into(">16h", info, a + 8, *coefs)
        # amostras que dividiam o mesmo lugar no .samp continuam juntas
        for s in self.samples:
            if s.index not in new and s.off in placed:
                struct.pack_into(">I", info, s.entry_at + 4, placed[s.off])
        return bytes(info), bytes(out)


# ---------------------------------------------------------------- WAV
def write_wav(path: str, rate: int, channels: List[array.array]):
    n = max(len(c) for c in channels)
    if len(channels) == 1:
        frames = channels[0]
    else:
        frames = array.array("h", bytes(2 * n * len(channels)))
        for ci, c in enumerate(channels):
            frames[ci:ci + len(c) * len(channels):len(channels)] = c
    data = array.array("h", frames)
    if struct.pack("=h", 1) == b"\x00\x01":
        data.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def read_wav(path: str) -> Tuple[int, List[array.array]]:
    """Le WAV PCM (8, 16, 24 ou 32 bits). Devolve (taxa, canais em 16 bits)."""
    try:
        w = wave.open(path, "rb")
    except wave.Error as exc:
        raise ValueError(f"WAV não suportado ({exc}). Salve como WAV PCM 16 bits.")
    with w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        a = array.array("h", raw)
        if struct.pack("=h", 1) == b"\x00\x01":
            a.byteswap()
    elif width == 1:
        a = array.array("h", ((b - 128) << 8 for b in raw))
    elif width == 3:
        a = array.array("h", (int.from_bytes(raw[i + 1:i + 3], "little", signed=True) for i in range(0, len(raw), 3)))
    elif width == 4:
        a = array.array("h", (int.from_bytes(raw[i + 2:i + 4], "little", signed=True) for i in range(0, len(raw), 4)))
    else:
        raise ValueError("WAV com formato desconhecido")
    return rate, [a[c::ch] for c in range(ch)]


def mix_mono(chs: List[array.array]) -> array.array:
    if len(chs) == 1:
        return chs[0]
    n = min(len(c) for c in chs)
    k = len(chs)
    return array.array("h", (sum(c[i] for c in chs) // k for i in range(n)))


def resample(pcm, src: int, dst: int) -> array.array:
    """Muda a taxa de amostragem (filtro passa-baixa simples + interpolacao linear)."""
    if src == dst or not pcm:
        return array.array("h", pcm)
    x = list(pcm)
    if dst < src:
        # media movel ~ corta acima da nova frequencia de Nyquist
        w = max(1, int(round(src / dst)))
        if w > 1:
            acc = 0
            y = []
            q = []
            for v in x:
                q.append(v)
                acc += v
                if len(q) > w:
                    acc -= q.pop(0)
                y.append(acc / len(q))
            x = y
    n = int(len(x) * dst / src)
    out = array.array("h", bytes(2 * n))
    r = src / dst
    last = len(x) - 1
    for i in range(n):
        p = i * r
        j = int(p)
        t = p - j
        v = x[j] if j >= last else x[j] + (x[j + 1] - x[j]) * t
        out[i] = max(-32768, min(32767, int(round(v))))
    return out
