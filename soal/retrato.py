"""Miniatura de um modelo 3D (GLB) em PNG, so' com Python e Pillow: triangulos pintados do
mais longe para o mais perto, com a cor da textura e uma luz simples. Serve para mostrar quem
e' cada tripulante na pasta dos sons."""
import io
import json
import math
import struct
from typing import List, Optional

_CT = {5126: ("f", 4), 5123: ("H", 2), 5125: ("I", 4), 5121: ("B", 1)}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _acc(j, binc, i) -> List[tuple]:
    a = j["accessors"][i]
    bv = j["bufferViews"][a["bufferView"]]
    fmt, size = _CT[a["componentType"]]
    n = _NC[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or size * n
    norm = a.get("normalized") and fmt != "f"
    scale = {"B": 255.0, "H": 65535.0}.get(fmt, 1.0)
    out = []
    for k in range(a["count"]):
        v = struct.unpack_from("<%d%s" % (n, fmt), binc, off + k * stride)
        out.append(tuple(x / scale for x in v) if norm else v)
    return out


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _local(n):
    if "matrix" in n:
        m = n["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = n.get("scale", [1, 1, 1])
    tx, ty, tz = n.get("translation", [0, 0, 0])
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[0][0] * sx, r[0][1] * sy, r[0][2] * sz, tx],
            [r[1][0] * sx, r[1][1] * sy, r[1][2] * sz, ty],
            [r[2][0] * sx, r[2][1] * sy, r[2][2] * sz, tz], [0, 0, 0, 1]]


def render(glb: bytes, size: int = 256, yaw: float = 20, pitch: float = 12,
           bg=(58, 68, 88)) -> Optional[bytes]:
    from PIL import Image, ImageDraw
    if glb[:4] != b"glTF":
        return None
    jl = struct.unpack_from("<I", glb, 12)[0]
    j = json.loads(glb[20:20 + jl])
    o = 20 + jl
    bl = struct.unpack_from("<I", glb, o)[0]
    binc = glb[o + 8:o + 8 + bl]
    imgs = {}

    def tex_of(mat):
        bt = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if not bt:
            return None
        src = j["textures"][bt["index"]]["source"]
        if src not in imgs:
            im = j["images"][src]
            bv = j["bufferViews"][im["bufferView"]]
            s = bv.get("byteOffset", 0)
            imgs[src] = Image.open(io.BytesIO(binc[s:s + bv["byteLength"]])).convert("RGBA")
        return imgs[src]

    tris = []
    ident = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    nodes = j.get("nodes", [])

    def walk(i, parent, depth=0):
        if depth > 64:
            return
        n = nodes[i]
        w = _mul(parent, _local(n))
        if "mesh" in n:
            m = ident if "skin" in n else w
            for p in j["meshes"][n["mesh"]]["primitives"]:
                at = p["attributes"]
                pos = [(m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
                        m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
                        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]) for x, y, z in _acc(j, binc, at["POSITION"])]
                uv = _acc(j, binc, at["TEXCOORD_0"]) if "TEXCOORD_0" in at else None
                col = _acc(j, binc, at["COLOR_0"]) if "COLOR_0" in at else None
                idx = [v[0] if isinstance(v, tuple) else v for v in _acc(j, binc, p["indices"])]
                mat = j["materials"][p["material"]] if "material" in p else {}
                tris.append((pos, uv, col, idx, tex_of(mat),
                             mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1]),
                             mat.get("alphaMode", "OPAQUE"), mat.get("doubleSided", False)))
        for c in n.get("children", []):
            walk(c, w, depth + 1)

    for r in j["scenes"][j.get("scene", 0)]["nodes"]:
        walk(r, ident)
    pts = [p for t in tris for p in t[0]]
    if not pts:
        return None
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    c = [(lo[k] + hi[k]) / 2 for k in range(3)]
    rad = max(1e-6, math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3))) / 2)
    ya, pa = math.radians(yaw), math.radians(pitch)
    cy, sy, cp, sp = math.cos(ya), math.sin(ya), math.cos(pa), math.sin(pa)
    ss = size * 2
    light = (0.4, 0.8, 0.5)
    ln = math.sqrt(sum(v * v for v in light))
    light = tuple(v / ln for v in light)
    faces = []
    for pos, uv, col, idx, tex, bc, am, ds in tris:
        scr = []
        for x, y, z in pos:
            x, y, z = x - c[0], y - c[1], z - c[2]
            x, z = cy * x + sy * z, -sy * x + cy * z
            y, z = cp * y - sp * z, sp * y + cp * z
            scr.append(((x / rad * 0.5 + 0.5) * ss, (-y / rad * 0.5 + 0.5) * ss, -z))
        for t in range(0, len(idx) - 2, 3):
            a, b, d = idx[t], idx[t + 1], idx[t + 2]
            (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = scr[a], scr[b], scr[d]
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9 or (area > 0 and not ds):
                continue
            pa_, pb, pc = pos[a], pos[b], pos[d]
            e1 = [pb[k] - pa_[k] for k in range(3)]
            e2 = [pc[k] - pa_[k] for k in range(3)]
            fn = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
            fl = math.sqrt(sum(v * v for v in fn)) or 1
            shade = 0.45 + 0.55 * abs(sum(fn[k] * light[k] for k in range(3)) / fl)
            rgba = [bc[0], bc[1], bc[2], bc[3] if len(bc) > 3 else 1]
            if tex is not None and uv is not None:
                tw, th = tex.size
                acc_ = [0, 0, 0, 0]
                samples = [uv[a], uv[b], uv[d], tuple((uv[a][k] + uv[b][k] + uv[d][k]) / 3 for k in range(2))]
                for u, v in samples:
                    px = tex.getpixel((int(u * tw) % tw, int(v * th) % th))
                    for k in range(4):
                        acc_[k] += px[k] / 255 / len(samples)
                rgba = [rgba[k] * acc_[k] for k in range(4)]
            if col is not None:
                for k in range(min(4, len(col[a]))):
                    rgba[k] *= (col[a][k] + col[b][k] + col[d][k]) / 3
            if am == "MASK" and rgba[3] < 0.5:
                continue
            if am == "BLEND" and rgba[3] < 0.25:
                continue
            fill = tuple(max(0, min(255, int(rgba[k] * shade * 255))) for k in range(3))
            faces.append(((z0 + z1 + z2) / 3, ((x0, y0), (x1, y1), (x2, y2)), fill))
    if not faces:
        return None
    faces.sort(key=lambda f: -f[0])
    im = Image.new("RGB", (ss, ss), bg)
    dr = ImageDraw.Draw(im)
    for _, poly, fill in faces:
        dr.polygon(poly, fill=fill)
    im = im.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()
