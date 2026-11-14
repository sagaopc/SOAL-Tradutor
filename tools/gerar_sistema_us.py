"""Gera soal/data/sistema_us.json: onde ficam, no main.dol americano (GEAE8P), os textos
de itens, armas, menus e mensagens, e quanto espaco cada um tem.

Ferramenta de desenvolvimento; o programa so' le o .json pronto. Precisa do main.dol
americano original e do english.sot da versao europeia (usado so' para reconhecer quais
textos do main.dol sao do jogo e a que tabela cada um pertence). O .json guarda posicoes,
tamanhos e grupos, nenhum texto do jogo.

    python tools/gerar_sistema_us.py <main.dol americano> <english.sot europeu>

As posicoes das tabelas com estrutura fixa (nomes de armas, itens, navios...) e das
descricoes vem do ALX (Skies of Arcadia Legends Examiner, de Marcel Renner).
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soal import sistema  # noqa: E402

# grupo, tabela, inicio, fim, quantidade, tamanho do nome (o nome fica no comeco de cada registro)
STRUCTS = [
    ("personagens", "Personagens", 0x2c1860, 0x2c1bf0, 6, 11),
    ("magias", "MagicDataTable", 0x2c1bf0, 0x2c22b0, 0x24, 17),
    ("magias", "MagicDataTable+36", 0x2c22b0, 0x2c2790, 0x1a, 17),
    ("armas", "WeaponDataTable", 0x2c2790, 0x2c3190, 0x50, 17),
    ("armaduras", "ArmorDataTable", 0x2c3190, 0x2c3e10, 0x50, 17),
    ("acessorios", "AccessDataTable", 0x2c3e10, 0x2c4a90, 0x50, 17),
    ("itens", "IppanItemDataTable", 0x2c4c34, 0x2c5774, 0x50, 17),
    ("itens_especiais", "ClearItemDataTable", 0x2c5774, 0x2c5e54, 0x50, 17),
    ("procurados", "OtokogiDataTable", 0x2c5e54, 0x2c6184, 0x18, 25),
    ("navio", "PlShipInitParamP", 0x2d3740, 0x2d3934, 5, 20),
    ("navio", "EnShipInitParamP", 0x2d3934, 0x2d4e4c, 0x2d, 20),
    ("navio", "ShipWeaponParamP", 0x2d4e4c, 0x2d53ec, 0x28, 17),
    ("navio", "ShipAccessParamP", 0x2d53ec, 0x2d5a2c, 0x28, 17),
    ("navio", "ShipItemParamP", 0x2d5a2c, 0x2d5e64, 0x1e, 17),
    ("navio", "ShipCrewParamP", 0x2d5e64, 0x2d617c, 0x16, 17),
    ("inimigos", "EnspatkDataTable", 0x2aa440, 0x2aa950, 0x24, 17),
    ("inimigos", "EnspatkDataTable+36", 0x2aa950, 0x2ad4c4, 0x135, 17),
]

# descricoes: uma atras da outra, cada uma ocupando blocos de 4 bytes
DESCRS = [
    ("magias", "MagicMessageDataTable", 0x2c6668, 0x2c73e0),
    ("magias", "MagicMessageDataTable+36", 0x2c73e0, 0x2c7d9c),
    ("armas", "WeaponMessageDataTable", 0x2c7d9c, 0x2c9714),
    ("armaduras", "ArmorMessageDataTable", 0x2c9714, 0x2ca880),
    ("acessorios", "AccessoryMessageDataTable", 0x2ca880, 0x2cbc88),
    ("itens", "IppanItemMessageDataTable", 0x2cbc88, 0x2cd4ec),
    ("itens_especiais", "ClearItemMessageDataTable", 0x2cd4ec, 0x2ce220),
    ("navio", "ShipHouMessageDataTable", 0x2ce220, 0x2ceef8),
    ("navio", "ShipAccessoryMessageDataTable", 0x2ceef8, 0x2cfbf0),
    ("navio", "ShipItemMessageDataTable", 0x2cfbf0, 0x2d05c4),
    ("navio", "ShipMagicMessageDataTable", 0x2d05c4, 0x2d0ef4),
    ("navio", "ShipCrewMessageDataTable", 0x2d0ef4, 0x2d1600),
]

# faixas do main.dol onde ha' textos (ALX, string detector GC-US-GEA)
RANGES = [
    (0x0003fc, 0x00042a), (0x2a9820, 0x2b1dda), (0x2b2f68, 0x2b39e8), (0x2b4c64, 0x2d7595),
    (0x2da23c, 0x2db559), (0x2df888, 0x2e06f1), (0x2e5f60, 0x2e807f), (0x2e8b20, 0x2e8ea3),
    (0x2eb618, 0x2ebdad), (0x2f30ec, 0x2f47d1), (0x2f63f8, 0x2f989b), (0x2ffa90, 0x2ffe40),
    (0x300028, 0x300091), (0x3002b0, 0x3003f7), (0x3006f8, 0x3007de), (0x300af8, 0x300b18),
    (0x301530, 0x301626), (0x301874, 0x301884), (0x301960, 0x30198c), (0x3026e8, 0x302766),
    (0x302a6c, 0x302ab7), (0x302fa8, 0x302fb6), (0x3030c0, 0x30311d), (0x303170, 0x3031b4),
    (0x3032d0, 0x3032fc), (0x3033f0, 0x30340e), (0x303570, 0x3035d1), (0x303784, 0x30389e),
    (0x303ad8, 0x303ce5), (0x303e98, 0x303f39), (0x303fc0, 0x304183),
]


def sections(d):
    offs = struct.unpack_from(">18I", d, 0)
    addr = struct.unpack_from(">18I", d, 0x48)
    size = struct.unpack_from(">18I", d, 0x90)
    return [(i, offs[i], addr[i], size[i]) for i in range(18) if size[i]]


def is_text(raw: bytes) -> bool:
    try:
        u = sistema.us_decode(raw)
    except ValueError:
        return False
    if any(0x3040 <= ord(c) <= 0x9FFF or 0xFF61 <= ord(c) <= 0xFF9F for c in u):
        return False
    return sum(c.isalpha() for c in u) >= 2


def cstr(d, o, limit=None):
    e = d.find(b"\0", o, limit if limit else len(d))
    return d[o:e] if e >= 0 else d[o:limit]


def main():
    dol_path, sot_path = sys.argv[1], sys.argv[2]
    d = open(dol_path, "rb").read()
    secs = sections(d)
    text_secs = [(fo, s) for i, fo, a, s in secs if i < 7]
    data_secs = [(fo, s) for i, fo, a, s in secs if i >= 7]

    def addr(o):
        for i, fo, a, s in secs:
            if fo <= o < fo + s:
                return a + o - fo
        raise ValueError(hex(o))

    # ponteiros (palavras de 4 bytes alinhadas) nas secoes de dados
    ptrs = collections.defaultdict(list)
    for fo, s in data_secs:
        for o in range(fo, fo + s - 3, 4):
            v = struct.unpack_from(">I", d, o)[0]
            if 0x80000000 <= v < 0x81800000:
                ptrs[v].append(o)
    # enderecos montados no codigo com lis + addi/ori/lwz...
    code = set()
    for fo, s in text_secs:
        regs = {}
        for o in range(fo, fo + s, 4):
            ins = struct.unpack_from(">I", d, o)[0]
            op = ins >> 26
            if op == 15 and ((ins >> 16) & 31) == 0:
                regs[(ins >> 21) & 31] = (ins & 0xFFFF) << 16
            elif op in (14, 24, 32, 34, 36, 38, 40, 44, 48, 52):
                ra = (ins >> 16) & 31
                if ra in regs:
                    lo = ins & 0xFFFF
                    v = regs[ra] | lo if op == 24 else (regs[ra] + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF
                    code.add(v)
            elif op == 18:
                regs.clear()

    entries = []          # dicts: k, grp, tab, off, kind, cap
    taken = set()

    def add(grp, tab, off, kind, cap, raw):
        entries.append({"grp": grp, "tab": tab, "off": off, "kind": kind, "cap": cap, "len": len(raw)})
        taken.add(off)

    # 1) nomes em registros de tamanho fixo
    for grp, tab, a, b, n, ns in STRUCTS:
        st = (b - a) // n
        assert st * n == b - a, tab
        for i in range(n):
            o = a + i * st
            raw = cstr(d, o, o + ns)
            if len(raw) >= ns or not raw or not is_text(raw) or raw.upper().startswith(b"DUMMY"):
                continue
            add(grp, f"{tab}:{i}", o, "campo", ns, raw)

    # 2) descricoes
    dscr_ranges = []
    for grp, tab, a, b in DESCRS:
        o = a
        i = 0
        while o < b:
            raw = cstr(d, o, b)
            nxt = (o + len(raw) + 1 + 3) & ~3
            if raw and is_text(raw) and not raw.upper().startswith((b"DUMMY", b"CUT.")):
                add(grp, f"{tab}:{i}", o, "solto", None, raw)
            o = max(nxt, o + 4)
            i += 1
        dscr_ranges.append((a, b))

    # 3) demais textos: reconhecidos pelo texto ingles igual no english.sot europeu
    sot = sistema.Sot(open(sot_path, "rb").read())
    want = {}
    for tname, strs in sot.tables:
        if tname in sistema.SOT_SKIP:
            continue
        for i, s in enumerate(strs):
            t = sistema.sot_decode(s).replace("…", "...").strip()
            if t:
                want.setdefault(t, (tname, i))
    inside = lambda o: any(a <= o < b for _g, _t, a, b, _n, _s in STRUCTS) or any(a <= o < b for a, b in dscr_ranges)
    cands = []
    for a, b in RANGES:
        p = a
        while p < b:
            e = d.find(b"\0", p, b)
            if e < 0:
                e = b
            if e > p and (p == a or d[p - 1] == 0) and not inside(p) and p not in taken:
                raw = d[p:e]
                if is_text(raw):
                    cands.append((p, raw))
            p = e + 1
    seq = []
    for o, raw in cands:
        t = sistema.us_decode(raw).replace("…", "...").strip()
        seq.append([o, raw, want.get(t)])
    # textos sem par europeu entre dois da mesma tabela, perto um do outro: mesma tabela
    for k, x in enumerate(seq):
        if x[2]:
            continue
        pj = next((j for j in range(k - 1, -1, -1) if seq[j][2]), None)
        nj = next((j for j in range(k + 1, len(seq)) if seq[j][2]), None)
        if pj is None or nj is None:
            continue
        if seq[pj][2][0] == seq[nj][2][0] and seq[nj][0] - seq[pj][0] < 0x400 and len(x[1]) >= 4:
            x[2] = (seq[pj][2][0], -1)
    for o, raw, m in seq:
        if not m:
            continue
        grp = sistema.SOT_GROUPS.get(m[0])
        if not grp:
            continue
        add(grp, f"{m[0]}:{m[1]}" if m[1] >= 0 else f"{m[0]}:?", o, "solto", None, raw)

    entries.sort(key=lambda e: e["off"])
    starts = sorted(e["off"] for e in entries)
    # espaco de cada texto solto, quem aponta para ele, e se da' para muda-lo de lugar
    for e in entries:
        o = e["off"]
        e["k"] = f"{o:06x}"
        if e["kind"] != "solto":
            continue
        end = o + e["len"] + 1
        if o % 4 == 0:
            lim = (end + 3) & ~3
            nxt = next((s for s in starts if s > o), lim)
            j = end
            while j < min(lim, nxt) and d[j] == 0:
                j += 1
            end = j
        e["cap"] = end - o
        a = addr(o)
        e["ptrs"] = ptrs.get(a, [])
        e["code"] = a in code
        inner = any(ptrs.get(addr(o) + j) for j in range(1, e["cap"]))
        e["move"] = bool(e["ptrs"]) and not e["code"] and not inner and o % 4 == 0
    # blocos de textos moveis encostados: podem ser rearrumados juntos
    pools = []
    cur = None
    for e in entries:
        if e["kind"] == "solto" and e["move"]:
            if cur and cur["end"] == e["off"]:
                cur["keys"].append(e["k"])
                cur["end"] = e["off"] + e["cap"]
                continue
            cur = {"start": e["off"], "end": e["off"] + e["cap"], "keys": [e["k"]]}
            pools.append(cur)
        else:
            cur = None
    pools = [p for p in pools if len(p["keys"]) > 1]
    pooled = {k for p in pools for k in p["keys"]}
    out_entries = []
    for e in entries:
        x = {"k": e["k"], "grp": e["grp"], "tab": e["tab"], "off": e["off"], "cap": e["cap"],
             "fixo": e["kind"] == "campo"}
        if e["k"] in pooled:
            x["ptrs"] = e["ptrs"]
        out_entries.append(x)
    out = {
        "_sobre": "Gerado por tools/gerar_sistema_us.py. Posicoes no main.dol americano (GEAE8P).",
        "dol_sha1": hashlib.sha1(d).hexdigest(),
        "entries": out_entries,
        "pools": [{"start": p["start"], "end": p["end"], "keys": p["keys"]} for p in pools],
    }
    dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "soal", "data", "sistema_us.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    c = collections.Counter(e["grp"] for e in out_entries)
    print(len(out_entries), "textos;", len(pools), "blocos com", len(pooled), "textos moveis")
    for g, n in sorted(c.items()):
        print(" ", g, n)


if __name__ == "__main__":
    main()
