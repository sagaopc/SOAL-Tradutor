"""Extrator para remaster: texturas (no formato dos pacotes HD do Dolphin/recomp) e modelos 3D
(glTF 2.0, que o Blender abre direto).

Para cada arquivo do jogo com texturas ou modelos:
    texturas/GEA/<pasta>/<arquivo>/tex1_....png   - cada textura com o nome que o recomp procura;
                                                   melhore a imagem (em qualquer resolucao), mantenha
                                                   o nome e instale: o jogo passa a usar a nova
    modelos/<pasta>/<arquivo>/<modelo>.glb        - um modelo por arquivo: malha, esqueleto, pesos,
                                                   materiais e texturas
    cenarios/<pasta>/<arquivo>.glb                - o lugar inteiro, com cada objeto na sua posicao
                                                   (cidades, construcoes, interiores)
    indice.csv                                    - de onde vem cada textura e quais modelos a usam
"""

from __future__ import annotations

import array
import csv
import io
import json
import math
import os
import struct
import sys
from typing import Callable, Dict, List, Optional, Tuple

from . import aklz, modelo, textura

MODEL_EXT = (".mld", ".mlk", ".mll", ".sml")
TEX_EXT = MODEL_EXT + (".gvr",)

# nome de cada pasta do jogo na saida (e na tela)
FOLDERS = {
    "bchara": "Personagens e inimigos (batalha)",
    "field": "Cenários, cidades e objetos",
    "battle": "Batalha (cenários e interface)",
    "beff": "Efeitos de batalha",
    "title": "Tela-título",
    "ending": "Encerramento",
    "": "Outros (raiz do disco)",
}

WRAP = {"repeat": 10497, "mirror": 33648, "clamp": 33071}


# ------------------------------------------------------------------ glTF
class Gltf:
    def __init__(self, generator: str = "SOAL Tradutor"):
        self.j = {"asset": {"version": "2.0", "generator": generator}, "scene": 0,
                  "scenes": [{"nodes": []}], "nodes": [], "meshes": [], "materials": [],
                  "textures": [], "images": [], "samplers": [], "accessors": [],
                  "bufferViews": [], "buffers": []}
        self.bin = bytearray()
        self._samplers: Dict[tuple, int] = {}
        self._textures: Dict[tuple, int] = {}
        self._images: Dict[str, int] = {}
        self.ext_used = set()

    def view(self, data: bytes, target: Optional[int] = None) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        bv = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.bin += data
        self.j["bufferViews"].append(bv)
        return len(self.j["bufferViews"]) - 1

    def accessor(self, data: bytes, comp: int, count: int, typ: str, target=None, mn=None, mx=None,
                 normalized=False) -> int:
        a = {"bufferView": self.view(data, target), "componentType": comp, "count": count, "type": typ}
        if mn is not None:
            a["min"], a["max"] = mn, mx
        if normalized:
            a["normalized"] = True
        self.j["accessors"].append(a)
        return len(self.j["accessors"]) - 1

    def floats(self, rows, typ: str, target=34962, minmax=False) -> int:
        flat = array.array("f", [x for r in rows for x in r])
        if sys.byteorder != "little":
            flat.byteswap()
        n = {"VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16, "SCALAR": 1}[typ]
        mn = mx = None
        if minmax and rows:
            mn = [min(r[k] for r in rows) for k in range(n)]
            mx = [max(r[k] for r in rows) for k in range(n)]
        return self.accessor(flat.tobytes(), 5126, len(rows), typ, target, mn, mx)

    def image(self, png: bytes, name: str) -> int:
        i = self._images.get(name)
        if i is None:
            bv = self.view(png)
            self.j["images"].append({"bufferView": bv, "mimeType": "image/png", "name": name})
            i = self._images[name] = len(self.j["images"]) - 1
        return i

    def texture(self, img: int, ws: int, wt: int) -> int:
        sk = (ws, wt)
        s = self._samplers.get(sk)
        if s is None:
            self.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": ws, "wrapT": wt})
            s = self._samplers[sk] = len(self.j["samplers"]) - 1
        tk = (img, s)
        t = self._textures.get(tk)
        if t is None:
            self.j["textures"].append({"source": img, "sampler": s})
            t = self._textures[tk] = len(self.j["textures"]) - 1
        return t

    def node(self, d: dict, root: bool = False) -> int:
        self.j["nodes"].append(d)
        i = len(self.j["nodes"]) - 1
        if root:
            self.j["scenes"][0]["nodes"].append(i)
        return i

    def glb(self) -> bytes:
        while len(self.bin) % 4:
            self.bin.append(0)
        j = dict(self.j)
        j["buffers"] = [{"byteLength": len(self.bin)}]
        if self.ext_used:
            j["extensionsUsed"] = sorted(self.ext_used)
        for k in ("meshes", "materials", "textures", "images", "samplers", "accessors", "bufferViews"):
            if not j[k]:
                del j[k]
        js = json.dumps(j, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js +
                struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin))


def quat_from_rot(m) -> List[float]:
    """Quaternion (x, y, z, w) de uma matriz de rotacao (linha a linha, 4x4)."""
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return [x / n, y / n, z / n, w / n]


def col_major(m) -> List[float]:
    return [m[r * 4 + c] for c in range(4) for r in range(4)]


# ------------------------------------------------------------------ texturas de um arquivo
class FileTextures:
    """As texturas de um arquivo: decodifica uma vez, guarda PNG, nome do Dolphin e se tem
    transparencia."""

    def __init__(self, data: bytes):
        self.tf = textura.TexFile(data)
        self._png: Dict[int, Tuple[bytes, bool]] = {}
        self._name: Dict[int, str] = {}

    def by_offset(self, off: Optional[int]) -> Optional[int]:
        if off is None:
            return None
        return self.tf.by_offset(off)

    def name(self, n: int) -> str:
        if n not in self._name:
            try:
                self._name[n] = self.tf.dolphin_name(n)
            except Exception:                      # formato sem nome no Dolphin
                self._name[n] = f"textura_{n:03d}"
        return self._name[n]

    def png(self, n: int) -> Optional[Tuple[bytes, bool]]:
        """(PNG, tem pixels transparentes) ou None se o formato nao e' suportado."""
        if n not in self._png:
            t = self.tf.tex[n]
            if not t.ok:
                self._png[n] = None
            else:
                try:
                    img = self.tf.image(n)
                except Exception:
                    self._png[n] = None
                else:
                    a = img.getchannel("A")
                    lo = a.getextrema()[0]
                    b = io.BytesIO()
                    img.save(b, "PNG", optimize=False)
                    self._png[n] = (b.getvalue(), lo < 250)
        return self._png[n]


# ------------------------------------------------------------------ modelo -> glTF
def is_marker(grp: modelo.Group) -> bool:
    """Caixa sem textura de 12 triangulos: gatilho de script, escada, porta... O jogo usa para
    saber onde o personagem esta', mas nao desenha."""
    if grp.mat.tex >= 0 or grp.mat.alpha or len(grp.tris) != 12:
        return False
    pts = {tuple(round(c, 3) for c in v[0]) for v in grp.verts}
    if len(pts) != 8:
        return False
    xs, ys, zs = ({p[k] for p in pts} for k in range(3))
    return len(xs) <= 2 and len(ys) <= 2 and len(zs) <= 2 or len(pts) == 8 and len(grp.verts) <= 24


def visible(m: modelo.Model) -> modelo.Model:
    m.groups = [g for g in m.groups if not is_marker(g)]
    return m


def _model_materials(g: Gltf, m: modelo.Model, tex_off: List[Optional[int]], ft: FileTextures,
                     cache: Dict[tuple, int], used: Optional[Dict[str, set]] = None) -> List[int]:
    out = []
    for grp in m.groups:
        mat = grp.mat
        tn = None
        if 0 <= mat.tex < len(tex_off):
            tn = ft.by_offset(tex_off[mat.tex])
        key = (tn,) + mat.key()
        i = cache.get(key)
        if i is None:
            d = {"name": "material", "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0}}
            pbr = d["pbrMetallicRoughness"]
            transparent = False
            if tn is not None:
                p = ft.png(tn)
                if p:
                    png, transparent = p
                    name = ft.name(tn)
                    img = g.image(png, name)
                    ws = WRAP["mirror"] if mat.flip_u else WRAP["clamp"] if mat.clamp_u else WRAP["repeat"]
                    wt = WRAP["mirror"] if mat.flip_v else WRAP["clamp"] if mat.clamp_v else WRAP["repeat"]
                    pbr["baseColorTexture"] = {"index": g.texture(img, ws, wt)}
                    d["name"] = name
                    if used is not None:
                        used.setdefault(name, set()).add(m.name)
                    if mat.alpha and mat.diffuse[3] < 0.999:
                        pbr["baseColorFactor"] = [1.0, 1.0, 1.0, round(mat.diffuse[3], 4)]
            else:
                r, gg, b, a = mat.diffuse
                pbr["baseColorFactor"] = [round(r, 4), round(gg, 4), round(b, 4), round(a if mat.alpha else 1.0, 4)]
            if mat.alpha:
                d["alphaMode"] = "BLEND"
            elif transparent:
                d["alphaMode"] = "MASK"
                d["alphaCutoff"] = 0.5
            if mat.double:
                d["doubleSided"] = True
            if mat.unlit:
                d["extensions"] = {"KHR_materials_unlit": {}}
                g.ext_used.add("KHR_materials_unlit")
            g.j["materials"].append(d)
            i = cache[key] = len(g.j["materials"]) - 1
        out.append(i)
    return out


def _normals(grp: modelo.Group) -> List[tuple]:
    have = [v[1] for v in grp.verts]
    if all(n is not None for n in have):
        return have
    acc = [[0.0, 0.0, 0.0] for _ in grp.verts]
    for a, b, c in grp.tris:
        pa, pb, pc = grp.verts[a][0], grp.verts[b][0], grp.verts[c][0]
        e1 = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        e2 = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        for i in (a, b, c):
            for k in range(3):
                acc[i][k] += n[k]
    out = []
    for i, n in enumerate(have):
        out.append(n if n is not None else modelo._norm(acc[i]))
    return out


def add_mesh(g: Gltf, m: modelo.Model, mats: List[int], skin: bool, name: str) -> Optional[int]:
    prims = []
    for grp, mi in zip(m.groups, mats):
        vs = grp.verts
        if not vs or not grp.tris:
            continue
        nrm = _normals(grp)
        att = {"POSITION": g.floats([v[0] for v in vs], "VEC3", minmax=True),
               "NORMAL": g.floats(nrm, "VEC3")}
        if any(v[2] is not None for v in vs):
            att["TEXCOORD_0"] = g.floats([v[2] if v[2] is not None else (0.0, 0.0) for v in vs], "VEC2")
        elif grp.mat.env and grp.mat.tex >= 0:
            # reflexo (mapa de ambiente): o jogo tira a coordenada da normal; aqui, uma aproximacao fixa
            att["TEXCOORD_0"] = g.floats([(0.5 + 0.5 * n[0], 0.5 - 0.5 * n[1]) for n in nrm], "VEC2")
        if any(v[3] is not None for v in vs):
            att["COLOR_0"] = g.floats([v[3] if v[3] is not None else (1.0, 1.0, 1.0, 1.0) for v in vs], "VEC4")
        if skin:
            js, ws = [], []
            for v in vs:
                w = sorted(v[4], key=lambda x: -x[1])[:4]
                tot = sum(x[1] for x in w) or 1.0
                w = [(j, x / tot) for j, x in w] + [(0, 0.0)] * (4 - len(w))
                js.extend(j for j, _ in w)
                ws.append(tuple(x for _, x in w))
            ja = array.array("H", js)
            if sys.byteorder != "little":
                ja.byteswap()
            att["JOINTS_0"] = g.accessor(ja.tobytes(), 5123, len(vs), "VEC4", 34962)
            att["WEIGHTS_0"] = g.floats(ws, "VEC4")
        flat = [i for t in grp.tris for i in t]
        big = len(vs) > 65535
        ia = array.array("I" if big else "H", flat)
        if sys.byteorder != "little":
            ia.byteswap()
        idx = g.accessor(ia.tobytes(), 5125 if big else 5123, len(flat), "SCALAR", 34963)
        prims.append({"attributes": att, "indices": idx, "material": mi, "mode": 4})
    if not prims:
        return None
    g.j["meshes"].append({"name": name, "primitives": prims})
    return len(g.j["meshes"]) - 1


def add_skeleton(g: Gltf, m: modelo.Model, prefix: str) -> Tuple[List[int], List[int]]:
    """Cria os nos (ossos) do modelo; devolve (indices dos nos, raizes)."""
    ids, roots = [], []
    for n in m.nodes:
        d = {"name": f"{prefix}_osso{n.idx:03d}"}
        if any(abs(x) > 1e-7 for x in n.pos):
            d["translation"] = [float(x) for x in n.pos]
        q = quat_from_rot(n.rot)
        if abs(q[3]) < 0.9999999:
            d["rotation"] = q
        if any(abs(x - 1.0) > 1e-7 for x in n.scl):
            d["scale"] = [float(x) for x in n.scl]
        ids.append(g.node(d))
    for n in m.nodes:
        if n.parent >= 0:
            g.j["nodes"][ids[n.parent]].setdefault("children", []).append(ids[n.idx])
        else:
            roots.append(ids[n.idx])
    return ids, roots


def model_glb(mf: modelo.MldFile, ref: modelo.ModelRef, ft: FileTextures, generator: str,
              used: Optional[Dict[str, set]] = None, info: Optional[dict] = None) -> Optional[bytes]:
    m = visible(mf.load(ref.n))
    if info is not None:
        info["triangulos"] = m.tri_count
        info["ossos"] = len(m.nodes)
        info["pesos"] = m.has_weights
        info["problemas"] = list(m.problems)
    if not m.groups:
        return None
    g = Gltf(generator)
    mats = _model_materials(g, m, mf.model_textures(ref), ft, {}, used)
    skin = len(m.nodes) > 1
    mesh = add_mesh(g, m, mats, skin, m.name)
    if mesh is None:
        return None
    if skin:
        ids, roots = add_skeleton(g, m, m.name)
        for r in roots:
            g.j["scenes"][0]["nodes"].append(r)
        ibm = g.floats([col_major(modelo.mat_inv(n.world)) for n in m.nodes], "MAT4", target=None)
        g.j["skins"] = [{"name": m.name, "joints": ids, "inverseBindMatrices": ibm, "skeleton": roots[0]}]
        g.node({"name": m.name, "mesh": mesh, "skin": 0}, root=True)
    else:
        g.node({"name": m.name, "mesh": mesh}, root=True)
    return g.glb()


def _entry_trs(trs) -> dict:
    """Posicao/rotacao (graus)/escala de um objeto do cenario -> TRS do glTF."""
    pos, ang, scl = trs[0:3], trs[3:6], trs[6:9]
    d = {}
    if any(abs(x) > 1e-7 for x in pos):
        d["translation"] = [float(x) for x in pos]
    if any(abs(x) > 1e-7 for x in ang):
        _, r = modelo.mat_trs((0, 0, 0), tuple(math.radians(a) for a in ang), (1, 1, 1))
        d["rotation"] = quat_from_rot(r)
    if any(abs(x - 1.0) > 1e-7 for x in scl) and all(abs(x) > 1e-9 for x in scl):
        d["scale"] = [float(x) for x in scl]
    return d


def scene_glb(mf: modelo.MldFile, ft: FileTextures, name: str, generator: str,
              used: Optional[Dict[str, set]] = None) -> Optional[bytes]:
    """O cenario inteiro: cada objeto da lista do arquivo na sua posicao. Arquivo sem lista
    (os cenarios de batalha, .sml): todos os modelos juntos, que ja' vem na posicao."""
    ents = [e for e in mf.entries if e["models"]]
    if len(ents) < 2:
        if not name.lower().endswith(".sml") or len(mf.models) < 2:
            return None
        ents = [{"n": r.n, "name": r.name, "models": [r], "trs": (0, 0, 0, 0, 0, 0, 1, 1, 1)} for r in mf.models]
    g = Gltf(generator)
    meshes: Dict[int, Optional[int]] = {}
    mcache: Dict[tuple, int] = {}
    any_mesh = False
    for e in ents:
        kids = []
        for ref in e["models"]:
            if ref.n not in meshes:
                m = visible(mf.load(ref.n))
                mats = _model_materials(g, m, mf.model_textures(ref), ft, mcache, used)
                meshes[ref.n] = add_mesh(g, m, mats, False, ref.name)
            if meshes[ref.n] is not None:
                kids.append(g.node({"name": ref.name, "mesh": meshes[ref.n]}))
        if kids:
            any_mesh = True
            d = {"name": f"{e['n']:03d}_{e['name'] or 'objeto'}", "children": kids}
            d.update(_entry_trs(e["trs"]))
            g.node(d, root=True)
    return g.glb() if any_mesh else None


# ------------------------------------------------------------------ extracao em lote
def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s) or "x"


def list_files(files_dir: str) -> List[Tuple[str, str]]:
    """(caminho relativo com /, caminho completo) dos arquivos com texturas/modelos."""
    out = []
    for dp, dn, fn in os.walk(files_dir):
        dn.sort()
        for f in sorted(fn):
            if f.lower().endswith(TEX_EXT):
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, files_dir).replace(os.sep, "/")
                out.append((rel, full))
    return out


def folder_of(rel: str) -> str:
    return rel.split("/", 1)[0].lower() if "/" in rel else ""


def extract(files_dir: str, out_dir: str, what=("texturas", "modelos", "cenarios"),
            folders: Optional[List[str]] = None, generator: str = "SOAL Tradutor",
            progress: Optional[Callable[[int, int, str], None]] = None,
            cancel: Optional[Callable[[], bool]] = None) -> dict:
    """Extrai tudo de files_dir (a pasta files/ do jogo) para out_dir."""
    if not textura.have_pillow():
        raise RuntimeError("falta o Pillow para gravar as imagens")
    todo = [(r, f) for r, f in list_files(files_dir) if folders is None or folder_of(r) in folders]
    os.makedirs(out_dir, exist_ok=True)
    seen_tex: Dict[str, str] = {}               # nome do Dolphin -> onde foi gravada
    scene_paths: set = set()
    index: List[list] = []
    used: Dict[str, set] = {}
    rep = {"arquivos": 0, "texturas": 0, "texturas_repetidas": 0, "modelos": 0, "cenarios": 0,
           "triangulos": 0, "erros": [], "pasta": out_dir}
    for k, (rel, full) in enumerate(todo):
        if cancel and cancel():
            rep["cancelado"] = True
            break
        if progress:
            progress(k, len(todo), rel)
        try:
            raw = open(full, "rb").read()
            data = aklz.decompress(raw) if aklz.is_compressed(raw) else raw
            if b"GVRT" not in data and b"NJCM" not in data:
                continue
            base = rel.rsplit(".", 1)[0]
            # pasta com o nome inteiro do arquivo (cr001.mld e cr001.mlk sao arquivos diferentes)
            sub = "/".join(_safe(x) for x in rel.split("/"))
            ft = FileTextures(data)
            used_here: Dict[str, set] = {}
            if b"NJCM" in data and ("modelos" in what or "cenarios" in what):
                mf = modelo.MldFile(data)
                if "modelos" in what:
                    for ref in mf.models:
                        info: dict = {}
                        try:
                            glb = model_glb(mf, ref, ft, generator, used_here, info)
                        except Exception as e:      # um modelo ruim nao para o resto
                            rep["erros"].append(f"{rel} ({ref.name}): {e}")
                            continue
                        if glb:
                            p = os.path.join(out_dir, "modelos", *sub.split("/"), _safe(ref.name) + ".glb")
                            os.makedirs(os.path.dirname(p), exist_ok=True)
                            with open(p, "wb") as fh:
                                fh.write(glb)
                            rep["modelos"] += 1
                            rep["triangulos"] += info.get("triangulos", 0)
                if "cenarios" in what:
                    try:
                        glb = scene_glb(mf, ft, rel, generator, used_here)
                    except Exception as e:
                        rep["erros"].append(f"{rel} (cenário): {e}")
                        glb = None
                    if glb:
                        p = os.path.join(out_dir, "cenarios", *"/".join(_safe(x) for x in base.split("/")).split("/")) + ".glb"
                        if p in scene_paths:          # outro arquivo com o mesmo nome (ex.: .mld e .sml)
                            p = os.path.join(out_dir, "cenarios", *sub.split("/")) + ".glb"
                        scene_paths.add(p)
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        with open(p, "wb") as fh:
                            fh.write(glb)
                        rep["cenarios"] += 1
            for name, ms in used_here.items():
                used.setdefault(name, set()).update(f"{base}:{x}" for x in ms)
            if "texturas" in what:
                for t in ft.tf.tex:
                    p = ft.png(t.n)
                    if not p:
                        continue
                    name = ft.name(t.n)
                    index.append([name, rel, t.n, t.w, t.h, t.fmt_name, len(t.levels()) - 1])
                    if name in seen_tex:
                        rep["texturas_repetidas"] += 1
                        continue
                    dst = os.path.join(out_dir, "texturas", "GEA", *sub.split("/"), name + ".png")
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as fh:
                        fh.write(p[0])
                    seen_tex[name] = dst
                    rep["texturas"] += 1
            rep["arquivos"] += 1
        except Exception as e:
            rep["erros"].append(f"{rel}: {e}")
    if progress:
        progress(len(todo), len(todo), "")
    if index:
        with open(os.path.join(out_dir, "indice_texturas.csv"), "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["textura", "arquivo do jogo", "número no arquivo", "largura", "altura", "formato",
                        "mipmaps", "usada nos modelos"])
            for row in index:
                w.writerow(row + [", ".join(sorted(used.get(row[0], ())))])
    with open(os.path.join(out_dir, "LEIA-ME.txt"), "w", encoding="utf-8") as fh:
        fh.write(README)
    return rep


README = """Extração para remaster — SOAL Tradutor
=======================================

texturas/GEA/...   Cada textura do jogo, com o nome que o recomp (e o Dolphin) procura.
                   Melhore as imagens (aumentar 2x, 4x, redesenhar...), MANTENHA O NOME do
                   arquivo e instale a pasta GEA pelo SOAL Tradutor (Extrair para remaster >
                   Instalar texturas no recomp) ou pelo próprio recomp (Configurações > Gráficos >
                   Texture pack > Import a folder...). A resolução nova pode ser qualquer uma,
                   desde que a proporção seja a mesma. Apague as que você não mudou.

modelos/...        Cada modelo 3D em glTF (.glb): malha, esqueleto, pesos e texturas.
                   No Blender: Arquivo > Importar > glTF 2.0. Os materiais usam as mesmas
                   texturas da pasta texturas/ (o nome da imagem é o nome da textura).

cenarios/...       Cada lugar inteiro (cidades, construções, interiores) com os objetos na
                   posição do jogo.

indice_texturas.csv  De qual arquivo do jogo vem cada textura e quais modelos a usam.

Observação: algumas texturas (menus que o jogo copia da tela, por exemplo) mudam de nome a
cada vez e não podem ser trocadas por pacote.
"""


# ------------------------------------------------------------------ instalar no recomp
def install_textures(src_dir: str, data_dir: str, sub: str = "SOAL Tradutor") -> dict:
    """Copia as texturas tex1_*.png/.dds de src_dir para Load/Textures/GEA/<sub> do recomp e
    liga as texturas HD (GFX.ini [Settings] HiresTextures)."""
    import shutil
    from . import recomp
    dst_root = os.path.join(data_dir, "Load", "Textures", "GEA", sub)
    n = 0
    names = set()
    for dp, dn, fn in os.walk(src_dir):
        for f in fn:
            fl = f.lower()
            if fl.startswith("tex1_") and fl.endswith((".png", ".dds")):
                if fl in names:
                    continue
                names.add(fl)
                rel = os.path.relpath(os.path.join(dp, f), src_dir)
                d = os.path.join(dst_root, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(os.path.join(dp, f), d)
                n += 1
    if n:
        recomp.set_hires_textures(data_dir, True)
    return {"copiadas": n, "pasta": dst_root}
