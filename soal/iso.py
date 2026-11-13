"""Monta uma imagem de disco de GameCube (.iso / .gcm) a partir de uma pasta extraida.

A pasta precisa estar no formato que o Dolphin usa ao extrair um disco:

    <pasta>/sys/boot.bin      cabecalho do disco (0x440 bytes)
    <pasta>/sys/bi2.bin       informacoes extras (0x2000 bytes)
    <pasta>/sys/apploader.img programa de carga
    <pasta>/sys/main.dol      executavel
    <pasta>/sys/fst.bin       tabela de arquivos
    <pasta>/files/...         arquivos do jogo

Os arquivos sao gravados na ordem em que estavam no disco original, com as posicoes e
os tamanhos novos atualizados na tabela (fst.bin) e no cabecalho (boot.bin). Nada na pasta
e' alterado.
"""

import os
import struct
from typing import Callable, Dict, List, Optional

DISC_SIZE = 0x57058000           # 1.459.978.240 bytes: um disco de GameCube
HEADER_SIZE = 0x440
BI2_SIZE = 0x2000
APPLOADER_OFF = 0x2440
CHUNK = 4 * 1024 * 1024


class IsoError(Exception):
    pass


def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as e:
        raise IsoError(f"não consegui ler {path}: {e.strerror or e}")


def is_extracted_disc(root: str) -> bool:
    sysd = os.path.join(root, "sys")
    return all(os.path.isfile(os.path.join(sysd, n))
               for n in ("boot.bin", "bi2.bin", "apploader.img", "main.dol", "fst.bin")) \
        and os.path.isdir(os.path.join(root, "files"))


def _parse_fst(fst: bytes) -> List[dict]:
    """Entradas de arquivo da tabela: indice, caminho (com /) e posicao original."""
    if len(fst) < 12 or fst[0] != 1:
        raise IsoError("sys/fst.bin inválido")
    count = struct.unpack_from(">I", fst, 8)[0]
    if count < 1 or 12 * count > len(fst):
        raise IsoError("sys/fst.bin inválido")
    names = 12 * count
    out: List[dict] = []
    dirs = [(count, "")]
    for i in range(1, count):
        while len(dirs) > 1 and i >= dirs[-1][0]:
            dirs.pop()
        w0, a, b = struct.unpack_from(">III", fst, 12 * i)
        off = names + (w0 & 0xFFFFFF)
        end = fst.find(b"\0", off)
        if off >= len(fst) or end < 0:
            raise IsoError("nome de arquivo fora do sys/fst.bin")
        name = fst[off:end].decode("shift_jis", "replace")
        if w0 >> 24:
            if not (i < b <= count):
                raise IsoError("pasta com limites inválidos no sys/fst.bin")
            dirs.append((b, dirs[-1][1] + name + "/"))
        else:
            out.append({"i": i, "path": dirs[-1][1] + name, "orig_off": a, "orig_size": b})
    return out


def _find_file(files_dir: str, rel: str, cache: Dict[str, Dict[str, str]]) -> Optional[str]:
    """Acha o arquivo mesmo que a caixa das letras seja diferente (Linux)."""
    p = os.path.join(files_dir, *rel.split("/"))
    if os.path.isfile(p):
        return p
    cur = files_dir
    for part in rel.split("/"):
        names = cache.get(cur)
        if names is None:
            try:
                names = {n.lower(): n for n in os.listdir(cur)}
            except OSError:
                return None
            cache[cur] = names
        real = names.get(part.lower())
        if real is None:
            return None
        cur = os.path.join(cur, real)
    return cur if os.path.isfile(cur) else None


def plan(root: str) -> dict:
    """Le a pasta e calcula onde cada parte vai ficar no disco."""
    if not is_extracted_disc(root):
        raise IsoError("A pasta do jogo precisa ter sys/ (boot.bin, bi2.bin, apploader.img, "
                       "main.dol, fst.bin) e files/, como numa extração do Dolphin.")
    sysd = os.path.join(root, "sys")
    boot = bytearray(_read(os.path.join(sysd, "boot.bin")))
    bi2 = _read(os.path.join(sysd, "bi2.bin"))
    app = _read(os.path.join(sysd, "apploader.img"))
    dol = _read(os.path.join(sysd, "main.dol"))
    fst = bytearray(_read(os.path.join(sysd, "fst.bin")))
    if len(boot) != HEADER_SIZE or len(bi2) != BI2_SIZE:
        raise IsoError("sys/boot.bin ou sys/bi2.bin com tamanho errado.")
    if boot[0x1C:0x20] != b"\xC2\x33\x9F\x3D":
        raise IsoError("sys/boot.bin não é de um disco de GameCube.")
    entries = _parse_fst(bytes(fst))
    files_dir = os.path.join(root, "files")
    cache: Dict[str, Dict[str, str]] = {}
    missing = []
    for e in entries:
        e["src"] = _find_file(files_dir, e["path"], cache)
        if e["src"] is None:
            missing.append(e["path"])
        else:
            e["size"] = os.path.getsize(e["src"])
    if missing:
        raise IsoError(f"Faltam {len(missing)} arquivos em files/, por exemplo: " + ", ".join(missing[:3]))
    # mesma ordem do disco original (leitura mais rapida no console)
    entries.sort(key=lambda e: (e["orig_off"], e["i"]))

    dol_off = _align(APPLOADER_OFF + len(app), 0x100)
    fst_off = _align(dol_off + len(dol), 0x100)
    head_end = fst_off + len(fst)
    layout = None
    for align in (0x8000, 0x800, 0x20):
        pos = _align(head_end, align)
        offs = []
        for e in entries:
            pos = _align(pos, align)
            offs.append(pos)
            pos += e["size"]
        if pos <= DISC_SIZE:
            layout = (align, offs, pos)
            break
    if layout is None:
        over = pos - DISC_SIZE
        raise IsoError(f"Os arquivos passam {over:,} bytes do tamanho de um disco de GameCube "
                       "(1,36 GB).".replace(",", "."))
    align, offs, end = layout
    for e, o in zip(entries, offs):
        e["off"] = o
        struct.pack_into(">II", fst, 12 * e["i"] + 4, o, e["size"])
    struct.pack_into(">IIII", boot, 0x420, dol_off, fst_off, len(fst),
                     max(len(fst), struct.unpack_from(">I", boot, 0x42C)[0]))
    return {"boot": bytes(boot), "bi2": bi2, "app": app, "dol": dol, "fst": bytes(fst),
            "dol_off": dol_off, "fst_off": fst_off, "entries": entries, "align": align,
            "end": end, "game_id": boot[:6].decode("ascii", "replace"),
            "changed": sum(1 for e in entries if e["size"] != e["orig_size"])}


def build(root: str, out_path: str, progress: Optional[Callable] = None,
          cancelled: Callable[[], bool] = lambda: False, full_size: bool = True) -> dict:
    """Grava a imagem em out_path (primeiro num arquivo temporario ao lado)."""
    pl = plan(root)
    out_path = os.path.abspath(out_path)
    rootn = os.path.normcase(os.path.abspath(root)) + os.sep
    if os.path.normcase(out_path).startswith(rootn):
        raise IsoError("Salve a imagem fora da pasta do jogo.")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".gerando"
    total = sum(e["size"] for e in pl["entries"])
    done = 0
    try:
        with open(tmp, "wb") as out:
            out.write(pl["boot"])
            out.write(pl["bi2"])
            out.write(pl["app"])
            for off, data in ((pl["dol_off"], pl["dol"]), (pl["fst_off"], pl["fst"])):
                out.write(b"\0" * (off - out.tell()))
                out.write(data)
            for n, e in enumerate(pl["entries"]):
                if cancelled():
                    raise IsoError("Cancelado.")
                gap = e["off"] - out.tell()
                if gap:
                    out.write(b"\0" * gap)
                left = e["size"]
                with open(e["src"], "rb") as src:
                    while left > 0:
                        buf = src.read(min(CHUNK, left))
                        if not buf:
                            raise IsoError(f"{e['path']} mudou de tamanho durante a gravação.")
                        out.write(buf)
                        left -= len(buf)
                        done += len(buf)
                        if progress:
                            progress(f"Gerando a imagem do disco ({n + 1} de {len(pl['entries'])} arquivos)",
                                     done, total)
            if full_size and out.tell() < DISC_SIZE:
                out.truncate(DISC_SIZE)
        if progress:
            progress("Conferindo a imagem", total, total)
        verify(tmp, pl)
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {"path": out_path, "bytes": os.path.getsize(out_path), "files": len(pl["entries"]),
            "changed": pl["changed"], "game_id": pl["game_id"], "align": pl["align"]}


def read_iso(path: str) -> dict:
    """Le cabecalho e tabela de uma imagem (usado para conferir a que foi gerada)."""
    with open(path, "rb") as fh:
        boot = fh.read(HEADER_SIZE)
        dol_off, fst_off, fst_size = struct.unpack_from(">III", boot, 0x420)
        fh.seek(fst_off)
        fst = fh.read(fst_size)
    return {"boot": boot, "dol_off": dol_off, "fst_off": fst_off, "fst": fst,
            "entries": {e["path"]: e for e in _parse_fst(fst)}}


def verify(path: str, pl: dict) -> None:
    info = read_iso(path)
    if info["boot"] != pl["boot"] or info["fst"] != pl["fst"]:
        raise IsoError("A conferência da imagem falhou (cabeçalho ou tabela diferentes).")
    with open(path, "rb") as fh:
        fh.seek(info["dol_off"])
        if fh.read(len(pl["dol"])) != pl["dol"]:
            raise IsoError("A conferência da imagem falhou (main.dol).")
        for e in pl["entries"]:
            got = info["entries"].get(e["path"])
            if got is None or got["orig_off"] != e["off"] or got["orig_size"] != e["size"]:
                raise IsoError(f"A conferência da imagem falhou ({e['path']}).")
            n = min(e["size"], 4096)
            if not n:
                continue
            fh.seek(e["off"])
            head = fh.read(n)
            with open(e["src"], "rb") as src:
                if src.read(n) != head:
                    raise IsoError(f"A conferência da imagem falhou ({e['path']}).")


def extract(path: str, dest: str) -> int:
    """Extrai uma imagem para sys/ e files/ (usado nos testes)."""
    info = read_iso(path)
    os.makedirs(os.path.join(dest, "sys"), exist_ok=True)
    with open(path, "rb") as fh:
        boot = info["boot"]
        fh.seek(HEADER_SIZE)
        bi2 = fh.read(BI2_SIZE)
        fh.seek(APPLOADER_OFF)
        hdr = fh.read(0x20)
        app_size = 0x20 + struct.unpack_from(">I", hdr, 0x14)[0] + struct.unpack_from(">I", hdr, 0x18)[0]
        fh.seek(APPLOADER_OFF)
        app = fh.read(app_size)
        fh.seek(info["dol_off"])
        dh = fh.read(0x100)
        dol_size = max([0x100] + [struct.unpack_from(">I", dh, 4 * k)[0] + struct.unpack_from(">I", dh, 0x90 + 4 * k)[0]
                                  for k in range(18)])
        fh.seek(info["dol_off"])
        dol = fh.read(dol_size)
        for name, data in (("boot.bin", boot), ("bi2.bin", bi2), ("apploader.img", app), ("main.dol", dol),
                           ("fst.bin", info["fst"])):
            with open(os.path.join(dest, "sys", name), "wb") as o:
                o.write(data)
        for e in info["entries"].values():
            p = os.path.join(dest, "files", *e["path"].split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            fh.seek(e["orig_off"])
            with open(p, "wb") as o:
                o.write(fh.read(e["orig_size"]))
    return len(info["entries"])
