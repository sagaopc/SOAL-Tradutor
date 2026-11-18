"""Sons do jogo para a dublagem: inventario da pasta sound/, extracao para WAV organizada por
personagem e reconhecimento dos WAV dublados que voltam (pelo nome, em qualquer pasta).

Dois tipos de som:
  - fluxo: <base>_l.dsp + <base>_r.dsp (um arquivo por canal). Vira <base>.wav estereo.
    Chave: "<base>" (ex.: "141", "ko0000").
  - amostra de banco: os bancos MusyX (<base>.info + <base>.samp) guardam amostras com um id
    que vale para o jogo inteiro: o mesmo id e' o mesmo som em todos os bancos que o usam (as
    falas de batalha da Aika, por exemplo, estao repetidas em 72 bancos). Cada id vira um WAV
    so', <id>.wav, e a dublagem dele vai para todos os bancos.
    Chave: "#<id em hex>" (ex.: "#0e5f").

A pasta onde o WAV esta' nao importa na volta: so' o nome. Assim da' para reorganizar.
"""
import csv
import hashlib
import os
import re
import struct
from typing import Callable, Dict, List, Optional, Tuple

from . import audio

# o que extrair (primeira pasta da organizacao)
GROUPS = {
    "personagens": "Falas dos personagens (vitória e batalha)",
    "tripulacao": "Tripulação (sons de cada tripulante e das batalhas de navio)",
    "cenas": "Sons das cenas (vozes curtas e efeitos)",
    "batalha": "Outros sons de batalha",
    "campo": "Sons do campo e do navio",
    "musica": "Música",
    "outros": "Outros",
}
FOLDER_GROUP = {"Personagens": "personagens", "Tripulacao": "tripulacao", "Cenas": "cenas",
                "Batalha": "batalha", "Campo": "campo", "Musica": "musica", "Outros": "outros"}

# Personagens: as falas de vitoria (com a fanfarra) sao o fluxo <n>xx (n = 1..6) e as de batalha
# sao amostras dos bancos stv. Os grupos de ids foram achados pela distribuicao nos 72 bancos
# stv (Vyse, Aika e Fina estao em todos; Drachma, Enrique e Gilder se revezam no 4o lugar) e
# conferidos pela voz (tom e timbre comparados com as falas de vitoria de cada um).
CHARS = ["Vyse", "Aika", "Fina", "Drachma", "Enrique", "Gilder"]
BATTLE_IDS = {
    "Vyse": range(0xEB1, 0xEBD),
    "Aika": range(0xE5F, 0xE6C),
    "Fina": range(0xE86, 0xE90),
    "Drachma": range(0xE6F, 0xE7A),
    "Enrique": range(0xE7A, 0xE86),
    "Gilder": range(0xE96, 0xEA1),
}
_ID_CHAR = {i: name for name, ids in BATTLE_IDS.items() for i in ids}


def stream_char(base: str) -> Optional[str]:
    m = re.match(r"^([1-6])\d\d$", base)
    return CHARS[int(m.group(1)) - 1] if m else None


def sound_dir(files_dir: str) -> Optional[str]:
    for n in os.listdir(files_dir) if os.path.isdir(files_dir) else ():
        if n.lower() == "sound" and os.path.isdir(os.path.join(files_dir, n)):
            return os.path.join(files_dir, n)
    return None


def _sdir_ids(info: bytes) -> List[Tuple[int, int, int]]:
    """(id, taxa, amostras) de cada amostra da tabela de um .info, sem ler o .samp."""
    b = audio.Bank.__new__(audio.Bank)
    b.info = bytearray(info)
    st = b._find_sdir()
    if st is None:
        return []
    out = []
    o = st
    while info[o:o + 4] != b"\xff\xff\xff\xff" and o + 0x20 <= len(info):
        sid, _, _, _, _, _, rate, ns = struct.unpack(">HHIIBBHI", info[o:o + 0x14])
        if ns >> 24 == 0:
            out.append((sid, rate, ns & 0xFFFFFF))
        o += 0x20
    return out


class Inventory:
    """O que ha' na pasta sound/: fluxos (base -> {canal: arquivo}), bancos (base -> (.info,
    .samp)) e, para cada id de amostra, os bancos que o usam."""

    def __init__(self, sdir: str, read: Optional[Callable[[str], bytes]] = None):
        self.dir = sdir
        self.read = read or (lambda n: open(os.path.join(sdir, n), "rb").read())
        self.streams: Dict[str, Dict[str, str]] = {}
        self.banks: Dict[str, Tuple[str, str]] = {}
        names = sorted(os.listdir(sdir))
        low = {n.lower(): n for n in names}
        for n in names:
            m = re.match(r"^(.+)_([lr])\.dsp$", n, re.I)
            if m:
                self.streams.setdefault(m.group(1).lower(), {})[m.group(2).lower()] = n
                continue
            m = re.match(r"^(.+)\.info$", n, re.I)
            if m and (m.group(1).lower() + ".samp") in low:
                self.banks[m.group(1).lower()] = (n, low[m.group(1).lower() + ".samp"])
        self._ids: Optional[Dict[int, List[str]]] = None
        self.meta: Dict[int, Tuple[int, int]] = {}

    @property
    def ids(self) -> Dict[int, List[str]]:
        """id -> bancos que o usam (em ordem alfabetica)."""
        if self._ids is None:
            ids: Dict[int, List[str]] = {}
            for b in sorted(self.banks):
                try:
                    lst = _sdir_ids(self.read(self.banks[b][0]))
                except (OSError, struct.error):
                    continue
                for sid, rate, ns in lst:
                    ids.setdefault(sid, []).append(b)
                    self.meta.setdefault(sid, (rate, ns))
            self._ids = ids
        return self._ids

    def key_files(self, key: str) -> List[str]:
        if key.startswith("#"):
            out = []
            for b in self.ids.get(int(key[1:], 16), []):
                out += list(self.banks[b])
            return out
        return sorted((self.streams.get(key) or {}).values())

    # ---------------------------------------------------------------- organizacao
    def place(self, key: str) -> str:
        """Caminho (com /) do WAV de um som na extracao."""
        if not key.startswith("#"):
            b = key
            ch = stream_char(b)
            if ch:
                return f"Personagens/{ch}/vitoria/{b}.wav"
            if b.startswith("ko"):
                return f"Cenas/efeitos/{b}.wav"
            top = {"b": "Batalha", "f": "Campo", "m": "Musica"}.get(b[:1], "Outros")
            return f"{top}/{b}.wav"
        sid = int(key[1:], 16)
        name = f"{sid:04x}.wav"
        if sid in _ID_CHAR:
            return f"Personagens/{_ID_CHAR[sid]}/batalha/{name}"
        banks = self.ids.get(sid, [])
        first = banks[0] if banks else "?"
        if first.startswith("stv"):
            return f"Personagens/Outras vozes de batalha/{name}"
        if first.startswith("cr"):
            n_cr = sum(1 for b in self.banks if b.startswith("cr"))
            if len(banks) > max(3, n_cr // 2):
                return f"Tripulacao/comum/{name}"
            return f"Tripulacao/{first}/{name}"
        if first.startswith("e6"):
            return f"Cenas/{first}/{name}"
        if first.startswith("b"):
            return f"Batalha/{first}/{name}"
        if first.startswith("f"):
            return f"Campo/{first}/{name}"
        if first.startswith("m") or first == "tone":
            return f"Musica/instrumentos/{first}/{name}"
        return f"Outros/{first}/{name}"

    def keys(self) -> List[str]:
        return sorted(self.streams) + [f"#{i:04x}" for i in sorted(self.ids)]

    def describe(self, key: str) -> str:
        """Onde o som fica, em poucas palavras (para a lista da janela)."""
        p = self.place(key).split("/")
        return " › ".join(x for x in p[:-1] if x)


def group_of(path: str) -> str:
    return FOLDER_GROUP.get(path.split("/")[0], "outros")


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stream_channels(inv: Inventory, base: str) -> Tuple[int, List]:
    chans = inv.streams[base]
    out = []
    rate = 0
    for c in ("l", "r"):
        if c in chans:
            s = audio.DspStream(inv.read(chans[c]))
            rate = s.rate
            out.append(s.pcm())
    return rate, out


class BankCache:
    """Bancos abertos (o .samp so' e' lido quando preciso)."""

    def __init__(self, inv: Inventory, keep: int = 6):
        self.inv = inv
        self.keep = keep
        self.open: Dict[str, audio.Bank] = {}

    def get(self, b: str) -> audio.Bank:
        bk = self.open.get(b)
        if bk is None:
            if len(self.open) >= self.keep:
                self.open.pop(next(iter(self.open)))
            fi, fs = self.inv.banks[b]
            bk = self.open[b] = audio.Bank(self.inv.read(fi), self.inv.read(fs))
        return bk

    def sample(self, sid: int) -> Tuple[audio.Bank, "audio.Sample"]:
        for b in self.inv.ids.get(sid, []):
            bk = self.get(b)
            for s in bk.samples:
                if s.id == sid and s.fmt == 0:
                    return bk, s
        raise KeyError(f"som {sid:04x} não encontrado")

    def pcm(self, key: str) -> Tuple[int, List]:
        if key.startswith("#"):
            bk, s = self.sample(int(key[1:], 16))
            return s.rate, [bk.pcm(s)]
        return stream_channels(self.inv, key)


def extract(inv: Inventory, out_dir: str, groups: List[str], progress=None, cancel=lambda: False,
            portraits: Optional[Callable[[str], Optional[bytes]]] = None) -> dict:
    """Extrai os sons para WAV, organizados por personagem. inv.read devolve os arquivos
    ORIGINAIS (o projeto guarda os originais dos sons ja' dublados). portraits(crNNN) devolve
    a imagem do tripulante (ou None)."""
    keys = [k for k in inv.keys() if group_of(inv.place(k)) in groups]
    # amostras na ordem dos bancos: abre cada banco uma vez
    def bank_order(k):
        if not k.startswith("#"):
            return ("", k)
        b = inv.ids.get(int(k[1:], 16), ["~"])
        return (b[0], k)
    keys.sort(key=bank_order)
    os.makedirs(out_dir, exist_ok=True)
    rep = {"pasta": os.path.abspath(out_dir), "falas": 0, "segundos": 0.0, "erros": [], "cancelado": False,
           "por_grupo": {}, "repetidos": 0}
    rows = []
    cache = BankCache(inv)
    for i, key in enumerate(keys):
        if cancel():
            rep["cancelado"] = True
            break
        rel = inv.place(key)
        if progress and i % 10 == 0:
            progress(i, len(keys), rel)
        try:
            rate, chans = cache.pcm(key)
            if not chans or not max(len(c) for c in chans):
                continue
            path = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            audio.write_wav(path, rate, chans)
            secs = max(len(c) for c in chans) / rate
            if key.startswith("#"):
                banks = inv.ids.get(int(key[1:], 16), [])
                rep["repetidos"] += max(0, len(banks) - 1)
                origem = ", ".join(banks[:4]) + (f" e mais {len(banks) - 4}" if len(banks) > 4 else "")
                tipo = f"banco ({len(banks)})"
            else:
                origem = ", ".join(sorted(inv.streams[key].values()))
                tipo = "fluxo"
            rows.append([rel, key, origem, tipo, rate, len(chans), f"{secs:.2f}", _sha1(path)])
            rep["falas"] += 1
            rep["segundos"] += secs
            g = group_of(rel)
            rep["por_grupo"][g] = rep["por_grupo"].get(g, 0) + 1
        except (ValueError, OSError, IndexError, KeyError) as exc:
            rep["erros"].append(f"{key}: {exc}")
    # quem e' cada tripulante
    if portraits and "tripulacao" in groups and not rep["cancelado"]:
        for b in sorted(inv.banks):
            if not re.match(r"^cr\d{3}$", b):
                continue
            d = os.path.join(out_dir, "Tripulacao", b)
            if not os.path.isdir(d):
                continue
            try:
                png = portraits(b)
            except Exception:  # noqa: o retrato e' so' uma ajuda
                png = None
            if png:
                with open(os.path.join(d, "aparencia.png"), "wb") as fh:
                    fh.write(png)
    # o indice serve para a volta: os WAV que nao mudaram sao pulados
    idx = os.path.join(out_dir, "indice_audio.csv")
    old = {r[0]: r for r in read_index(out_dir).values()} if os.path.exists(idx) else {}
    for r in rows:
        old[r[0]] = r
    with open(idx, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["arquivo", "chave", "origem no jogo", "tipo", "taxa (Hz)", "canais", "segundos", "sha1"])
        for k in sorted(old):
            w.writerow(old[k])
    with open(os.path.join(out_dir, "LEIA-ME.txt"), "w", encoding="utf-8") as fh:
        fh.write(README)
    rep["segundos"] = round(rep["segundos"])
    if progress:
        progress(len(keys), len(keys), "")
    return rep


def read_index(root: str) -> Dict[str, list]:
    """caminho relativo (com /) -> linha do indice_audio.csv (formato novo: 8 colunas com a
    chave na 2a; o antigo, da 0.13.0, tinha o sha1 na 8a e nao tinha chave)."""
    out = {}
    try:
        with open(os.path.join(root, "indice_audio.csv"), encoding="utf-8-sig", newline="") as fh:
            r = csv.reader(fh, delimiter=";")
            head = next(r, None) or []
            new = len(head) > 1 and head[1] == "chave"
            for row in r:
                if len(row) >= 8:
                    if not new:
                        row = [row[0], "", row[1], row[2], row[4], row[5], row[6], row[7]]
                    out[row[0]] = row
    except OSError:
        pass
    return out


def key_for(inv: Inventory, rel: str) -> Optional[str]:
    """Chave do som de um WAV pelo nome. Aceita texto depois do nome ("0e5f - grito.wav")."""
    parts = rel.replace("\\", "/").split("/")
    stem = parts[-1].rsplit(".", 1)[0].lower().strip()
    first = re.split(r"[\s(\[]| - ", stem, 1)[0].strip(" -_")
    for s in (stem, first):
        if s in inv.streams:
            return s
        m = re.match(r"^(?:\d{3}_)?([0-9a-f]{4})$", s)
        if m and int(m.group(1), 16) in inv.ids:
            return "#" + m.group(1)
    return None


def find_wavs(src: str) -> List[str]:
    out = []
    for dp, dn, fn in os.walk(src):
        dn[:] = [d for d in dn if not d.startswith(".")]
        for f in fn:
            if f.lower().endswith(".wav"):
                out.append(os.path.relpath(os.path.join(dp, f), src).replace("\\", "/"))
    return sorted(out)


README = """SONS DE SKIES OF ARCADIA LEGENDS, extraídos pelo SOAL Tradutor
===============================================================

Cada som do jogo virou um arquivo WAV (PCM 16 bits), com a mesma taxa do jogo.

Personagens/<nome>/vitoria    falas de vitória, com a fanfarra (estéreo)
Personagens/<nome>/batalha    falas de batalha: gritos de ataque e de dano e nomes dos golpes
                              especiais, misturados
Personagens/Outras vozes de batalha   falas de batalha de chefes e convidados
Tripulacao/crNNN              sons de cada tripulante (aparencia.png mostra quem é)
Tripulacao/comum              sons das batalhas de navio (comandos, canhões...)
Cenas/<cena>                  sons de cada cena: vozes curtas e efeitos misturados
Cenas/efeitos                 efeitos longos das cenas
Batalha, Campo, Musica, Outros

Cada som aparece uma vez só, mesmo que o jogo use em vários lugares: as falas de batalha
da Aika, por exemplo, estão em 72 arquivos do jogo; dublando o WAV dela, o programa troca
nos 72.

O NOME DO ARQUIVO É O QUE LIGA O WAV AO JOGO (141.wav, ko0000.wav, 0e5f.wav). A pasta não
importa: pode mover os arquivos, criar pastas, separar como quiser. Também pode pôr texto
depois do nome, com espaço: "0e5f - Aika grito.wav".

DUBLAGEM
  1. Grave a fala nova e salve por cima do WAV (ou em outra pasta, com o mesmo nome).
     Qualquer taxa, mono ou estéreo: o programa converte para a do jogo. WAV PCM.
  2. Tente manter a duração parecida com a original.
  3. No SOAL Tradutor: Dublagem > Importar. Os WAV que você não mudou são pulados (o
     indice_audio.csv guarda a impressão digital de cada original).
  4. Gravar no jogo grava os sons dublados nos arquivos originais do jogo, cada um no seu
     lugar, junto com a tradução. Restaurar os originais devolve os sons originais.

indice_audio.csv: chave de cada WAV, de que arquivos do jogo vem, taxa, canais e duração.
"""
