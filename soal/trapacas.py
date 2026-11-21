"""Trapacas para testar a traducao no recomp de ogdanimal: viajar para qualquer mapa, ganhar todos os
itens, magias e Super Movimentos, status maximos e invencibilidade.

Como funciona
    O recomp (skies-run) tem um modo de automacao, usado pelo autor nos testes (tools/drive.py do
    repositorio dele): aberto com --automation-dir PASTA, ele le arquivos de comando em
    PASTA/commands/ (um comando por arquivo, chave=valor), executa em ordem de nome e conta o que fez em
    PASTA/status.txt. Os comandos usados aqui: write_memory (address, data em hex), read_memory
    (address, size, path) e set_config (system, section, key, value). O codigo do jogo esta' compilado
    dentro do recomp, entao codigos Action Replay que mexem em codigo nao funcionam; os dados (status,
    itens, variaveis da historia) ficam na memoria e podem ser trocados.

Enderecos (versao americana; a europeia soma 0x3680 nos dados do save)
    lbl_8030B7F4   registros do grupo, 0x5C bytes cada (Vyse, Aika, Fina, Drachma, Enrique, Gilder);
                   o save do cartao guarda a mesma regiao (payload em +0x1440 do arquivo = registro - 0x10)
    +0x34C         ouro (u32)
    +0x354 ...     estoque: entradas de 4 bytes (id u16, quantidade u8, 0xFF); id -1 = vazio.
                   Armas 80, armaduras 80, acessorios 80, itens 80, itens especiais 80, itens do navio 30,
                   canhoes 40, pecas do navio 40 (fn_801F1840 da versao europeia)
    lbl_80305CF0   nome do script do proximo mapa ("me002a.sct"); 0xF no estado do campo (0x80311AEC)
                   troca de mapa como fn_80100270 faz (patches/game/shipdebug.c do recomp)
    0x8030E3E4     IntVar (u32 cada), 0x80310A1C ByteVar, 0x80310B3C BitVar (bit N = byte N/8, 1 << N%8)
                   (SALSA, ferramenta de scripts de Jahorta)
"""

from __future__ import annotations

import glob
import os
import struct
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

from . import recomp


class TrapacaError(Exception):
    pass


EU_DELTA = 0x3680
_US = {"save": 0x8030B7F4, "map": 0x80305CF0, "field_state": 0x80311AEC,
       "intvar": 0x8030E3E4, "bytevar": 0x80310A1C, "bitvar": 0x80310B3C}
REGIONS: Dict[str, Dict[str, int]] = {
    "GEAE8P": dict(_US),
    "GEAP8P": {"save": _US["save"] + EU_DELTA, "map": 0x80309370, "field_state": 0x8031517C,
               "intvar": _US["intvar"] + EU_DELTA, "bytevar": _US["bytevar"] + EU_DELTA,
               "bitvar": _US["bitvar"] + EU_DELTA},
}

# ------------------------------------------------------------------ grupo
CHARS = ["Vyse", "Aika", "Fina", "Drachma", "Enrique", "Gilder"]
REC = 0x5C
LEVEL, MP, MP_MAX, HP, HP_MAX, SP, SP_MAX, EXP = 0x0A, 0x0D, 0x0E, 0x18, 0x1A, 0x1C, 0x1E, 0x24
SPELLS = 0x2C            # 8 bytes: magia/Super Mov. N = byte N/8, bit N%8 (MagicDataTable)
RANKS = 0x34             # 6 bytes: nivel de cada Cristal da Lua (verde, vermelho, roxo, azul, amarelo, prata)
STATS = 0x3A             # 5 u16: Poder, Vontade, Vigor, Agilidade, Rapidez
MAGIC_EXP = -0x2C0       # 6 u32 por personagem, 0x78 bytes cada: o que falta para o proximo nivel do cristal
MAGIC_EXP_STRIDE = 0x78
SPELL_COUNT = 36         # 0-35 sao as magias; 36-61 os Super Movimentos
S_MOVES = {              # indices da MagicDataTable (codigos da Codejunkies conferidos com a tabela)
    "Vyse": [36, 37, 38, 50, 51],
    "Aika": [39, 40, 41, 52, 53],
    "Fina": [42, 43, 54, 55, 56],
    "Drachma": [44, 45, 57],
    "Enrique": [46, 47, 58],
    "Gilder": [48, 49, 59],
}
GOLD = 0x34C
GOLD_MAX = 99999999
REPUTATION = 0x349       # byte (Vyse, Rei dos Piratas = 0xFF)

# ------------------------------------------------------------------ estoque
# (chave, rotulo, deslocamento a partir do registro do Vyse, vagas, primeiro id, tabela de nomes, quantidade)
SECTIONS = [
    ("armas", "Armas", 0x354, 80, 0x000, "WeaponDataTable", 99),
    ("armaduras", "Armaduras", 0x494, 80, 0x050, "ArmorDataTable", 99),
    ("acessorios", "Acessórios", 0x5D4, 80, 0x0A0, "AccessDataTable", 99),
    ("itens", "Itens", 0x714, 80, 0x0F0, "IppanItemDataTable", 99),
    ("especiais", "Itens especiais", 0x854, 80, 0x140, "ClearItemDataTable", 1),
    ("navio_itens", "Itens do navio", 0x994, 30, 0x1E0, "ShipItemParamP", 99),
    ("navio_canhoes", "Canhões do navio", 0xA0C, 40, 0x190, "ShipWeaponParamP", 9),
    ("navio_pecas", "Peças do navio", 0xAAC, 40, 0x1B8, "ShipAccessParamP", 9),
]
SECTION = {s[0]: s for s in SECTIONS}
# nomes internos que o jogo nunca entrega (sobras de desenvolvimento)
NEVER = {"GINGESSHO", "SISIKABAB", "CHO SISIKABAB", "SAISYUHEIKI3"}

# BitVar: diario de bordo e descobertas (codigos da Codejunkies: bytes a partir de BitVar)
JOURNAL = [(0x00, 8), (0x0C, 16), (0x20, 20), (0x38, 4), (0x40, 8), (0xD0, 4)]
DISCOVERIES = [(0x168, 16)]


def region(game_id: str) -> Dict[str, int]:
    r = REGIONS.get(game_id)
    if not r:
        raise TrapacaError("As trapaças funcionam com a versão americana (GEAE8P) ou europeia (GEAP8P).")
    return r


def valid_name(name: str) -> bool:
    n = (name or "").strip()
    return bool(n) and n != "-" and not n.upper().startswith("DUMMY") and n not in NEVER


# ------------------------------------------------------------------ montagem dos dados
def section_bytes(entries: List[Tuple[int, int]], slots: int) -> bytes:
    """entries: (id, quantidade). Completa as vagas com -1 (vazio)."""
    if len(entries) > slots:
        raise TrapacaError(f"{len(entries)} itens não cabem em {slots} vagas")
    out = bytearray()
    for i, n in entries:
        out += struct.pack(">HBB", i & 0xFFFF, max(0, min(99, n)), 0xFF)
    out += b"\xff" * (4 * (slots - len(entries)))
    return bytes(out)


def merge_section(current: bytes, add: List[Tuple[int, int]], slots: int) -> bytes:
    """Junta os itens novos aos que o jogador ja' tem, sem mexer na ordem dos que ja' estao la'.
    A quantidade fica a maior das duas."""
    have: List[List[int]] = []
    for k in range(slots):
        i, n, f = struct.unpack_from(">hBB", current, 4 * k)
        if i >= 0 and n > 0:
            have.append([i, n])
    pos = {i: k for k, (i, _) in enumerate(have)}
    for i, n in add:
        if i in pos:
            have[pos[i]][1] = max(have[pos[i]][1], n)
        else:
            pos[i] = len(have)
            have.append([i, n])
    return section_bytes([(i, n) for i, n in have], slots)


def max_record(rec: bytes, char: str, spells: bool = True, stats: bool = True) -> bytes:
    """Registro do personagem com nivel 99, Pv 9999, Pm 99, status 999, todas as magias e os Super
    Movimentos dele e os Cristais da Lua no nivel maximo (como os codigos da Codejunkies)."""
    r = bytearray(rec)
    if stats:
        struct.pack_into(">H", r, LEVEL, 99)
        r[MP] = r[MP_MAX] = 99
        struct.pack_into(">HH", r, HP, 9999, 9999)
        struct.pack_into(">HH", r, SP, 99, 99)
        struct.pack_into(">I", r, EXP, GOLD_MAX)
        struct.pack_into(">5H", r, STATS, 999, 999, 999, 999, 999)
    if spells:
        bits = bytearray(r[SPELLS:SPELLS + 8])
        for n in list(range(SPELL_COUNT)) + S_MOVES.get(char, []):
            bits[n // 8] |= 1 << (n % 8)
        r[SPELLS:SPELLS + 8] = bits
        for k in range(6):
            r[RANKS + k] = 0x64
    return bytes(r)


def warp_bytes(script: str) -> bytes:
    s = (script or "").strip().lower()
    if not s.endswith(".sct"):
        s += ".sct"
    if not (s.startswith("me") and len(s) <= 15 and s[:-4].isalnum()):
        raise TrapacaError("Nome de mapa inválido: " + script)
    return s.encode("ascii") + b"\0"


# ------------------------------------------------------------------ automacao
class Automation:
    """Fala com um skies-run aberto com --automation-dir."""

    def __init__(self, directory: str):
        self.dir = directory
        self._seq = int(time.time() * 1000)

    def status(self) -> Dict[str, str]:
        try:
            with open(os.path.join(self.dir, "status.txt"), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return {}
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def alive(self, max_age: float = 15.0) -> bool:
        try:
            age = time.time() - os.path.getmtime(os.path.join(self.dir, "status.txt"))
        except OSError:
            return False
        return age < max_age and self.status().get("state") not in (None, "", "stopped", "exited")

    def send(self, timeout: float = 10.0, **kv) -> Dict[str, str]:
        cmds = os.path.join(self.dir, "commands")
        os.makedirs(cmds, exist_ok=True)
        before = int(self.status().get("processed_commands", 0) or 0)
        self._seq += 1
        name = f"{self._seq}.txt"
        tmp = os.path.join(self.dir, name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(f"{k}={v}\n" for k, v in kv.items()))
        os.replace(tmp, os.path.join(cmds, name))
        end = time.time() + timeout
        while time.time() < end:
            s = self.status()
            if int(s.get("processed_commands", 0) or 0) > before:
                if s.get("last_error"):
                    raise TrapacaError("O recomp recusou o comando: " + s["last_error"])
                return s
            time.sleep(0.03)
        try:
            os.unlink(os.path.join(cmds, name))
        except OSError:
            pass
        raise TrapacaError("O recomp não respondeu. Ele está aberto pelo botão Abrir o jogo com trapaças?")

    def post(self, **kv):
        """Manda um comando sem esperar resposta (o stop fecha o jogo antes de responder)."""
        cmds = os.path.join(self.dir, "commands")
        os.makedirs(cmds, exist_ok=True)
        self._seq += 1
        tmp = os.path.join(self.dir, f"{self._seq}.txt.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(f"{k}={v}\n" for k, v in kv.items()))
        os.replace(tmp, os.path.join(cmds, f"{self._seq}.txt"))

    def write(self, addr: int, data: bytes):
        for k in range(0, len(data), 0x1000):
            part = data[k:k + 0x1000]
            self.send(command="write_memory", address=f"0x{addr + k:08X}", data=part.hex())

    def read(self, addr: int, size: int) -> bytes:
        out = os.path.join(self.dir, "peek.bin")
        try:
            os.unlink(out)
        except OSError:
            pass
        self.send(command="read_memory", address=f"0x{addr:08X}", size=size, path=os.path.abspath(out))
        last = -1
        for _ in range(100):
            n = os.path.getsize(out) if os.path.exists(out) else -1
            if n >= size and n == last:
                break
            last = n
            time.sleep(0.03)
        with open(out, "rb") as fh:
            data = fh.read()
        if len(data) < size:
            raise TrapacaError("O recomp não devolveu a memória pedida.")
        return data[:size]

    def config(self, system: str, section: str, key: str, value: str):
        self.send(command="set_config", system=system, section=section, key=key, value=value)


# ------------------------------------------------------------------ o jogo aberto
class Session:
    def __init__(self, data_dir: str, game_id: str):
        self.data_dir = data_dir
        self.game_id = game_id
        self.reg = region(game_id)
        self.auto = Automation(os.path.join(data_dir, "SOAL Trapacas"))

    def need(self):
        if not self.auto.alive():
            raise TrapacaError("O jogo não está aberto no modo de trapaças. Clique em Abrir o jogo com trapaças "
                               "(se ele já estiver aberto pelo atalho normal, feche e abra por aqui).")

    # --- grupo
    def party(self) -> List[dict]:
        self.need()
        base = self.reg["save"]
        raw = self.auto.read(base, REC * 6)
        out = []
        for k, name in enumerate(CHARS):
            r = raw[k * REC:(k + 1) * REC]
            out.append({"nome": name, "nivel": struct.unpack_from(">H", r, LEVEL)[0],
                        "pv": struct.unpack_from(">H", r, HP)[0], "pv_max": struct.unpack_from(">H", r, HP_MAX)[0],
                        "pm": r[MP], "pm_max": r[MP_MAX]})
        gold = struct.unpack(">I", self.auto.read(base + GOLD, 4))[0]
        return out + [{"ouro": gold}]

    def max_party(self, who: List[str], spells: bool, stats: bool) -> int:
        self.need()
        base = self.reg["save"]
        raw = bytearray(self.auto.read(base, REC * 6))
        done = 0
        for k, name in enumerate(CHARS):
            if name not in who:
                continue
            raw[k * REC:(k + 1) * REC] = max_record(raw[k * REC:(k + 1) * REC], name, spells, stats)
            done += 1
        self.auto.write(base, bytes(raw))
        if spells:
            for k, name in enumerate(CHARS):
                if name in who:
                    self.auto.write(base + MAGIC_EXP + MAGIC_EXP_STRIDE * k, b"\0" * 24)
        return done

    def gold(self, value: int = GOLD_MAX):
        self.need()
        self.auto.write(self.reg["save"] + GOLD, struct.pack(">I", max(0, min(GOLD_MAX, int(value)))))

    def reputation(self):
        self.need()
        self.auto.write(self.reg["save"] + REPUTATION, b"\xff")

    # --- estoque
    def give(self, key: str, ids: List[int], count: Optional[int] = None) -> int:
        self.need()
        k, _label, off, slots, first, _tab, default = SECTION[key]
        n = default if count is None else count
        addr = self.reg["save"] + off
        cur = self.auto.read(addr, 4 * slots)
        add = [(i, n) for i in ids if first <= i < first + slots]
        self.auto.write(addr, merge_section(cur, add, slots))
        return len(add)

    # --- bandeiras
    def bits(self, ranges: List[Tuple[int, int]]):
        self.need()
        for off, size in ranges:
            self.auto.write(self.reg["bitvar"] + off, b"\xff" * size)

    def get_var(self, kind: str, index: int) -> int:
        self.need()
        if kind == "int":
            return struct.unpack(">i", self.auto.read(self.reg["intvar"] + 4 * index, 4))[0]
        if kind == "byte":
            return self.auto.read(self.reg["bytevar"] + index, 1)[0]
        b = self.auto.read(self.reg["bitvar"] + index // 8, 1)[0]
        return int(bool(b & (1 << (index % 8))))

    def set_var(self, kind: str, index: int, value: int):
        self.need()
        if not 0 <= index < 0x4000:
            raise TrapacaError("Índice fora do intervalo.")
        if kind == "int":
            self.auto.write(self.reg["intvar"] + 4 * index, struct.pack(">i", int(value)))
        elif kind == "byte":
            self.auto.write(self.reg["bytevar"] + index, bytes([int(value) & 0xFF]))
        else:
            a = self.reg["bitvar"] + index // 8
            b = self.auto.read(a, 1)[0]
            b = (b | (1 << (index % 8))) if value else (b & ~(1 << (index % 8)) & 0xFF)
            self.auto.write(a, bytes([b]))

    # --- mapa
    def current_map(self) -> str:
        self.need()
        raw = self.auto.read(self.reg["map"], 16)
        return raw.split(b"\0", 1)[0].decode("ascii", "replace")

    def warp(self, script: str):
        self.need()
        self.auto.write(self.reg["map"], warp_bytes(script))
        self.auto.write(self.reg["field_state"], struct.pack(">I", 0xF))

    # --- opcoes do proprio recomp (ficam gravadas no Dolphin.ini)
    def option(self, key: str, value: str):
        recomp._ini_set(self.data_dir, {("Skies", key): str(value)})
        if self.auto.alive():
            self.auto.config("Dolphin", "Skies", key, str(value))


def options(data_dir: str) -> Dict[str, Optional[str]]:
    return {k: recomp._ini_get(data_dir, "Skies", k) for k in ("Invincible", "Encounters")}


# ------------------------------------------------------------------ abrir o jogo
def runner_names() -> List[str]:
    return ["skies-run.exe"] if sys.platform.startswith("win") else ["skies-run"]


def find_runner(data_dir: str, hint: Optional[str] = None) -> Optional[str]:
    cands: List[str] = []
    if hint:
        cands += [hint, os.path.dirname(hint)]
    cands += [os.path.dirname(os.path.abspath(data_dir).rstrip("\\/")), data_dir]
    if sys.platform.startswith("win"):
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            v = os.environ.get(env)
            if v:
                cands += glob.glob(os.path.join(v, "*Skies*"))
    for c in cands:
        if not c:
            continue
        if os.path.isfile(c) and os.path.basename(c).lower() in runner_names():
            return os.path.abspath(c)
        for n in runner_names():
            p = os.path.join(c, n)
            if os.path.isfile(p):
                return os.path.abspath(p)
    return None


def state_files(data_dir: str, game_id: str) -> List[dict]:
    out = []
    for d in (os.path.join(data_dir, "StateSaves", game_id), os.path.join(data_dir, "StateSaves")):
        for p in glob.glob(os.path.join(d, "*.sav")):
            out.append({"path": os.path.abspath(p), "name": os.path.basename(p), "mtime": os.path.getmtime(p)})
    out.sort(key=lambda x: -x["mtime"])
    return out


def card_saves(data_dir: str, game_id: str) -> List[dict]:
    out = []
    pat = f"*{game_id[:4]}*SA_LEGENDS.*.gci" if game_id != "GEAJ8P" else "*EA_LEGEND.*.gci"
    for p in glob.glob(os.path.join(data_dir, "GC", "*", "Card A", pat)):
        tail = p.rsplit(".", 2)[-2]
        if tail.isdigit():
            out.append({"n": int(tail), "path": p, "mtime": os.path.getmtime(p)})
    out.sort(key=lambda x: -x["mtime"])
    return out


def launch(runner: str, game_root: str, data_dir: str, state: Optional[str] = None,
           card: Optional[int] = None) -> subprocess.Popen:
    auto = os.path.join(data_dir, "SOAL Trapacas")
    os.makedirs(os.path.join(auto, "commands"), exist_ok=True)
    for f in glob.glob(os.path.join(auto, "commands", "*")) + [os.path.join(auto, "status.txt")]:
        try:
            os.unlink(f)
        except OSError:
            pass
    if card is not None and not state:
        # AutoLoadCard conta a partir de 1: SA_LEGENDS.000 = 1 (patches/game/autoload.c do recomp)
        recomp._ini_set(data_dir, {("Skies", "AutoLoadCard"): str(int(card) + 1)})
    cmd = [runner, "--game", game_root, "--user-dir", data_dir, "--automation-dir", auto]
    if state:
        cmd += ["--load-state", state]
    kw = {}
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    with open(os.path.join(auto, "run.log"), "wb") as log:
        return subprocess.Popen(cmd, cwd=os.path.dirname(runner), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, **kw)
