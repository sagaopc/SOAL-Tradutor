"""Suporte ao port nativo "Skies of Arcadia Legends: Recompiled" (ogdanimal).

O launcher do port extrai o disco do jogador para

    <pasta de dados>/games/GEAE8P/sys   e   .../files

e o jogo le os arquivos de files/ direto dali, sem conferir o conteudo. Por isso
a traducao entra gravando os .sct e a fonte nessa pasta, igual a uma extracao
do Dolphin.

O port guarda os save states de um jogo modificado numa pasta propria
(StateSaves/romhack-<etiqueta>). A etiqueta e' calculada com os dados do
main.dol e com o sys/fst.bin, a tabela de arquivos do disco. Um save state
guarda essa tabela na memoria, com o tamanho de cada arquivo; se ele for
carregado depois que os .sct mudaram de tamanho, o jogo le os arquivos com os
tamanhos antigos. Para que isso nao aconteca, depois de gravar a traducao o
fst.bin e' atualizado com os tamanhos novos: a etiqueta muda e o port passa a
usar outra pasta de states. O fst.bin nao e' lido para rodar o jogo (a tabela
usada e' montada a partir da pasta files/), entao essa mudanca so' afeta a
etiqueta.
"""

from __future__ import annotations

import os
import struct
import sys
from typing import Dict, List, Optional, Tuple

DATA_NAME = "Skies of Arcadia Legends"
SUPPORTED_ID = "GEAE8P"
SUPPORTED_IDS = ("GEAE8P", "GEAP8P")
# idioma do console (GameCube) no Dolphin.ini do port: o jogo europeu mostra o idioma do console
GC_LANG = {"en": 0, "de": 1, "fr": 2, "es": 3}
GC_LANG_NAMES = {0: "inglês", 1: "alemão", 2: "francês", 3: "espanhol", 4: "italiano", 5: "holandês"}
REGION_NAMES = {"GEAE8P": "americana", "GEAP8P": "europeia", "GEAJ8P": "japonesa"}
BLOCK = 0x8000      # o port alinha cada arquivo do disco em blocos de 32 KB


def game_id(root: str) -> Optional[str]:
    """Codigo do disco (GEAE8P...) lido de sys/boot.bin, ou None se nao houver."""
    for p in (os.path.join(root, "sys", "boot.bin"), os.path.join(root, "&&systemdata", "ISO.hdr")):
        try:
            with open(p, "rb") as fh:
                raw = fh.read(6)
            if len(raw) == 6 and raw.isalnum():
                return raw.decode("ascii")
        except OSError:
            continue
    return None


def is_recomp_game(root: str) -> bool:
    """A pasta e' um jogo importado pelo port? (fica em <dados>/games/<ID>)"""
    root = os.path.abspath(root)
    parent = os.path.dirname(root)
    if os.path.basename(parent).lower() != "games":
        return False
    data = os.path.dirname(parent)
    return (os.path.isdir(os.path.join(data, "StateSaves")) or os.path.isdir(os.path.join(data, "Config"))
            or os.path.exists(os.path.join(data, "default-game.txt")))


def _default_data_dirs() -> List[str]:
    out = []
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        out.append(os.path.join(base, DATA_NAME))
    elif sys.platform == "darwin":
        out.append(os.path.join(home, "Library", "Application Support", DATA_NAME))
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg and os.path.isabs(xdg):
            out.append(os.path.join(xdg, DATA_NAME))
        out.append(os.path.join(home, ".local", "share", DATA_NAME))
    return out


def _game_in(data_dir: str) -> Optional[str]:
    """Jogo importado dentro de uma pasta de dados do port."""
    cands = []
    try:
        with open(os.path.join(data_dir, "default-game.txt"), encoding="utf-8") as fh:
            line = fh.readline().strip()
        if line:
            cands.append(line if os.path.isabs(line) else os.path.join(data_dir, line))
            cands.append(os.path.join(data_dir, "games", os.path.basename(line.rstrip("\\/"))))
    except OSError:
        pass
    for gid in SUPPORTED_IDS:
        cands.append(os.path.join(data_dir, "games", gid))
    for c in cands:
        if os.path.isdir(os.path.join(c, "files", "field")):
            return os.path.abspath(c)
    return None


def find_install(hint: Optional[str] = None) -> Optional[dict]:
    """Procura o jogo importado pelo port. hint: pasta de dados, pasta do port ou do jogo."""
    dirs: List[str] = []
    if hint:
        hint = os.path.abspath(hint)
        dirs += [hint, os.path.join(hint, "User"), os.path.join(hint, DATA_NAME)]
        if os.path.isdir(os.path.join(hint, "files", "field")) and is_recomp_game(hint):
            return _describe(hint)
    for d in _default_data_dirs():
        dirs.append(d)
        # o jogador pode ter mudado a pasta de dados de lugar: o padrao guarda um ponteiro
        try:
            with open(os.path.join(d, "data-folder.txt"), encoding="utf-8") as fh:
                moved = fh.readline().strip()
            if moved and os.path.isabs(moved):
                dirs.insert(len(dirs) - 1, moved)
        except OSError:
            pass
    for d in dirs:
        if not os.path.isdir(d):
            continue
        g = _game_in(d)
        if g:
            return _describe(g)
    return None


def find_region(gid: str, hint: Optional[str] = None) -> Optional[dict]:
    """O jogo de um disco (GEAE8P ou GEAP8P) importado no port, mesmo que nao seja o padrao."""
    first = find_install(hint)
    if first and first.get("id") == gid:
        return first
    if first:
        g = os.path.join(first["data_dir"], "games", gid)
        if os.path.isdir(os.path.join(g, "files", "field")) and game_id(g) == gid:
            return _describe(os.path.abspath(g))
    return None


def _ini_path(data_dir: str) -> str:
    return os.path.join(data_dir, "Config", "Dolphin.ini")


def gc_language(data_dir: str) -> int:
    """Idioma do console configurado no port (0 = ingles, o padrao)."""
    try:
        with open(_ini_path(data_dir), encoding="utf-8", errors="replace") as fh:
            sec = ""
            for line in fh:
                t = line.strip()
                if t.startswith("[") and t.endswith("]"):
                    sec = t[1:-1].strip().lower()
                elif sec == "core" and "=" in t and t.split("=", 1)[0].strip().lower() == "selectedlanguage":
                    return int(t.split("=", 1)[1].strip() or 0)
    except (OSError, ValueError):
        pass
    return 0


def set_gc_language(data_dir: str, value: int) -> bool:
    """Grava [Core] SelectedLanguage no Dolphin.ini do port. Devolve True se mudou."""
    if gc_language(data_dir) == value:
        return False
    path = _ini_path(data_dir)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    out, sec, done, core_at = [], "", False, None
    for line in lines:
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            if sec == "core" and not done:
                out.append("SelectedLanguage = %d" % value)
                done = True
            sec = t[1:-1].strip().lower()
            if sec == "core":
                core_at = len(out)
        elif sec == "core" and "=" in t and t.split("=", 1)[0].strip().lower() == "selectedlanguage":
            out.append("SelectedLanguage = %d" % value)
            done = True
            continue
        out.append(line)
    if not done:
        if sec == "core":
            out.append("SelectedLanguage = %d" % value)
        elif core_at is None:
            out += ["[Core]", "SelectedLanguage = %d" % value]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    return True


def _describe(game_root: str) -> dict:
    gid = game_id(game_root)
    data_dir = os.path.dirname(os.path.dirname(game_root))
    return {"game_root": game_root, "data_dir": data_dir, "id": gid,
            "supported": gid in SUPPORTED_IDS, "region": REGION_NAMES.get(gid or "", "desconhecida"),
            "states": count_states(data_dir)}


def count_states(data_dir: str) -> int:
    """Quantos save states existem na pasta do port (todas as subpastas)."""
    n = 0
    base = os.path.join(data_dir, "StateSaves")
    for _, _, files in os.walk(base):
        n += sum(1 for f in files if f.lower().endswith(".sav"))
    return n


# --------------------------------------------------------------------- fst.bin
class FstError(Exception):
    pass


class Fst:
    """Tabela de arquivos de um disco de GameCube (sys/fst.bin)."""

    def __init__(self, data: bytes):
        if len(data) < 12:
            raise FstError("fst.bin pequeno demais")
        self.data = bytearray(data)
        count = struct.unpack_from(">I", data, 8)[0]
        if count < 1 or 12 * count > len(data) or data[0] != 1:
            raise FstError("fst.bin invalido")
        names = 12 * count
        self.files: Dict[str, int] = {}       # caminho em minusculas -> indice da entrada
        dirs: List[Tuple[int, str]] = [(count, "")]
        for i in range(1, count):
            while len(dirs) > 1 and i >= dirs[-1][0]:
                dirs.pop()
            w0, _a, b = struct.unpack_from(">III", data, 12 * i)
            off = names + (w0 & 0xFFFFFF)
            end = data.find(b"\0", off)
            if off >= len(data) or end < 0:
                raise FstError("nome de arquivo fora do fst.bin")
            name = data[off:end].decode("latin-1")
            if w0 >> 24:
                if not (i < b <= count):
                    raise FstError("pasta com limites invalidos no fst.bin")
                dirs.append((b, dirs[-1][1] + name + "/"))
            else:
                self.files[(dirs[-1][1] + name).lower()] = i

    def size(self, path: str) -> Optional[int]:
        i = self.files.get(path.lower().replace("\\", "/"))
        return None if i is None else struct.unpack_from(">I", self.data, 12 * i + 8)[0]

    def set_size(self, path: str, size: int) -> bool:
        i = self.files.get(path.lower().replace("\\", "/"))
        if i is None:
            return False
        struct.pack_into(">I", self.data, 12 * i + 8, size)
        return True

    def build(self) -> bytes:
        return bytes(self.data)


def pad_to_block(data: bytes) -> bytes:
    """Completa com zeros ate' um multiplo de 32 KB (tamanho estavel entre gravacoes)."""
    return data + b"\0" * (-len(data) % BLOCK)
