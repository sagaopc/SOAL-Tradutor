"""Sons do jogo para a dublagem: inventario da pasta sound/, extracao para WAV e
reconhecimento dos WAV dublados que voltam.

Dois tipos de som:
  - fluxo: <base>_l.dsp + <base>_r.dsp (um arquivo por canal). Vira <base>.wav estereo.
  - banco: <base>.info + <base>.samp (MusyX). Cada amostra vira <base>/<nnn>_<id>.wav.

Chave de cada som (usada no projeto e na volta dos WAV):
  fluxo  -> "<base>"           ex.: "ko0000"
  banco  -> "<base>/<id hex>"  ex.: "stv00/0e5f"
"""
import csv
import hashlib
import os
import re
from typing import Callable, Dict, List, Optional, Tuple

from . import audio

# grupos (para escolher o que extrair) e a pasta de cada tipo de arquivo
GROUPS = {
    "vozes": "Vozes (falas de golpes, de eventos e de batalha)",
    "eventos": "Sons dos eventos (vozes curtas e efeitos)",
    "batalha": "Sons de batalha (personagens, inimigos e efeitos)",
    "campo": "Sons do campo e do navio",
    "musica": "Música",
    "outros": "Outros",
}


def classify(base: str, kind: str) -> Tuple[str, str]:
    """(grupo, pasta) de um som pelo nome do arquivo."""
    b = base.lower()
    if b[:1].isdigit():
        return "vozes", "vozes/golpes"
    if b.startswith("ko"):
        return "vozes", "vozes/eventos"
    if b.startswith("stv"):
        return "vozes", "vozes/batalha"
    if b.startswith("e6"):
        return "eventos", "eventos"
    if b.startswith("cr"):
        return "batalha", "batalha/personagens"
    if b.startswith("b"):
        return "batalha", "batalha/efeitos"
    if b.startswith("f"):
        return "campo", "campo"
    if b.startswith("m") or b == "tone":
        return "musica", "musica" if kind == "stream" else "musica/instrumentos"
    return "outros", "outros"


def sound_dir(files_dir: str) -> Optional[str]:
    for n in os.listdir(files_dir) if os.path.isdir(files_dir) else ():
        if n.lower() == "sound" and os.path.isdir(os.path.join(files_dir, n)):
            return os.path.join(files_dir, n)
    return None


class Inventory:
    """O que ha' na pasta sound/: fluxos (base -> {canal: nome do arquivo}) e bancos
    (base -> (nome do .info, nome do .samp))."""

    def __init__(self, sdir: str):
        self.dir = sdir
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

    def game_files(self, key: str) -> List[str]:
        """Arquivos do jogo que um som (chave) usa."""
        if "/" in key:
            b = self.banks.get(key.split("/")[0])
            return list(b) if b else []
        return sorted((self.streams.get(key) or {}).values())


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stream_channels(inv: Inventory, base: str, read: Callable[[str], bytes]) -> Tuple[int, List]:
    chans = inv.streams[base]
    out = []
    rate = 0
    for c in ("l", "r"):
        if c in chans:
            s = audio.DspStream(read(chans[c]))
            rate = s.rate
            out.append(s.pcm())
    return rate, out


def extract(files_dir: str, out_dir: str, groups: List[str], read: Callable[[str], bytes],
            progress=None, cancel=lambda: False) -> dict:
    """Extrai os sons para WAV. read(nome) devolve o arquivo ORIGINAL da pasta sound/ (o
    projeto guarda os originais dos sons ja' dublados)."""
    sdir = sound_dir(files_dir)
    if not sdir:
        raise ValueError("Não achei a pasta sound do jogo.")
    inv = Inventory(sdir)
    units = [("stream", b) for b in sorted(inv.streams)] + [("bank", b) for b in sorted(inv.banks)]
    units = [(k, b) for k, b in units if classify(b, k)[0] in groups]
    os.makedirs(out_dir, exist_ok=True)
    rep = {"pasta": os.path.abspath(out_dir), "arquivos": 0, "falas": 0, "segundos": 0.0, "erros": [],
           "cancelado": False, "por_grupo": {}}
    rows = []
    for i, (kind, base) in enumerate(units):
        if cancel():
            rep["cancelado"] = True
            break
        grp, folder = classify(base, kind)
        if progress:
            progress(i, len(units), base)
        try:
            if kind == "stream":
                rate, chans = stream_channels(inv, base, read)
                rel = f"{folder}/{base}.wav"
                path = os.path.join(out_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                audio.write_wav(path, rate, chans)
                secs = max(len(c) for c in chans) / rate
                rows.append([rel, ", ".join(sorted(inv.streams[base].values())), "fluxo", "", rate, len(chans),
                             f"{secs:.2f}", _sha1(path)])
                rep["falas"] += 1
                rep["segundos"] += secs
                rep["por_grupo"][grp] = rep["por_grupo"].get(grp, 0) + 1
            else:
                fi, fs = inv.banks[base]
                bank = audio.Bank(read(fi), read(fs))
                for s in bank.samples:
                    pcm = bank.pcm(s)
                    if pcm is None or not len(pcm):
                        continue
                    rel = f"{folder}/{base}/{s.index:03d}_{s.id:04x}.wav"
                    path = os.path.join(out_dir, *rel.split("/"))
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    audio.write_wav(path, s.rate, [pcm])
                    secs = len(pcm) / s.rate
                    rows.append([rel, f"{fi}, {fs}", "banco", f"{s.id:04x}", s.rate, 1, f"{secs:.2f}", _sha1(path)])
                    rep["falas"] += 1
                    rep["segundos"] += secs
                    rep["por_grupo"][grp] = rep["por_grupo"].get(grp, 0) + 1
            rep["arquivos"] += 1
        except (ValueError, OSError, IndexError) as exc:
            rep["erros"].append(f"{base}: {exc}")
    # o indice serve para a volta: os WAV que nao mudaram sao pulados
    old = {}
    idx = os.path.join(out_dir, "indice_audio.csv")
    if os.path.exists(idx):
        for r in read_index(out_dir).values():
            old[r[0]] = r
    for r in rows:
        old[r[0]] = r
    with open(idx, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["arquivo", "origem no jogo", "tipo", "id", "taxa (Hz)", "canais", "segundos", "sha1"])
        for k in sorted(old):
            w.writerow(old[k])
    with open(os.path.join(out_dir, "LEIA-ME.txt"), "w", encoding="utf-8") as fh:
        fh.write(README)
    rep["segundos"] = round(rep["segundos"])
    if progress:
        progress(len(units), len(units), "")
    return rep


def read_index(root: str) -> Dict[str, list]:
    """caminho relativo (com /) -> linha do indice_audio.csv."""
    out = {}
    try:
        with open(os.path.join(root, "indice_audio.csv"), encoding="utf-8-sig", newline="") as fh:
            r = csv.reader(fh, delimiter=";")
            next(r, None)
            for row in r:
                if len(row) >= 8:
                    out[row[0]] = row
    except OSError:
        pass
    return out


def key_for(inv: Inventory, rel: str) -> Optional[str]:
    """Chave do som de um WAV pelo nome (e pela pasta, para os bancos)."""
    parts = rel.replace("\\", "/").split("/")
    stem = parts[-1].rsplit(".", 1)[0].lower().strip()
    if stem in inv.streams:
        return stem
    if len(parts) >= 2:
        bank = parts[-2].lower()
        m = re.match(r"^(?:\d+_)?([0-9a-f]{4})$", stem)
        if bank in inv.banks and m:
            return f"{bank}/{m.group(1)}"
    return None


def find_wavs(src: str) -> List[str]:
    """WAV dentro de src (caminhos relativos com /)."""
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

Pastas
  vozes/golpes       falas dos golpes especiais dos personagens (estéreo)
  vozes/eventos      falas das cenas (estéreo)
  vozes/batalha      falas curtas de batalha (uma pasta por grupo de sons)
  eventos            sons de cada cena: vozes curtas e efeitos misturados
  batalha            personagens e inimigos (vozes e efeitos) e efeitos de batalha
  campo, musica, outros

Nos bancos (pastas com vários WAV numerados), o nome é <ordem>_<id>.wav: o id liga o WAV ao
som do jogo. Não mude os nomes nem as pastas.

DUBLAGEM
  1. Grave a fala nova e salve por cima do WAV (ou numa cópia da pasta, com o mesmo nome e a
     mesma pasta). Qualquer taxa e mono ou estéreo: o programa converte para a do jogo.
     Use WAV PCM (16 bits é o mais comum).
  2. Tente manter a duração parecida com a original. Fala bem mais longa pode ser cortada
     pela cena ou atrasar a próxima; nos bancos, sons maiores ocupam mais memória do console.
  3. No SOAL Tradutor: Dublagem > Importar. Os WAV que você não mudou são pulados (o
     indice_audio.csv guarda a impressão digital de cada original).
  4. Gravar no jogo grava os sons dublados junto com a tradução. Restaurar os originais
     devolve os sons originais também.

indice_audio.csv: de que arquivo do jogo vem cada WAV, taxa, canais e duração.
"""
