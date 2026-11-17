"""Modelos 3D do jogo (personagens, objetos, construcoes).

Os arquivos .mld guardam os modelos no formato "Ninja chunk" da Sega (blocos NJCM), o
mesmo do Dreamcast, aqui em big-endian. Cada modelo e' uma arvore de pecas (nos): cada no
tem posicao, rotacao e escala em relacao ao pai, uma lista de vertices e uma lista de
tiras de triangulos com material e textura. Os vertices de um no vao para uma tabela
comum, ja' na posicao final, e as tiras (do mesmo no ou de um no posterior) apontam para
essa tabela: e' assim que o jogo junta as pecas do corpo de um personagem.

Este modulo le o arquivo e devolve, para cada modelo, os nos (o esqueleto) e a malha em
triangulos, com normais, UV, cores e o peso de cada vertice em cada no. A exportacao para
arquivos (glTF, OBJ) fica em exportar.py.

Estrutura do .mld (depois de descomprimir o AKLZ):
    cabecalho  quantidade de entradas, posicao da tabela, dos dados, dos blocos e das texturas
    entradas   0x68 bytes: numero, codigo, 7 ponteiros, nome, posicao/rotacao/escala
    blocos     [posicao do NJCM, tamanho, posicao do NJTL, 0] + NJTL (nomes das texturas) + NJCM
    texturas   quantidade, depois (nome de 0x28 bytes + tamanho) e os GCIX/GVRT em sequencia
"""

from __future__ import annotations

import math
import struct
from typing import Dict, List, Optional, Tuple

from . import aklz

ENTRY = 0x68
BAMS = 2.0 * math.pi / 65536.0

# sinalizadores do no
F_UNIT_POS, F_UNIT_ANG, F_UNIT_SCL, F_HIDE, F_BREAK, F_ZXY, F_SKIP = 1, 2, 4, 8, 16, 32, 64
# sinalizadores da tira
S_IGNORE_LIGHT, S_USE_ALPHA, S_DOUBLE, S_FLAT, S_ENV = 1, 8, 16, 32, 64

# vertice: (tem "1" depois do xyz, tem normal, extra de 32 bits: "", "cor", "peso", "x")
VERTEX = {
    32: (True, False, ""), 33: (True, True, ""),
    34: (False, False, ""), 35: (False, False, "cor"), 36: (False, False, "x"), 37: (False, False, "peso"),
    38: (False, False, "x"), 39: (False, False, "x"), 40: (False, False, "x"),
    41: (False, True, ""), 42: (False, True, "cor"), 43: (False, True, "x"), 44: (False, True, "peso"),
    45: (False, True, "x"), 46: (False, True, "x"), 47: (False, True, "x"),
}
# tira: (UV: 0 nao tem, 255 ou 1023 e' o divisor; normal; cor; segundo UV)
STRIP = {
    64: (0, False, False, False), 65: (255, False, False, False), 66: (1023, False, False, False),
    67: (0, True, False, False), 68: (255, True, False, False), 69: (1023, True, False, False),
    70: (0, False, True, False), 71: (255, False, True, False), 72: (1023, False, True, False),
    73: (0, False, False, False), 74: (255, False, False, True), 75: (1023, False, False, True),
}


class ModelError(Exception):
    pass


# ------------------------------------------------------------------ matrizes 4x4 (linha a linha)
IDENT = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def mat_mul(a, b):
    return tuple(a[r * 4] * b[c] + a[r * 4 + 1] * b[4 + c] + a[r * 4 + 2] * b[8 + c] + a[r * 4 + 3] * b[12 + c]
                 for r in range(4) for c in range(4))


def mat_trs(pos, ang, scl, zxy=False):
    """Matriz local do no: translacao, rotacao (Z·Y·X, ou Y·X·Z com zxy) e escala."""
    sx, cx = math.sin(ang[0]), math.cos(ang[0])
    sy, cy = math.sin(ang[1]), math.cos(ang[1])
    sz, cz = math.sin(ang[2]), math.cos(ang[2])
    rx = (1, 0, 0, 0, 0, cx, -sx, 0, 0, sx, cx, 0, 0, 0, 0, 1)
    ry = (cy, 0, sy, 0, 0, 1, 0, 0, -sy, 0, cy, 0, 0, 0, 0, 1)
    rz = (cz, -sz, 0, 0, sz, cz, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    r = mat_mul(mat_mul(ry, rx), rz) if zxy else mat_mul(mat_mul(rz, ry), rx)
    m = list(r)
    for c in range(3):
        for rr in range(3):
            m[rr * 4 + c] *= scl[c]
    m[3], m[7], m[11] = pos
    return tuple(m), r


def mat_point(m, p):
    x, y, z = p
    return (m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def mat_dir(m, p):
    x, y, z = p
    return (m[0] * x + m[1] * y + m[2] * z, m[4] * x + m[5] * y + m[6] * z, m[8] * x + m[9] * y + m[10] * z)


def mat_inv(m):
    """Inversa de uma matriz afim (ultima linha 0 0 0 1)."""
    a, b, c, d, e, f, g, h, i = m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        return IDENT
    k = 1.0 / det
    r = ((e * i - f * h) * k, (c * h - b * i) * k, (b * f - c * e) * k,
         (f * g - d * i) * k, (a * i - c * g) * k, (c * d - a * f) * k,
         (d * h - e * g) * k, (b * g - a * h) * k, (a * e - b * d) * k)
    tx, ty, tz = m[3], m[7], m[11]
    return (r[0], r[1], r[2], -(r[0] * tx + r[1] * ty + r[2] * tz),
            r[3], r[4], r[5], -(r[3] * tx + r[4] * ty + r[5] * tz),
            r[6], r[7], r[8], -(r[6] * tx + r[7] * ty + r[8] * tz), 0.0, 0.0, 0.0, 1.0)


def _bgra(d: bytes, p: int):
    """Cor de material/tira: bytes B, G, R, A (como no Dreamcast)."""
    b, g, r, a = d[p], d[p + 1], d[p + 2], d[p + 3]
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else (0.0, 1.0, 0.0)


# ------------------------------------------------------------------ estruturas
class Node:
    __slots__ = ("idx", "parent", "flags", "pos", "ang", "scl", "local", "rot", "world", "off", "has_model")

    def __init__(self, idx, parent, flags, pos, ang, scl, off):
        self.idx, self.parent, self.flags, self.pos, self.ang, self.scl, self.off = idx, parent, flags, pos, ang, scl, off
        self.local, self.rot = mat_trs(pos, ang, scl, bool(flags & F_ZXY))
        self.world = IDENT
        self.has_model = False


class Material:
    __slots__ = ("tex", "diffuse", "specular", "alpha", "double", "flat", "env", "clamp_u", "clamp_v",
                 "flip_u", "flip_v", "unlit")

    def key(self):
        return tuple(getattr(self, k) for k in self.__slots__)


class Group:
    """Triangulos de um mesmo material. Cada vertice: (posicao, normal, uv, cor, pesos)."""

    def __init__(self, mat: Material):
        self.mat = mat
        self.verts: List[tuple] = []
        self.tris: List[Tuple[int, int, int]] = []
        self._seen: Dict[tuple, int] = {}

    def add(self, key, v) -> int:
        i = self._seen.get(key)
        if i is None:
            i = self._seen[key] = len(self.verts)
            self.verts.append(v)
        return i


class Model:
    def __init__(self, name: str, tex_names: List[str]):
        self.name = name
        self.tex_names = tex_names
        self.nodes: List[Node] = []
        self.groups: List[Group] = []
        self.problems: List[str] = []
        self.has_weights = False

    @property
    def tri_count(self) -> int:
        return sum(len(g.tris) for g in self.groups)

    @property
    def vert_count(self) -> int:
        return sum(len(g.verts) for g in self.groups)

    def bounds(self):
        lo, hi = [1e30] * 3, [-1e30] * 3
        for g in self.groups:
            for v in g.verts:
                for k in range(3):
                    lo[k] = min(lo[k], v[0][k])
                    hi[k] = max(hi[k], v[0][k])
        return (tuple(lo), tuple(hi)) if self.groups and lo[0] < 1e30 else ((0.0,) * 3, (0.0,) * 3)


# ------------------------------------------------------------------ leitura do NJCM
class _Reader:
    """Le um bloco NJCM (a partir do conteudo, depois dos 8 bytes do cabecalho)."""

    MAX_NODES = 4096

    def __init__(self, d: bytes, base: int, size: int, model: Model):
        self.d, self.base, self.end = d, base, min(len(d), base + size)
        self.m = model
        self.buf: Dict[int, list] = {}       # tabela comum de vertices
        self.serial = 0
        self.cache: Dict[int, int] = {}      # listas de poligonos guardadas (chunk 4 / 5)
        self.groups: Dict[tuple, Group] = {}
        self._seen_nodes = set()

    def u16(self, o):
        return struct.unpack_from(">H", self.d, o)[0]

    def u32(self, o):
        return struct.unpack_from(">I", self.d, o)[0]

    def ptr(self, o):
        """Ponteiro relativo ao comeco do bloco; 0 = nenhum."""
        v = self.u32(o)
        if not v:
            return 0
        p = self.base + v
        if p + 4 > self.end:
            raise ModelError("ponteiro fora do bloco")
        return p

    # -- arvore
    def walk(self, off: int, parent: Optional[Node]):
        while off:
            if off in self._seen_nodes or len(self.m.nodes) >= self.MAX_NODES:
                self.m.problems.append("árvore de peças com laço: parei")
                return
            self._seen_nodes.add(off)
            if off + 0x34 > self.end:
                raise ModelError("nó fora do bloco")
            flags = self.u32(off)
            f = struct.unpack_from(">3f3i3f", self.d, off + 8)
            pos = (0.0, 0.0, 0.0) if flags & F_UNIT_POS else f[0:3]
            ang = (0.0, 0.0, 0.0) if flags & F_UNIT_ANG else tuple((a & 0xFFFF) * BAMS for a in f[3:6])
            scl = (1.0, 1.0, 1.0) if flags & F_UNIT_SCL else f[6:9]
            n = Node(len(self.m.nodes), parent.idx if parent else -1, flags, pos, ang, scl, off - self.base)
            n.world = mat_mul(parent.world, n.local) if parent else n.local
            self.m.nodes.append(n)
            mp = self.ptr(off + 4)
            if mp and not flags & F_HIDE:
                n.has_model = True
                try:
                    self.model(mp, n)
                except (struct.error, IndexError, ModelError) as e:
                    self.m.problems.append(f"peça {n.idx}: {e or 'dados cortados'}")
            child = self.ptr(off + 0x2C)
            if child and not flags & F_BREAK:
                self.walk(child, n)
            off = self.ptr(off + 0x30)

    def model(self, off: int, node: Node):
        vl, pl = self.ptr(off), self.ptr(off + 4)
        if vl:
            self.vlist(vl, node)
        if pl:
            self.plist(pl, node)

    # -- vertices
    def vlist(self, o: int, node: Node):
        d, w = self.d, node.world
        while True:
            if o + 4 > self.end:
                raise ModelError("lista de vértices cortada")
            head = self.u32(o)
            typ, flags, size = head & 0xFF, (head >> 8) & 0xFF, head >> 16
            if typ == 0xFF:
                return
            if typ == 0:
                o += 4
                continue
            spec = VERTEX.get(typ)
            if spec is None:
                raise ModelError(f"tipo de vértice desconhecido ({typ})")
            sh, has_n, extra = spec
            h2 = self.u32(o + 4)
            first, count = h2 & 0xFFFF, h2 >> 16
            step = (4 if sh else 3) * (2 if has_n else 1) + (1 if extra else 0)
            p = o + 8
            if p + count * step * 4 > self.end:
                raise ModelError("vértices cortados")
            fmt = ">" + "f" * ((4 if sh else 3) * (2 if has_n else 1)) + ("I" if extra else "")
            status = flags & 3
            for i in range(count):
                t = struct.unpack_from(fmt, d, p)
                p += step * 4
                pos = mat_point(w, t[0:3])
                nrm = mat_dir(w, t[4:7] if sh else t[3:6]) if has_n else None
                col = None
                if extra == "cor":
                    c = t[-1]
                    col = (((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0, (c >> 24) / 255.0)
                self.serial += 1
                if extra == "peso":
                    idx = first + (t[-1] & 0xFFFF)
                    wt = ((t[-1] >> 16) & 0xFF) / 255.0
                    self.m.has_weights = True
                    cur = self.buf.get(idx)
                    if status == 0 or cur is None:
                        self.buf[idx] = [self.serial, [pos[0] * wt, pos[1] * wt, pos[2] * wt],
                                         [nrm[0] * wt, nrm[1] * wt, nrm[2] * wt] if nrm else None, None,
                                         [(node.idx, wt)]]
                    else:
                        cur[0] = self.serial
                        for k in range(3):
                            cur[1][k] += pos[k] * wt
                            if nrm and cur[2]:
                                cur[2][k] += nrm[k] * wt
                        cur[4].append((node.idx, wt))
                else:
                    self.buf[first + i] = [self.serial, pos, nrm, col, [(node.idx, 1.0)]]
            o += 4 + size * 4

    # -- poligonos
    def plist(self, o: int, node: Node, depth: int = 0):
        d = self.d
        st = self._state(node)
        while True:
            if o + 2 > self.end:
                raise ModelError("lista de polígonos cortada")
            head = self.u16(o)
            typ, flags = head & 0xFF, head >> 8
            if typ == 0xFF:
                return
            if typ == 0:
                o += 2
            elif typ <= 5:                                   # bits
                if typ == 1:
                    st["blend"] = flags
                elif typ == 4:                               # guarda o resto da lista para desenhar depois
                    self.cache[flags] = o + 2
                    return
                elif typ == 5:
                    c = self.cache.get(flags)
                    if c and depth < 8:
                        save = dict(st)
                        self.plist(c, node, depth + 1)
                        self._states[node.idx] = st = save
                o += 2
            elif typ in (8, 9):                              # textura
                v = self.u16(o + 2)
                st["tex"] = v & 0x1FFF
                st["tflags"] = flags
                o += 4
            elif 16 <= typ <= 31:                            # material
                size = self.u16(o + 2)
                p = o + 4
                st["mflags"] = flags
                for bit, key in ((1, "diffuse"), (2, "ambient"), (4, "specular")):
                    if typ & bit:
                        st[key] = _bgra(self.d, p)
                        p += 4
                o += 4 + size * 2
            elif 56 <= typ <= 58:                            # volume (sombra): nao desenha
                o += 4 + self.u16(o + 2) * 2
            elif typ in STRIP:
                size = self.u16(o + 2)
                self.strips(o + 4, typ, flags, st, o + 4 + size * 2)
                o += 4 + size * 2
            elif 32 <= typ <= 55:
                raise ModelError("vértices dentro da lista de polígonos")
            else:
                raise ModelError(f"bloco de polígonos desconhecido ({typ})")

    def _state(self, node: Node) -> dict:
        if not hasattr(self, "_states"):
            self._states = {}
            self._last = {"tex": -1, "tflags": 0, "diffuse": (1.0, 1.0, 1.0, 1.0), "specular": None,
                          "ambient": None, "blend": 0, "mflags": 0}
        # o material vale ate' ser trocado, inclusive de um no para o seguinte
        return self._last

    def strips(self, o: int, typ: int, flags: int, st: dict, end: int):
        uvdiv, has_n, has_c, uv2 = STRIP[typ]
        d = self.d
        h = self.u16(o)
        count, user = h & 0x3FFF, h >> 14
        o += 2
        mat = Material()
        mat.tex = st["tex"]
        mat.diffuse = st["diffuse"]
        mat.specular = st["specular"]
        mat.alpha = bool(flags & S_USE_ALPHA)
        mat.double = bool(flags & S_DOUBLE)
        mat.flat = bool(flags & S_FLAT)
        mat.env = bool(flags & S_ENV)
        mat.unlit = bool(flags & S_IGNORE_LIGHT)
        tf = st["tflags"]
        mat.clamp_u, mat.clamp_v, mat.flip_u, mat.flip_v = bool(tf & 0x20), bool(tf & 0x10), bool(tf & 0x80), bool(tf & 0x40)
        if not uvdiv:
            mat.tex = -1 if not mat.env else mat.tex
        g = self.groups.get(mat.key())
        if g is None:
            g = self.groups[mat.key()] = Group(mat)
            self.m.groups.append(g)
        vsize = 2 + (4 if uvdiv else 0) + (6 if has_n else 0) + (4 if has_c else 0) + (4 if uv2 else 0)
        for _ in range(count):
            if o + 2 > end:
                raise ModelError("tira cortada")
            n = struct.unpack_from(">h", d, o)[0]
            o += 2
            rev = n < 0
            n = abs(n)
            idx = []
            for k in range(n):
                if o + vsize > end + 2:
                    raise ModelError("tira cortada")
                vi = self.u16(o)
                p = o + 2
                uv = None
                if uvdiv:
                    u, v = struct.unpack_from(">hh", d, p)
                    uv = (u / uvdiv, v / uvdiv)
                    p += 4
                nrm = None
                if has_n:
                    nx, ny, nz = struct.unpack_from(">hhh", d, p)
                    p += 6
                col = None
                if has_c:
                    col = _bgra(d, p)
                    p += 4
                if uv2:
                    p += 4
                o = p
                if k >= 2:
                    o += user * 2
                b = self.buf.get(vi)
                if b is None:
                    idx.append(-1)
                    continue
                key = (b[0], uv, col)
                i = g._seen.get(key)
                if i is None:
                    pos = tuple(b[1])
                    bn = _norm(b[2]) if b[2] else None
                    ws = b[4]
                    if len(ws) > 1 or abs(ws[0][1] - 1.0) > 1e-3:
                        tot = sum(w for _, w in ws) or 1.0
                        if abs(tot - 1.0) > 0.02:
                            pos = (pos[0] / tot, pos[1] / tot, pos[2] / tot)
                        ws = tuple((j, w / tot) for j, w in ws)
                    else:
                        ws = ((ws[0][0], 1.0),)
                    i = g.add(key, (pos, bn, uv, col or b[3], ws))
                idx.append(i)
            for k in range(n - 2):
                a, b2, c = idx[k], idx[k + 1], idx[k + 2]
                if a < 0 or b2 < 0 or c < 0 or a == b2 or b2 == c or a == c:
                    continue
                if (k & 1) != rev:
                    a, b2 = b2, a
                g.tris.append((a, b2, c))


def read_njcm(d: bytes, off: int, name: str, tex_names: List[str]) -> Model:
    """off: posicao da etiqueta "NJCM"."""
    if d[off:off + 4] != b"NJCM":
        raise ModelError("não é um modelo NJCM")
    size = struct.unpack_from(">I", d, off + 4)[0]
    m = Model(name, tex_names)
    r = _Reader(d, off + 8, size, m)
    try:
        r.walk(off + 8, None)
    except (struct.error, IndexError, ModelError, RecursionError) as e:
        m.problems.append(str(e) or "dados cortados")
    # sem textura e totalmente transparente: caixas invisiveis (colisao, alvo)
    m.groups = [g for g in m.groups if g.tris and not (g.mat.alpha and g.mat.tex < 0 and g.mat.diffuse[3] < 0.004)]
    return m


def read_njtl(d: bytes, off: int) -> List[str]:
    """Nomes das texturas de um bloco NJTL."""
    if d[off:off + 4] != b"NJTL":
        return []
    size = struct.unpack_from(">I", d, off + 4)[0]
    base = off + 8
    try:
        lst, count = struct.unpack_from(">II", d, base)
        out = []
        for i in range(min(count, 4096)):
            p = struct.unpack_from(">I", d, base + lst + i * 12)[0]
            s = d[base + p:base + p + 64].split(b"\0")[0]
            out.append(s.decode("latin1"))
        return out
    except struct.error:
        return []


# ------------------------------------------------------------------ o arquivo .mld
class ModelRef:
    """Um modelo dentro do arquivo: onde esta' e de que entrada veio."""

    def __init__(self, n, off, njtl, name, entry, obj_id):
        self.n, self.off, self.njtl, self.name, self.entry, self.obj_id = n, off, njtl, name, entry, obj_id


class MldFile:
    def __init__(self, raw: bytes):
        self.data = d = aklz.decompress(raw) if aklz.is_compressed(raw) else bytes(raw)
        self.entries: List[dict] = []
        self.models: List[ModelRef] = []
        self.textures: Dict[str, int] = {}       # nome -> posicao do GVRT
        self.tex_order: List[str] = []
        self._parse()

    def _parse(self):
        d = self.data
        seen = {}
        try:
            n, toff, doff, foff, xoff = struct.unpack_from(">5I", d, 0)
            ok = 0 < n < 4096 and toff in (0x14, 0x18) and toff + n * ENTRY <= len(d) and doff == toff + n * ENTRY
        except struct.error:
            ok = False
        if ok:
            for i in range(n):
                o = toff + i * ENTRY
                num, code = struct.unpack_from(">iI", d, o)
                ps = struct.unpack_from(">7I", d, o + 8)
                name = d[o + 0x24:o + 0x44].split(b"\0")[0].decode("latin1")
                trs = struct.unpack_from(">9f", d, o + 0x44)
                e = {"n": i, "num": num, "code": code, "name": name, "trs": trs, "models": []}
                self.entries.append(e)
                p = ps[3]
                if 0 < p < len(d) - 4:
                    cnt = struct.unpack_from(">I", d, p)[0]
                    if cnt < 1024 and p + 4 + cnt * 4 <= len(d):
                        for b in struct.unpack_from(f">{cnt}I", d, p + 4):
                            if 0 < b < len(d) - 16:
                                self._block(b, e, seen)
            self._textures(xoff)
        # modelos que nenhuma entrada aponta (e arquivos de outro tipo): procura pela etiqueta
        i = 0
        while True:
            i = d.find(b"NJCM", i)
            if i < 0:
                break
            if i not in seen and i + 8 + 0x34 <= len(d):
                size = struct.unpack_from(">I", d, i + 4)[0]
                if 0x34 <= size <= len(d) - i - 8:
                    seen[i] = ref = ModelRef(len(self.models), i, self._njtl_before(i), "", None, -1)
                    self.models.append(ref)
            i += 4
        if not self.textures:
            self._textures_scan()
        self.models.sort(key=lambda r: r.off)
        used: Dict[str, int] = {}
        for k, r in enumerate(self.models):
            r.n = k
            base = (r.name or "modelo").rsplit(".", 1)[0] or "modelo"
            c = used.get(base, 0)
            used[base] = c + 1
            r.name = base if not c else f"{base}_{c + 1}"

    def _block(self, b: int, e: dict, seen: dict):
        d = self.data
        a, size, t = struct.unpack_from(">3I", d, b)
        off = b + a
        if d[off:off + 4] != b"NJCM":
            return
        ref = seen.get(off)
        if ref is None:
            njtl = b + t if t and d[b + t:b + t + 4] == b"NJTL" else self._njtl_before(off)
            ref = seen[off] = ModelRef(len(self.models), off, njtl, e["name"], e, e["code"])
            self.models.append(ref)
        e["models"].append(ref)

    def _njtl_before(self, off: int) -> int:
        """O NJTL que vem logo antes do modelo (ate' 64 KB atras, sem outro modelo no meio)."""
        d = self.data
        i = d.rfind(b"NJTL", max(0, off - 0x10000), off)
        if i < 0 or d.find(b"NJCM", i, off) >= 0:
            return 0
        return i

    def _textures(self, xoff: int):
        d = self.data
        try:
            n = struct.unpack_from(">I", d, xoff)[0]
            if not 0 < n < 4096 or xoff + 4 + n * 0x2C > len(d):
                return
            p = xoff + 4 + n * 0x2C
            for i in range(n):
                o = xoff + 4 + i * 0x2C
                name = d[o:o + 0x28].split(b"\0")[0].decode("latin1")
                size = struct.unpack_from(">I", d, o + 0x28)[0]
                g = d.find(b"GVRT", p, p + 0x40)
                if g >= 0:
                    self.textures.setdefault(name.lower(), g)
                    self.tex_order.append(name)
                p += size
        except struct.error:
            pass

    def _textures_scan(self):
        """Arquivo sem tabela de texturas: usa a ordem em que aparecem."""
        d = self.data
        i = k = 0
        while True:
            i = d.find(b"GVRT", i)
            if i < 0:
                break
            name = f"tex{k:03d}"
            self.textures[name] = i
            self.tex_order.append(name)
            k += 1
            i += 4

    def tex_names(self, ref: ModelRef) -> List[str]:
        return read_njtl(self.data, ref.njtl) if ref.njtl else []

    def gvrt_list(self) -> List[int]:
        if not hasattr(self, "_gvrt"):
            d, out, i = self.data, [], 0
            while True:
                i = d.find(b"GVRT", i)
                if i < 0:
                    break
                out.append(i)
                i += 4
            self._gvrt = out
        return self._gvrt

    def model_textures(self, ref: ModelRef) -> List[Optional[int]]:
        """Posicao do GVRT de cada textura do modelo (na ordem da lista NJTL).

        Pelo nome, quando o arquivo tem a tabela de texturas; sem ela (.mlk, .sml) as
        texturas de um modelo vem logo depois dele, na mesma ordem."""
        names = self.tex_names(ref)
        if not names:
            return []
        d = self.data
        ends = [x for x in (d.find(b"NJTL", ref.off + 4), d.find(b"NJCM", ref.off + 4)) if x > 0]
        nxt = min(ends) if ends else len(d)
        after = [g for g in self.gvrt_list() if ref.off < g < nxt]
        out: List[Optional[int]] = []
        for i, n in enumerate(names):
            g = self.textures.get(n.lower())
            if g is None and i < len(after):
                g = after[i]
            out.append(g)
        return out

    def load(self, n: int) -> Model:
        """Le o modelo n (uma copia nova a cada chamada)."""
        ref = self.models[n]
        return read_njcm(self.data, ref.off, ref.name, self.tex_names(ref))
