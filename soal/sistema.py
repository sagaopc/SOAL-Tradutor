"""Textos fora dos dialogos: nomes e descricoes de itens, armas, magias, pecas do navio,
menus, lojas, descobertas, diario de bordo e mensagens do cartao de memoria.

Versao americana
    Ficam no executavel (sys/main.dol). As posicoes vem de data/sistema_us.json, gerado
    por tools/gerar_sistema_us.py para o main.dol original. Ha' dois tipos de texto:

    * campo: nome dentro de um registro de tamanho fixo (arma, item, navio...). O espaco
      e' o do campo e nao muda.
    * solto: texto avulso que o jogo acha por um ponteiro. Os soltos encostados uns nos
      outros, achados so' por ponteiros, formam um bloco: na gravacao o bloco e' rearrumado
      e os ponteiros sao corrigidos, entao um texto pode crescer desde que o bloco inteiro
      caiba no espaco original. Os demais soltos tem o espaco que ja' ocupavam.

Versao europeia
    Ficam em english.sot, french.sot, german.sot e spanish.sot, um arquivo por idioma com
    tabelas de textos. O arquivo e' remontado inteiro, sem limite de tamanho por texto.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import unicodedata
from typing import Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

GROUPS = [
    ("armas", "Armas"),
    ("armaduras", "Armaduras"),
    ("acessorios", "Acessórios"),
    ("itens", "Itens"),
    ("itens_especiais", "Itens especiais"),
    ("magias", "Magias e supergolpes"),
    ("navio", "Navio e tripulação"),
    ("inimigos", "Golpes dos inimigos"),
    ("descobertas", "Descobertas"),
    ("diario", "Diário de bordo"),
    ("lugares", "Lugares"),
    ("lojas", "Lojas"),
    ("procurados", "Procurados, lendas e títulos"),
    ("menus", "Menus e mensagens"),
    ("cartao", "Cartão de memória"),
    ("personagens", "Personagens"),
]
GROUP_LABEL = dict(GROUPS)
PREFIX = "sistema/"          # nome dos arquivos virtuais na lista: sistema/armas, ...

SOT_GROUPS = {
    "sotBtlContinue": "menus", "EnspatkDataTable": "inimigos", "sotBtlPCAction": "menus",
    "sotBtlResult": "menus", "sotPauseMenu": "menus", "guildShopMsgTbl": "descobertas",
    "guildDataTbl": "descobertas", "guildMsgTbl": "descobertas", "IslandTbl": "lugares",
    "sotBtlEnd": "menus", "lWmapTownName": "lugares", "NisshiData": "diario",
    "OptionData": "menus", "savenameTbl": "lugares", "sotSbpMenu": "menus",
    "SbMagicOrder": "navio", "SbNothingName": "navio", "SbGutsName": "navio",
    "SbActionName": "navio", "RIDE_ONOFF": "navio", "sotStatusCharaCard": "menus",
    "StaCmdName": "menus", "MoonSeedName": "menus", "sotCrewCard": "navio",
    "STACMD_CREWJOB": "navio", "ExpLabel": "menus", "sotShipCard": "navio",
    "NO_EQUIP": "menus", "VMRESULT_TITLE": "menus", "WmemTbl": "cartao",
    "WmemMsgTbl": "cartao", "savecommentTbl": "lugares", "shopDataBaseTbl": "lojas",
    "cmdString": "lojas", "cardmsgtbl": "lojas", "sotShopPCCard": "lojas",
    "MagicMessageDataTable": "magias", "WeaponMessageDataTable": "armas",
    "ArmorMessageDataTable": "armaduras", "AccessoryMessageDataTable": "acessorios",
    "IppanItemMessageDataTable": "itens", "ClearItemMessageDataTable": "itens_especiais",
    "ShipHouMessageDataTable": "navio", "ShipAccessoryMessageDataTable": "navio",
    "ShipItemMessageDataTable": "navio", "ShipMagicMessageDataTable": "navio",
    "ShipCrewMessageDataTable": "navio", "HakkenMes": "descobertas",
    "HamachouTalkData": "menus", "MagicDataTable": "magias", "WeaponDataTable": "armas",
    "ArmorDataTable": "armaduras", "AccessDataTable": "acessorios",
    "IppanItemDataTable": "itens", "ClearItemDataTable": "itens_especiais",
    "OtokogiDataTable": "procurados", "sotScptMessage": "menus",
    "PlShipInitParamP": "navio", "EnShipInitParamP": "navio", "ShipWeaponParamP": "navio",
    "ShipAccessParamP": "navio", "ShipItemParamP": "navio", "ShipCrewParamP": "navio",
    "EnemyShipActionNameTable": "inimigos", "sotTitleDisc": "cartao",
    "hakkenNameDisp": "descobertas", "wanted_name": "procurados", "wanted_info": "procurados",
    "wanted_l_info": "procurados", "ln_chara": "procurados", "gMsgTbl": "cartao",
    "MF_GET_MESSAGE": "menus",
}
for _i in range(24):
    SOT_GROUPS[f"NisshiTxt{_i}"] = "diario"

# tabelas que sobraram da versao de Dreamcast ou que sao nomes de arquivo: nao se traduzem
SOT_SKIP = {"KdiskChgMsg", "WdiskChgMsg", "StaVMMsg", "StaVMSelMsg", "VM_TANKEN", "sotSaveFileID",
            "backUpFileName", "BACKUP_ARES_KEY_WORD"}

TABLE_LABELS = {
    "guildDataTbl": "descoberta", "guildMsgTbl": "dica", "guildShopMsgTbl": "sociedade",
    "NisshiData": "título", "savenameTbl": "lugar do save", "savecommentTbl": "comentário do save",
    "IslandTbl": "ilha", "lWmapTownName": "mapa", "wanted_name": "procurado",
    "wanted_info": "procurado", "wanted_l_info": "procurado", "ln_chara": "lenda",
    "OtokogiDataTable": "título do Vyse", "Personagens": "personagem",
    "EnemyShipActionNameTable": "ação de navio inimigo", "EnspatkDataTable": "golpe inimigo",
    "shopDataBaseTbl": "loja", "SbMagicOrder": "ação do navio", "SbNothingName": "ação do navio",
    "SbGutsName": "ação do navio", "SbActionName": "ação do navio", "RIDE_ONOFF": "estado",
    "sotShipCard": "navio", "sotCrewCard": "tripulação", "STACMD_CREWJOB": "função",
    "cmdString": "comando", "cardmsgtbl": "aviso", "sotShopPCCard": "loja",
    "WmemMsgTbl": "mensagem", "WmemTbl": "mensagem", "gMsgTbl": "mensagem", "sotTitleDisc": "mensagem",
    "sotBtlContinue": "batalha", "sotBtlPCAction": "batalha", "sotBtlResult": "batalha",
    "sotBtlEnd": "batalha", "sotPauseMenu": "pausa", "StaCmdName": "menu", "OptionData": "opções",
    "NO_EQUIP": "equipamento", "VMRESULT_TITLE": "minigame", "MoonSeedName": "frutas da lua",
    "ExpLabel": "experiência", "sotStatusCharaCard": "status", "sotScptMessage": "baú",
    "MF_GET_MESSAGE": "mensagem", "HamachouTalkData": "eremita", "HakkenMes": "Domingo",
    "hakkenNameDisp": "descoberta", "sotSbpMenu": "menu do navio", "lWmapTownName": "mapa",
}

EU_SOT_FILES = {"en": "english.sot", "fr": "french.sot", "de": "german.sot", "es": "spanish.sot"}
KNOWN_SHA1 = {
    "main.dol": "8c0e278126fa3b0173400fdb632038172743cc13",
    "english.sot": "7fc7fe0eef828fa2b87d637d8bfbd543898370cb",
    "spanish.sot": "1186ed9961447b3aecf3cecb4378751588d449d2",
    "french.sot": "df4b38a518a003cfeafe749133159b0fc422f324",
    "german.sot": "22d221fa9b038909d59d00972dda328a853b3e8c",
}


class SistemaError(Exception):
    pass


def table_label(tab: str) -> str:
    base = tab.split(":")[0].split("+")[0]
    if base in TABLE_LABELS:
        return TABLE_LABELS[base]
    if base.startswith("NisshiTxt"):
        return "anotação"
    if "Message" in base:
        return "descrição"
    if base.endswith(("DataTable", "ParamP")):
        return "nome"
    return base


# ------------------------------------------------------------------ .sot (europeia)
class Sot:
    """Arquivo de tabelas de textos da versao europeia (little-endian).

    Cabecalho de 16 bytes (quantidade de tabelas + 12 bytes que sao mantidos) e um
    registro de 48 bytes por tabela: nome (32), posicao, -1, quantidade (u16), -1 (u16),
    tamanho. Cada tabela e' uma sequencia de textos terminados em zero."""

    def __init__(self, data: bytes):
        if len(data) < 16:
            raise SistemaError("arquivo .sot curto demais")
        n = struct.unpack_from("<I", data, 0)[0]
        if not 0 < n < 1000 or 16 + n * 48 > len(data):
            raise SistemaError("arquivo .sot com cabecalho inesperado")
        self.head = data[4:16]
        self.tables: List[Tuple[str, List[bytes]]] = []
        self.extra: List[Tuple[int, int]] = []
        for i in range(n):
            o = 16 + i * 48
            name = data[o:o + 32].split(b"\0")[0].decode("ascii", "replace")
            off, m1, cnt, m2, size = struct.unpack_from("<IIHHI", data, o + 32)
            blob = data[off:off + size]
            parts = blob.split(b"\0")
            if parts[-1] != b"" or len(parts) - 1 != cnt or off + size > len(data):
                raise SistemaError(f"tabela {name} do .sot nao bate com o cabecalho")
            self.tables.append((name, parts[:-1]))
            self.extra.append((m1, m2))

    def build(self) -> bytes:
        n = len(self.tables)
        head = bytearray(struct.pack("<I", n) + self.head)
        body = bytearray()
        base = 16 + n * 48
        for (name, strs), (m1, m2) in zip(self.tables, self.extra):
            blob = b"".join(s + b"\0" for s in strs)
            rec = name.encode("ascii")[:31].ljust(32, b"\0")
            rec += struct.pack("<IIHHI", base + len(body), m1, len(strs), m2, len(blob))
            head += rec
            body += blob
        return bytes(head + body)


def sot_decode(raw: bytes) -> str:
    out = []
    for b in raw:
        if b == 0x85:
            out.append("…")
        elif b == 0x92:
            out.append("’")
        elif b == 0x7F:
            out.append(" ")
        else:
            out.append(chr(b))
    return "".join(out).replace("\\n", "\n")


NORMALIZE = {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "\t": " ", " ": " "}


def sot_encode(s: str, missing: Optional[Dict[str, int]] = None) -> bytes:
    out = bytearray()
    # mensagens no formato dos dialogos: o cabecalho sem nome e' \h(<7F>)
    s = s.replace("\\h( )", "\\h(\x7f)")
    for ch in s:
        if ch == "’":
            out.append(0x92)
            continue
        ch = NORMALIZE.get(ch, ch)
        if ch == "\n":
            out += b"\\n"
        elif ch == "…":
            out.append(0x85)
        elif 0x20 <= ord(ch) <= 0xFF and ord(ch) not in range(0x7F, 0xA1) or ch == "\x7f":
            out.append(ord(ch))
        elif 0x80 <= ord(ch) <= 0xA0:
            out.append(ord(ch))
        else:
            base = unicodedata.normalize("NFD", ch)
            if len(base) > 1 and 0x20 <= ord(base[0]) <= 0x7E:
                out.append(ord(base[0]))
            else:
                if missing is not None:
                    missing[ch] = missing.get(ch, 0) + 1
                out.append(ord("?"))
    return bytes(out)


# ------------------------------------------------------------------ main.dol (americana)
def us_decode(raw: bytes) -> str:
    out = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == 0x0A:
            out.append("\n")
            i += 1
        elif 0x20 <= c <= 0x7E:
            out.append(chr(c))
            i += 1
        elif (0x81 <= c <= 0x9F or 0xE0 <= c <= 0xEF) and i + 1 < n:
            try:
                ch = raw[i:i + 2].decode("shift_jis")
            except UnicodeDecodeError as exc:
                raise ValueError("par Shift-JIS invalido") from exc
            if len(ch) != 1:
                raise ValueError("par Shift-JIS ambiguo")
            out.append(ch)
            i += 2
        else:
            raise ValueError(f"byte inesperado 0x{c:02x}")
    return "".join(out)


class UsEncoder:
    """Texto do editor -> bytes do main.dol. As letras acentuadas usam a mesma tabela dos
    dialogos (simbolos da fonte redesenhados); sem ela, vao sem acento."""

    def __init__(self, charmap: Optional[Dict[str, int]] = None):
        self.charmap = dict(charmap or {})
        self.missing: Dict[str, int] = {}
        self.stripped: Dict[str, int] = {}

    def encode(self, s: str) -> bytes:
        out = bytearray()
        for ch in s:
            ch = NORMALIZE.get(ch, ch)
            if ch == "\n":
                out.append(0x0A)
                continue
            if ch == "…":
                out += b"\x81\x63"
                continue
            code = self.charmap.get(ch)
            if code is not None:
                out.append(code)
                continue
            o = ord(ch)
            if 0x20 <= o <= 0x7E:
                out.append(o)
                continue
            base = unicodedata.normalize("NFD", ch)
            if len(base) > 1 and 0x20 <= ord(base[0]) <= 0x7E:
                self.stripped[ch] = self.stripped.get(ch, 0) + 1
                out.append(ord(base[0]))
                continue
            self.missing[ch] = self.missing.get(ch, 0) + 1
            out.append(ord("?"))
        return bytes(out)


_US_MAP = None


def us_map() -> dict:
    global _US_MAP
    if _US_MAP is None:
        with open(os.path.join(DATA_DIR, "sistema_us.json"), encoding="utf-8") as fh:
            _US_MAP = json.load(fh)
    return _US_MAP


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


# ------------------------------------------------------------------ limites
_PLACEHOLDER = re.compile(r"%[-0-9]*[sdxc]|\\[hce]|\[%s\]")


def placeholders(s: str) -> List[str]:
    return sorted(_PLACEHOLDER.findall(s))


def _line_cols(s: str) -> int:
    return max((len(x) for x in s.split("\n")), default=0)


def _limits(entries: List[dict]):
    """Limite de colunas e linhas de cada texto: o do maior original da mesma tabela."""
    by_tab: Dict[str, Tuple[int, int]] = {}
    for e in entries:
        tab = e["tab"].split(":")[0]
        c, l = by_tab.get(tab, (0, 0))
        by_tab[tab] = (max(c, _line_cols(e["body"])), max(l, e["body"].count("\n") + 1))
    for e in entries:
        c, l = by_tab[e["tab"].split(":")[0]]
        e["lim"]["cols"] = c
        e["lim"]["lines"] = l


def _virtual_files(entries: List[dict]) -> List[dict]:
    by_grp: Dict[str, List[dict]] = {}
    for e in entries:
        by_grp.setdefault(e.pop("grp"), []).append(e)
    out = []
    def rank(e):
        base = e["tab"].split(":")[0]
        if "MessageDataTable" in base:
            return 1
        if base.endswith(("DataTable", "ParamP", "+36")) or "DataTable+" in base:
            return 0
        return 2
    for g, label in GROUPS:
        es = by_grp.get(g)
        if not es:
            continue
        es.sort(key=rank)          # estavel: dentro de cada tipo, a ordem do jogo
        _limits(es)
        out.append({"name": PREFIX + g, "label": label, "cat": "sistema", "virt": "sistema",
                    "entries": es, "error": None})
    return out


def us_files(dol: bytes) -> List[dict]:
    m = us_map()
    if sha1(dol) != m["dol_sha1"]:
        raise SistemaError("o main.dol nao e' o original americano")
    pool_of = {k: i for i, p in enumerate(m["pools"]) for k in p["keys"]}
    pooled = set(pool_of)
    entries = []
    for x in m["entries"]:
        o = x["off"]
        end = dol.find(b"\0", o)
        raw = dol[o:end]
        try:
            body = us_decode(raw)
        except ValueError:
            continue
        lim = {"bytes": None if x["k"] in pooled else x["cap"] - 1}
        entries.append({"k": x["k"], "sec": table_label(x["tab"]), "i": -1, "head": None, "br": False,
                        "body": body, "end": "", "tab": x["tab"], "grp": x["grp"], "lim": lim,
                        "pool": pool_of.get(x["k"])})
    return _virtual_files(entries)


def eu_files(sot_en: bytes) -> List[dict]:
    s = Sot(sot_en)
    entries = []
    seen = set()
    for tname, strs in s.tables:
        if tname in SOT_SKIP or tname not in SOT_GROUPS:
            continue
        for i, raw in enumerate(strs):
            body = sot_decode(raw)
            if not body.strip() or body.strip().upper() in ("DUMMY", "KETSUBAN", "CUT.") or \
                    body.strip().upper().startswith(("DUMMY\n", "CUT.\n")) or body.strip() == "-":
                continue
            k = f"{tname}:{i}"
            if k in seen:
                continue
            seen.add(k)
            entries.append({"k": k, "sec": table_label(tname), "i": -1, "head": None, "br": False,
                            "body": body, "end": "", "tab": k, "grp": SOT_GROUPS[tname],
                            "lim": {"bytes": None}})
    return _virtual_files(entries)


# ------------------------------------------------------------------ gravacao
def build_eu(sot_slot: bytes, sot_en: bytes, tr: Dict[str, str], report: dict) -> bytes:
    """Monta o .sot do idioma escolhido com as traducoes (chave Tabela:indice)."""
    s = Sot(sot_slot)
    en = Sot(sot_en)
    if [n for n, _ in s.tables] != [n for n, _ in en.tables]:
        raise SistemaError("as tabelas do arquivo de idioma nao batem com as do english.sot")
    idx = {n: i for i, (n, _) in enumerate(s.tables)}
    for k, t in tr.items():
        name, _, i = k.partition(":")
        if name not in idx or not i.isdigit():
            continue
        strs = s.tables[idx[name]][1]
        i = int(i)
        if i >= len(strs):
            continue
        strs[i] = sot_encode(t, report.setdefault("missing", {}))
        report["entries"] = report.get("entries", 0) + 1
    out = s.build()
    Sot(out)    # confere
    return out


def build_us(dol: bytes, tr: Dict[str, str], enc: UsEncoder, report: dict) -> bytes:
    """Grava as traducoes no main.dol. Texto que nao cabe fica em ingles e vai para o
    relatorio (report["long"])."""
    m = us_map()
    if sha1(dol) != m["dol_sha1"]:
        raise SistemaError("o main.dol nao e' o original americano")
    out = bytearray(dol)
    by_k = {x["k"]: x for x in m["entries"]}
    pooled = {k for p in m["pools"] for k in p["keys"]}
    secs = _sections(dol)
    long = report.setdefault("long", [])

    def orig(x):
        o = x["off"]
        return dol[o:dol.find(b"\0", o)]

    # campos e soltos que ficam no lugar
    for k, t in tr.items():
        x = by_k.get(k)
        if x is None or k in pooled:
            continue
        raw = enc.encode(t)
        if len(raw) + 1 > x["cap"]:
            long.append({"k": k, "issue": f"{len(raw)} letras; cabem {x['cap'] - 1}"})
            continue
        o = x["off"]
        out[o:o + x["cap"]] = raw + b"\0" * (x["cap"] - len(raw))
        report["entries"] = report.get("entries", 0) + 1
    # blocos rearrumados
    for p in m["pools"]:
        items = []
        for k in p["keys"]:
            x = by_k[k]
            t = tr.get(k)
            items.append([x, enc.encode(t) if t else None, orig(x)])
        size = p["end"] - p["start"]

        def need(its):
            return sum((len(n if n is not None else o) + 1 + 3) & ~3 for _x, n, o in its)

        dropped = []
        while need(items) > size:
            cand = [it for it in items if it[1] is not None]
            if not cand:
                break
            worst = max(cand, key=lambda it: len(it[1]) - len(it[2]))
            worst[1] = None
            dropped.append(worst[0]["k"])
        if need(items) > size:
            raise SistemaError("um bloco de textos do main.dol nao cabe nem com o original")
        for k in dropped:
            long.append({"k": k, "issue": "não coube no espaço do bloco; diminua este texto "
                                          "ou outros do mesmo grupo"})
        pos = p["start"]
        out[p["start"]:p["end"]] = b"\0" * size
        for x, new, old in items:
            raw = new if new is not None else old
            out[pos:pos + len(raw)] = raw
            a = _addr(secs, pos)
            for po in x["ptrs"]:
                struct.pack_into(">I", out, po, a)
            if new is not None:
                report["entries"] = report.get("entries", 0) + 1
            pos += (len(raw) + 1 + 3) & ~3
    # confere: cada texto do bloco e' achado pelos ponteiros
    for p in m["pools"]:
        for k in p["keys"]:
            x = by_k[k]
            for po in x["ptrs"]:
                a = struct.unpack_from(">I", out, po)[0]
                o = _off(secs, a)
                if o is None or not (p["start"] <= o < p["end"]):
                    raise SistemaError("conferencia do main.dol falhou (ponteiro fora do bloco)")
    return bytes(out)


def _sections(d: bytes):
    offs = struct.unpack_from(">18I", d, 0)
    addr = struct.unpack_from(">18I", d, 0x48)
    size = struct.unpack_from(">18I", d, 0x90)
    return [(offs[i], addr[i], size[i]) for i in range(18) if size[i]]


def _addr(secs, o: int) -> int:
    for fo, a, s in secs:
        if fo <= o < fo + s:
            return a + o - fo
    raise SistemaError("posicao fora das secoes do main.dol")


def _off(secs, a: int) -> Optional[int]:
    for fo, ad, s in secs:
        if ad <= a < ad + s:
            return fo + a - ad
    return None
