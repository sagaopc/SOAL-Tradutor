"""Projeto de traducao: extracao dos textos, armazenamento das traducoes e gravacao no jogo."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import re
import shutil
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import aklz
from . import font as fontmod
from . import mt, recomp, sct, text

PROJECT_FILE = "projeto.json"
CACHE_FILE = "textos.json"
ORIG_DIR = "originais"
CACHE_VERSION = 5

CATEGORIES = [
    ("cidades", "Cidades e ilhas"),
    ("masmorras", "Masmorras"),
    ("cenas", "Cenas"),
    ("navios", "Batalhas de navio"),
    ("mundo", "Mundo aberto"),
    ("outros", "Testes e outros"),
]

# letra acentuada -> simbolo da fonte que sera' redesenhado (nenhum deles aparece nos dialogos)
DEFAULT_CHARMAP = {
    "á": "#", "à": "$", "â": "<", "ã": ">", "é": "@", "ê": "^",
    "í": "_", "ó": "`", "ô": "{", "õ": "|", "ú": "}", "ç": "=",
    "É": "+", "Á": "/", "Ó": '"',
}
FREE_SLOTS = '#$<>@^_`{|}=+/"'

DEFAULT_SETTINGS = {
    "cols": 48,
    "lines": 3,
    "accents": "font",       # font = redesenha simbolos da fonte; strip = grava sem acento
    "charmap": DEFAULT_CHARMAP,
    "autofill": True,
    "keep_states": False,    # so' no recomp: tamanhos em blocos de 32 KB (experimental)
    "backup_dir": "",        # pasta onde guardar copias de seguranca do projeto
}

BACKUP_EVERY = 600           # segundos entre copias de seguranca enquanto ha' mudancas
BACKUP_KEEP = 20             # quantas copias com data manter


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_STORY = None


def story_order() -> list:
    """Capitulos da historia com os arquivos de cada um (data/ordem_historia.json)."""
    global _STORY
    if _STORY is None:
        try:
            with open(os.path.join(DATA_DIR, "ordem_historia.json"), encoding="utf-8") as fh:
                _STORY = [[c["titulo"], list(c["arquivos"])] for c in json.load(fh)["capitulos"]]
        except (OSError, ValueError, KeyError):
            _STORY = []
    return _STORY


def tool_dir() -> str:
    """Pasta do proprio SOAL Tradutor (a do .exe, ou a que tem o run.py)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_project_dir(d: str) -> bool:
    return bool(d) and os.path.isfile(os.path.join(d, PROJECT_FILE))


def _fmt_secs(sec: float) -> str:
    sec = int(round(sec))
    if sec < 60:
        return f"{max(sec, 1)} s"
    if sec < 3600:
        return f"{sec // 60} min" + (f" {sec % 60:02d} s" if sec < 600 and sec % 60 else "")
    return f"{sec // 3600} h {(sec % 3600) // 60:02d} min"


class ProjectError(Exception):
    pass


def category_of(name: str) -> str:
    n = name.lower()
    if n.startswith("me099"):
        return "mundo"
    if n.startswith("me0"):
        return "cidades"
    if n.startswith("me1"):
        return "masmorras"
    if n.startswith("me2"):
        return "cenas"
    if n.startswith("me5"):
        return "navios"
    return "outros"


REGIONS = {"GEAE8P": "us", "GEAP8P": "eu"}


def eu_foreign_sections(names: List[str]) -> set:
    """Na versao europeia cada fala existe em ingles e em mais tres idiomas. As variantes
    em frances, alemao e espanhol tem o nome da fala inglesa com F, G ou S logo depois do
    M (MA0090000 -> MFA0090000, MGA0090000, MSA0090000). So' a inglesa e' traduzida; as
    outras ficam como estao."""
    have = set(names)
    out = set()
    for n in names:
        if len(n) > 2 and n[0] == "M" and n[1] in "FGS":
            base = "M" + n[2:]
            if base in have and all(("M" + x + n[2:]) in have for x in "FGS"):
                out.add(n)
    return out


def find_game(root: str) -> Tuple[str, Optional[str]]:
    """Acha a pasta 'field' (com os .sct) e o arquivo de fonte dentro de uma extracao do jogo."""
    root = os.path.abspath(root)
    candidates = [os.path.join(root, "files", "field"), os.path.join(root, "field"), root]
    for field in candidates:
        if os.path.isdir(field) and any(f.lower().endswith(".sct") for f in os.listdir(field)):
            parent = os.path.dirname(field)
            fnt = None
            for f in os.listdir(parent):
                if f.lower().startswith("fontdata."):
                    fnt = os.path.join(parent, f)
                    break
            return field, fnt
    raise ProjectError(
        "Nao encontrei arquivos .sct nessa pasta. Escolha a pasta onde a ISO foi extraida "
        "(a que contem 'files' e 'sys', ou a que contem 'field').")


def _atomic_write(path: str, data: bytes):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


class Project:
    def __init__(self, project_dir: str):
        self.dir = os.path.abspath(project_dir)
        self.lock = threading.RLock()
        self.meta: dict = {}
        self.files: List[dict] = []          # cache de extracao
        self.by_name: Dict[str, dict] = {}
        self.same: Dict[str, List[Tuple[str, str]]] = {}   # corpo original -> [(arquivo, chave)]
        self._dirty = False
        self._last_save = 0.0
        self._last_backup = 0.0
        self._backup_pending = False

    # ------------------------------------------------------------ caminhos
    @property
    def orig_field(self) -> str:
        return os.path.join(self.dir, ORIG_DIR, "field")

    @property
    def orig_font(self) -> Optional[str]:
        d = os.path.join(self.dir, ORIG_DIR)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().startswith("fontdata."):
                    return os.path.join(d, f)
        return None

    @property
    def settings(self) -> dict:
        return self.meta["settings"]

    @property
    def tr(self) -> Dict[str, Dict[str, dict]]:
        return self.meta["tr"]

    @property
    def names(self) -> Dict[str, str]:
        return self.meta["names"]

    @property
    def eu(self) -> bool:
        return self.meta.get("region") == "eu"

    # ------------------------------------------------------------ abrir / criar
    @staticmethod
    def default_dir(game_root: str) -> str:
        game_root = os.path.abspath(game_root).rstrip("\\/")
        if recomp.is_recomp_game(game_root):
            # dentro de "games" o launcher do port poderia confundir a pasta com um jogo
            return os.path.join(os.path.expanduser("~"), "SOAL Tradutor", os.path.basename(game_root))
        return game_root + "_traducao"

    @classmethod
    def create_or_open(cls, game_root: str, project_dir: Optional[str] = None,
                       progress: Optional[Callable[[str, int, int], None]] = None) -> "Project":
        field, fnt = find_game(game_root)
        gid = recomp.game_id(game_root)
        if gid and gid not in REGIONS:
            raise ProjectError(
                f"Esta pasta e' da versao {recomp.REGION_NAMES.get(gid, gid)} ({gid}). "
                "O programa traduz a versao americana (GEAE8P) e a europeia (GEAP8P).")
        pdir = project_dir or cls.default_dir(game_root)
        p = cls(pdir)
        os.makedirs(p.orig_field, exist_ok=True)
        meta_path = os.path.join(pdir, PROJECT_FILE)
        if os.path.exists(meta_path):
            p._load_meta()
        else:
            p.meta = {"version": 1, "created": time.strftime("%Y-%m-%d %H:%M"),
                      "settings": json.loads(json.dumps(DEFAULT_SETTINGS)), "names": {}, "tr": {}}
        region = REGIONS.get(gid or "", "us")
        if p.meta.get("region", region) != region:
            raise ProjectError("Esse projeto e' de outra versao do jogo; escolha outra pasta de projeto.")
        p.meta["region"] = region
        p.meta["game_id"] = gid or ""
        if region == "eu":
            # a fonte europeia ja' tem as letras acentuadas
            p.meta["settings"]["accents"] = "native"
        p.meta["game_root"] = os.path.abspath(game_root)
        p.meta["game_field"] = field
        p.meta["game_font"] = fnt
        # guarda os originais uma unica vez; depois disso o jogo pode ser sobrescrito a vontade
        names = sorted((f for f in os.listdir(field) if f.lower().endswith(".sct")), key=str.lower)
        for i, f in enumerate(names):
            dst = os.path.join(p.orig_field, f)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(field, f), dst)
            if progress and i % 20 == 0:
                progress("Guardando copias dos originais", i, len(names))
        if fnt and not p.orig_font:
            shutil.copy2(fnt, os.path.join(pdir, ORIG_DIR, os.path.basename(fnt)))
        p.meta["not_original"] = p.check_originals()
        p._dirty = True
        p.save(force=True)
        p.extract(progress)
        return p

    @classmethod
    def open(cls, project_dir: str, progress=None) -> "Project":
        p = cls(project_dir)
        if not os.path.exists(os.path.join(p.dir, PROJECT_FILE)):
            raise ProjectError("Essa pasta nao tem um projeto de traducao.")
        p._load_meta()
        p.extract(progress)
        return p

    def check_originals(self) -> List[str]:
        """Arquivos guardados como originais que nao batem com os do disco americano
        (pasta que ja' tinha traducao gravada, ou romhack)."""
        if self.eu:
            return self._check_eu_originals()
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                   "originais_geae8p.json"), encoding="utf-8") as fh:
                known = json.load(fh)["files"]
        except (OSError, ValueError, KeyError):
            return []
        bad = []
        for f in sorted(os.listdir(self.orig_field)):
            want = known.get(f.lower())
            if want and self._sha1_file(os.path.join(self.orig_field, f)) != want:
                bad.append(f)
        of = self.orig_font
        if of and known.get(os.path.basename(of).lower()) not in (None, self._sha1_file(of)):
            bad.append(os.path.basename(of))
        return bad

    def _check_eu_originals(self) -> List[str]:
        """Versao europeia: ainda nao ha' lista de referencia dos arquivos originais; so'
        aponta os que nao dao para ler."""
        bad = []
        for f in sorted(os.listdir(self.orig_field)):
            if not f.lower().endswith(".sct"):
                continue
            try:
                s = sct.load(os.path.join(self.orig_field, f))
            except (sct.SctError, OSError, ValueError):
                bad.append(f)
                continue
            if s.problems:
                bad.append(f)
        return bad

    def _load_meta(self):
        with open(os.path.join(self.dir, PROJECT_FILE), encoding="utf-8") as fh:
            self.meta = json.load(fh)
        st = json.loads(json.dumps(DEFAULT_SETTINGS))
        st.update(self.meta.get("settings") or {})
        self.meta["settings"] = st
        self.meta.setdefault("names", {})
        self.meta.setdefault("tr", {})
        self.meta.setdefault("region", "us")

    def save(self, force: bool = False):
        with self.lock:
            if not self._dirty and not force:
                return
            data = json.dumps(self.meta, ensure_ascii=False, indent=0).encode("utf-8")
            _atomic_write(os.path.join(self.dir, PROJECT_FILE), data)
            self._dirty = False
            self._last_save = time.time()
            self._backup_pending = True
        if self._backup_pending and time.time() - self._last_backup >= BACKUP_EVERY:
            try:
                self.backup()
            except OSError:
                pass

    # ------------------------------------------------------------ copias
    def backup_root(self) -> str:
        d = (self.settings.get("backup_dir") or "").strip()
        return os.path.join(d, os.path.basename(self.dir.rstrip("\\/"))) if d else ""

    def backup(self, force: bool = False) -> Optional[str]:
        """Copia o projeto.json para a pasta de copias, com a data no nome. Mantem as ultimas
        BACKUP_KEEP e um "projeto.json" sempre igual ao mais recente."""
        root = self.backup_root()
        if not root:
            return None
        with self.lock:
            if not self._backup_pending and not force:
                return None
            if self._dirty:
                self.save()
            src = os.path.join(self.dir, PROJECT_FILE)
            with open(src, "rb") as fh:
                data = fh.read()
            os.makedirs(root, exist_ok=True)
            name = "projeto " + time.strftime("%Y-%m-%d %H-%M-%S") + ".json"
            _atomic_write(os.path.join(root, name), data)
            _atomic_write(os.path.join(root, PROJECT_FILE), data)
            olds = sorted(f for f in os.listdir(root) if f.startswith("projeto 2") and f.endswith(".json"))
            for f in olds[:-BACKUP_KEEP]:
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass
            self._last_backup = time.time()
            self._backup_pending = False
            return os.path.join(root, name)

    def backup_list(self) -> List[str]:
        root = self.backup_root()
        if not root or not os.path.isdir(root):
            return []
        return sorted((f for f in os.listdir(root) if f.startswith("projeto 2") and f.endswith(".json")),
                      reverse=True)

    def move_to(self, new_dir: str, progress=None) -> str:
        """Move a pasta inteira do projeto (traducoes, originais, copias da gravacao)."""
        new_dir = os.path.abspath(new_dir.strip().strip('"'))
        old = self.dir
        if os.path.normcase(new_dir) == os.path.normcase(old):
            return old
        if os.path.normcase(new_dir).startswith(os.path.normcase(old.rstrip("\\/") + os.sep)):
            raise ProjectError("A pasta nova não pode ficar dentro da pasta atual do projeto.")
        if os.path.exists(new_dir) and os.listdir(new_dir):
            raise ProjectError("A pasta escolhida já tem arquivos. Escolha uma pasta vazia ou um nome novo.")
        gr = os.path.normcase(os.path.abspath(self.meta.get("game_root") or ""))
        if gr and (os.path.normcase(new_dir) == gr or os.path.normcase(new_dir).startswith(gr + os.sep)):
            raise ProjectError("Não coloque o projeto dentro da pasta do jogo.")
        with self.lock:
            self.save(force=True)
            names = []
            for base, _dirs, files in os.walk(old):
                for f in files:
                    names.append(os.path.join(base, f))
            tmp = new_dir + ".copiando"
            if os.path.exists(tmp):
                shutil.rmtree(tmp)
            for i, src in enumerate(names):
                if progress and i % 20 == 0:
                    progress("Copiando o projeto para a pasta nova", i, len(names))
                dst = os.path.join(tmp, os.path.relpath(src, old))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                if os.path.getsize(src) != os.path.getsize(dst):
                    raise ProjectError("A cópia de " + os.path.relpath(src, old) + " ficou diferente; nada foi movido.")
            if os.path.exists(new_dir):
                os.rmdir(new_dir)
            os.makedirs(os.path.dirname(new_dir) or ".", exist_ok=True)
            os.replace(tmp, new_dir)
            self.dir = new_dir
            # so' apaga a pasta antiga depois que a nova esta' completa
            if progress:
                progress("Apagando a pasta antiga", len(names), len(names))
            shutil.rmtree(old, ignore_errors=True)
        return new_dir

    def touch(self):
        self._dirty = True

    # ------------------------------------------------------------ extracao
    def extract(self, progress=None, force: bool = False):
        cache_path = os.path.join(self.dir, CACHE_FILE)
        names = sorted((f for f in os.listdir(self.orig_field) if f.lower().endswith(".sct")), key=str.lower)
        if not force and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as fh:
                    c = json.load(fh)
                if c.get("version") == CACHE_VERSION and [f["name"] for f in c["files"]] == names:
                    self._set_files(c["files"])
                    return
            except (ValueError, KeyError):
                pass
        files = []
        for i, f in enumerate(names):
            if progress:
                progress("Lendo os textos do jogo", i, len(names))
            files.append(self._extract_file(f))
        _atomic_write(cache_path, json.dumps({"version": CACHE_VERSION, "files": files},
                                             ensure_ascii=False).encode("utf-8"))
        self._set_files(files)

    def _extract_file(self, fname: str) -> dict:
        entry = {"name": fname, "cat": category_of(fname), "entries": [], "error": None}
        try:
            s = sct.load(os.path.join(self.orig_field, fname))
        except (sct.SctError, OSError, ValueError) as exc:
            entry["error"] = str(exc)
            return entry
        if s.problems:
            entry["error"] = "; ".join(s.problems[:3])
        seen: Dict[str, int] = {}
        prev_cont = False
        prev_index = -2
        eu = self.eu
        secs = s.string_sections()
        skip = eu_foreign_sections([x.name for x in secs]) if eu else set()
        for sec in secs:
            if sec.name in skip:
                continue
            n = seen.get(sec.name, 0)
            seen[sec.name] = n + 1
            key = sec.name if n == 0 else f"{sec.name}~{n}"
            raw = s.text_bytes(sec)
            e = {"k": key, "sec": sec.name, "i": sec.index}
            try:
                gt = text.decode(raw, eu)
                e.update(head=gt.head, br=gt.brackets, body=gt.body, end=gt.end)
                if gt.style != "jp":
                    e["bs"] = gt.style
            except text.TextError:
                e.update(head=None, br=False, body="", end="", raw=raw.hex())
            e["cont"] = bool(prev_cont and prev_index == sec.index - 1)
            if text.has_japanese(e["body"]) or e["body"].startswith("//"):
                e["dbg"] = True
            prev_cont = e["end"] == "c"
            prev_index = sec.index
            entry["entries"].append(e)
        for k, fs in enumerate(x for x in s.footer if x.dialog):
            raw = s.footer_bytes(fs)
            e = {"k": f"@rodape{k}", "sec": "rodape", "i": -1, "pos": fs.start, "cont": False}
            try:
                gt = text.decode(raw, eu)
                e.update(head=gt.head, br=gt.brackets, body=gt.body, end=gt.end)
                if gt.style != "jp":
                    e["bs"] = gt.style
            except text.TextError:
                continue
            if text.has_japanese(e["body"]) or entry["cat"] == "outros":
                e["dbg"] = True
            entry["entries"].append(e)
        return entry

    def _set_files(self, files: List[dict]):
        self.files = files
        self.by_name = {f["name"]: f for f in files}
        self.same = {}
        for f in files:
            f["_idx"] = {e["k"]: e for e in f["entries"]}
            for e in f["entries"]:
                if e["body"] and not e.get("raw"):
                    self.same.setdefault(e["body"], []).append((f["name"], e["k"]))

    # ------------------------------------------------------------ consulta
    def translated(self, fname: str, key: str) -> Optional[dict]:
        return self.tr.get(fname, {}).get(key)

    def file_stats(self, f: dict) -> Tuple[int, int]:
        tr = self.tr.get(f["name"], {})
        total = done = 0
        for e in f["entries"]:
            if e.get("dbg") or e.get("raw") or not e["body"].strip():
                continue
            total += 1
            t = tr.get(e["k"])
            if t and t.get("t"):
                done += 1
        return total, done

    def summary(self) -> dict:
        out = []
        gt = gd = 0
        for f in self.files:
            t, d = self.file_stats(f)
            gt += t
            gd += d
            out.append({"name": f["name"], "cat": f["cat"], "total": t, "done": d,
                        "count": len(f["entries"]), "error": f.get("error")})
        return {"files": out, "total": gt, "done": gd,
                "unique": len(self.same), "categories": CATEGORIES, "story": story_order()}

    def file_entries(self, fname: str) -> dict:
        f = self.by_name.get(fname)
        if f is None:
            raise ProjectError("arquivo desconhecido")
        tr = self.tr.get(fname, {})
        rows = []
        for e in f["entries"]:
            t = tr.get(e["k"], {})
            row = {k: v for k, v in e.items() if k not in ("raw",)}
            row["t"] = t.get("t", "")
            row["st"] = t.get("st", "")
            row["auto"] = bool(t.get("auto"))
            row["dup"] = len(self.same.get(e["body"], ())) if e["body"] else 0
            rows.append(row)
        return {"name": fname, "cat": f["cat"], "entries": rows, "error": f.get("error")}

    # ------------------------------------------------------------ edicao
    def set_translation(self, fname: str, key: str, value: str, status: Optional[str] = None) -> dict:
        with self.lock:
            f = self.by_name.get(fname)
            if f is None or key not in f["_idx"]:
                raise ProjectError("texto desconhecido")
            e = f["_idx"][key]
            value = value.replace("\r\n", "\n").replace("\r", "\n")
            ft = self.tr.setdefault(fname, {})
            cur = ft.get(key, {})
            new = dict(cur)
            new["t"] = value
            new.pop("auto", None)
            if status is not None:
                new["st"] = status
            if not new.get("t") and not new.get("st"):
                ft.pop(key, None)
            else:
                ft[key] = new
            filled = []
            if value and self.settings.get("autofill", True):
                for of, ok in self.same.get(e["body"], ()):
                    if of == fname and ok == key:
                        continue
                    oft = self.tr.setdefault(of, {})
                    o = oft.get(ok)
                    if o is None or not o.get("t") or o.get("auto"):
                        st2 = "mt" if status == "mt" else (o or {}).get("st", "")
                        oft[ok] = {"t": value, "auto": True, "st": st2}
                        filled.append([of, ok])
            self.touch()
            return {"filled": filled}

    def set_status(self, fname: str, key: str, status: str):
        with self.lock:
            f = self.by_name.get(fname)
            if f is None or key not in f["_idx"]:
                raise ProjectError("texto desconhecido")
            ft = self.tr.setdefault(fname, {})
            cur = ft.setdefault(key, {"t": ""})
            cur["st"] = status
            if not cur.get("t") and not status:
                ft.pop(key, None)
            self.touch()

    def name_list(self) -> List[dict]:
        counts: Dict[str, int] = {}
        for f in self.files:
            for e in f["entries"]:
                h = e.get("head")
                if h and e.get("br") and not e.get("dbg"):
                    counts[h] = counts.get(h, 0) + 1
        return [{"name": n, "count": c, "t": self.names.get(n, "")}
                for n, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]

    def set_name(self, name: str, value: str):
        with self.lock:
            value = value.strip()
            if value and value != name:
                self.names[name] = value
            else:
                self.names.pop(name, None)
            self.touch()

    def search(self, query: str, limit: int = 400) -> List[dict]:
        q = query.casefold().strip()
        if not q:
            return []
        out = []
        for f in self.files:
            tr = self.tr.get(f["name"], {})
            for e in f["entries"]:
                t = tr.get(e["k"], {}).get("t", "")
                hay = (e["body"] + "\n" + t + "\n" + (e.get("head") or "") + "\n" + e["sec"]).casefold()
                if q in hay:
                    out.append({"file": f["name"], "k": e["k"], "head": e.get("head"),
                                "body": e["body"], "t": t})
                    if len(out) >= limit:
                        return out
        return out

    # ------------------------------------------------------------ conferencia
    def charmap_codes(self) -> Dict[str, int]:
        if self.eu or self.settings.get("accents") != "font":
            return {}
        return {ch: ord(sym) for ch, sym in (self.settings.get("charmap") or {}).items()
                if len(ch) == 1 and len(sym) == 1}

    def check_text(self, body: str) -> List[str]:
        cm = self.charmap_codes()
        cols = int(self.settings.get("cols", 48))
        maxl = int(self.settings.get("lines", 3))
        issues = []
        for page in re.split(r"\\c", body):
            lines = page.split("\n")
            if len(lines) > maxl:
                issues.append(f"{len(lines)} linhas (a caixa mostra {maxl})")
            for ln in lines:
                w = text.columns(ln, cm, self.eu)
                if w > cols:
                    issues.append(f"linha com {w} colunas (limite {cols})")
        return issues

    # ------------------------------------------------------------ planilha
    def export_csv(self) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["arquivo", "chave", "personagem", "original", "traducao", "situacao"])
        for f in self.files:
            tr = self.tr.get(f["name"], {})
            for e in f["entries"]:
                if e.get("raw"):
                    continue
                t = tr.get(e["k"], {})
                w.writerow([f["name"], e["k"], e.get("head") or "", e["body"], t.get("t", ""), t.get("st", "")])
        return (chr(0xFEFF) + buf.getvalue()).encode("utf-8")

    def export_unique_csv(self) -> bytes:
        """Uma linha por fala unica (as repetidas sao preenchidas sozinhas na importacao)."""
        cols = int(self.settings.get("cols", 48))
        maxl = int(self.settings.get("lines", 3))
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["arquivo", "chave", "personagem", "tipo", "repeticoes", "fala_anterior",
                    "original", "traducao", "situacao"])
        seen = set()
        for f in self.files:
            tr = self.tr.get(f["name"], {})
            prev = ""
            for e in f["entries"]:
                if e.get("raw") or e.get("dbg") or not e["body"].strip():
                    continue
                body = e["body"]
                who = e.get("head") if e.get("br") else ""
                if body not in seen:
                    seen.add(body)
                    t = tr.get(e["k"], {})
                    kind = ("menu: mantenha uma opcao por linha" if text.is_menu(body)
                            else f"fala: ate {maxl} linhas de {cols} colunas")
                    w.writerow([f["name"], e["k"], who or "", kind, len(self.same.get(body, ())) or 1,
                                prev, body, t.get("t", ""), t.get("st", "")])
                prev = ((who + ": ") if who else "") + body.replace("\n", " ")
        return (chr(0xFEFF) + buf.getvalue()).encode("utf-8")

    def import_csv(self, data: bytes) -> dict:
        txt = data.decode("utf-8-sig", "replace")
        first = txt.split("\n", 1)[0]
        delim = ";" if first.count(";") >= first.count(",") and ";" in first else ("\t" if "\t" in first else ",")
        rd = csv.reader(io.StringIO(txt), delimiter=delim)
        head = [h.strip().lower() for h in next(rd, [])]
        try:
            ci, ck, ct = head.index("arquivo"), head.index("chave"), head.index("traducao")
        except ValueError:
            raise ProjectError("A planilha precisa das colunas 'arquivo', 'chave' e 'traducao'.")
        cs = head.index("situacao") if "situacao" in head else -1
        cols = int(self.settings.get("cols", 48))
        maxl = int(self.settings.get("lines", 3))
        cm = self.charmap_codes()
        applied = skipped = filled = wrapped = 0
        with self.lock:
            for row in rd:
                if len(row) <= max(ci, ck, ct):
                    continue
                f = self.by_name.get(row[ci].strip())
                key = row[ck].strip()
                if f is None or key not in f["_idx"]:
                    skipped += 1
                    continue
                e = f["_idx"][key]
                val = row[ct].replace("\r\n", "\n").replace("\r", "\n").strip("\n")
                if val and not text.is_menu(e["body"]):
                    val, ch = text.wrap(val, cols, maxl, cm, self.eu)
                    wrapped += ch
                st = row[cs].strip() if cs >= 0 and len(row) > cs else None
                ft = self.tr.setdefault(f["name"], {})
                cur = ft.get(key, {})
                if val != cur.get("t", "") or (st is not None and st != cur.get("st", "")):
                    if not val and not st:
                        ft.pop(key, None)
                    else:
                        ft[key] = {"t": val, "st": st if st is not None else cur.get("st", "")}
                    applied += 1
                # falas identicas em outros lugares: preenche as que ainda nao tem traducao propria
                if val:
                    for of, ok in self.same.get(e["body"], ()):
                        if of == f["name"] and ok == key:
                            continue
                        oft = self.tr.setdefault(of, {})
                        o = oft.get(ok)
                        if o is None or not o.get("t") or o.get("auto"):
                            if not o or o.get("t") != val:
                                oft[ok] = {"t": val, "auto": True, "st": (o or {}).get("st", "")}
                                filled += 1
            self.touch()
        self.save()
        return {"applied": applied, "skipped": skipped, "filled": filled, "wrapped": wrapped}

    # ------------------------------------------------------------ outro projeto
    def import_project(self, other_dir: str) -> dict:
        """Traz as traducoes de outro projeto (por exemplo, o da versao americana para o da
        europeia). As falas sao ligadas pelo arquivo e pelo nome da secao, que sao os mesmos
        nas duas versoes. Quando o texto original em ingles e' diferente entre as versoes, a
        traducao vem marcada para revisar. Traducoes que este projeto ja' tem nao sao trocadas."""
        other_dir = os.path.abspath((other_dir or "").strip().strip('"'))
        if os.path.normcase(other_dir) == os.path.normcase(self.dir):
            raise ProjectError("Escolha a pasta de outro projeto.")
        if not is_project_dir(other_dir):
            raise ProjectError("Essa pasta nao tem um projeto de traducao (falta o projeto.json).")
        other = Project.open(other_dir)
        rep = {"same": 0, "changed": 0, "kept": 0, "missing": 0, "names": 0, "files": 0,
               "missing_list": [], "changed_list": []}
        cols = int(self.settings.get("cols", 48))
        maxl = int(self.settings.get("lines", 3))
        with self.lock:
            for fname, items in other.tr.items():
                f = self.by_name.get(fname)
                if f is None:
                    low = {n.lower(): n for n in self.by_name}
                    f = self.by_name.get(low.get(fname.lower(), ""))
                of = other.by_name.get(fname)
                if not items:
                    continue
                touched = False
                for key, t in items.items():
                    if not t.get("t") or t.get("auto"):
                        continue
                    e = f["_idx"].get(key) if f else None
                    if e is None:
                        rep["missing"] += 1
                        if len(rep["missing_list"]) < 200:
                            rep["missing_list"].append(f"{fname}/{key}")
                        continue
                    ft = self.tr.setdefault(f["name"], {})
                    if (ft.get(key) or {}).get("t") and not ft[key].get("auto"):
                        rep["kept"] += 1
                        continue
                    oe = of["_idx"].get(key) if of else None
                    val = t["t"]
                    if not text.is_menu(e["body"]):
                        val, _ = text.wrap(val, cols, maxl, self.charmap_codes(), self.eu)
                    st = t.get("st", "")
                    if oe is not None and oe.get("body") == e["body"]:
                        rep["same"] += 1
                    else:
                        rep["changed"] += 1
                        st = "rev"
                        if len(rep["changed_list"]) < 200:
                            rep["changed_list"].append(f"{f['name']}/{key}")
                    ft[key] = {"t": val, "st": st}
                    touched = True
                    for sf, sk in self.same.get(e["body"], ()):
                        if (sf, sk) == (f["name"], key):
                            continue
                        oft = self.tr.setdefault(sf, {})
                        o = oft.get(sk)
                        if o is None or not o.get("t") or o.get("auto"):
                            oft[sk] = {"t": val, "auto": True, "st": (o or {}).get("st", "")}
                rep["files"] += touched
            for name, value in other.names.items():
                if value and not self.names.get(name):
                    self.names[name] = value
                    rep["names"] += 1
            self.touch()
        self.save(force=True)
        return rep

    # ------------------------------------------------------------ traducao automatica
    def mt_context(self, fname: str, key: str) -> dict:
        f = self.by_name.get(fname)
        if f is None or key not in f["_idx"]:
            raise ProjectError("texto desconhecido")
        prev = None
        for e in f["entries"]:
            if e["k"] == key:
                break
            if e.get("raw") or not e["body"].strip():
                continue
            who = e.get("head") if e.get("br") else ""
            prev = ((who + ": ") if who else "") + e["body"].replace("\n", " ")
        e = f["_idx"][key]
        return {"body": e["body"], "who": (e.get("head") if e.get("br") else None) or None,
                "prev": prev, "menu": text.is_menu(e["body"])}

    def _mt_extra_glossary(self) -> List[List[str]]:
        return [[n, t] for n, t in self.names.items() if t]

    def mt_suggest(self, tr: "mt.Translator", fname: str, key: str) -> str:
        c = self.mt_context(fname, key)
        out = tr.translate(c["body"], c["who"], c["prev"], c["menu"], self._mt_extra_glossary())
        if not c["menu"]:
            out, _ = text.wrap(out, int(self.settings.get("cols", 48)), int(self.settings.get("lines", 3)),
                               self.charmap_codes(), self.eu)
        return out

    # Lote: quando parar de insistir num servico que nao responde.
    MT_MAX_SEM_RESPOSTA = 2      # falas seguidas sem resposta (servidor fora do ar ou travado)
    MT_MAX_ERROS = 5             # falas seguidas com qualquer erro

    def mt_file(self, tr: "mt.Translator", fname: str, progress=None, cancelled=lambda: False,
                clock=None) -> dict:
        """Traduz automaticamente as falas sem traducao de um arquivo (marcadas para revisar).

        Para sozinho se o servico parar de responder (MT_MAX_SEM_RESPOSTA falas seguidas), se
        der erro em MT_MAX_ERROS falas seguidas ou, na hora, se a chave for recusada ou a cota
        acabar. O que ja' foi traduzido fica salvo; rodar de novo continua das que faltam."""
        import time
        clock = clock or time.monotonic
        f = self.by_name.get(fname)
        if f is None:
            raise ProjectError("arquivo desconhecido")
        todo = []
        for e in f["entries"]:
            if e.get("raw") or e.get("dbg") or not e["body"].strip():
                continue
            if (self.translated(fname, e["k"]) or {}).get("t"):
                continue
            todo.append(e)
        done = copied = 0
        errors: List[str] = []
        n = len(todo)
        no_answer = in_a_row = 0
        stopped = ""
        spent = 0.0                  # tempo gasto nas falas mandadas ao servico
        asked = 0
        handled = 0
        for i, e in enumerate(todo):
            if cancelled():
                break
            if progress:
                label = f"Traduzindo {fname} ({i + 1} de {n})"
                if asked:
                    per = spent / asked
                    label += f" · {_fmt_secs(per)} por fala"
                    left = per * (n - i)
                    if n - i > 1 and left >= 1:
                        label += f" · faltam cerca de {_fmt_secs(left)}"
                progress(label, i, n)
            handled = i + 1
            if (self.translated(fname, e["k"]) or {}).get("t"):
                copied += 1          # preenchida por uma fala igual traduzida antes
                continue
            # a mesma fala ja' traduzida em outro lugar: reaproveita
            reuse = None
            for of, ok in self.same.get(e["body"], ()):
                t = (self.translated(of, ok) or {}).get("t")
                if t:
                    reuse = t
                    break
            t0 = clock()
            try:
                val = reuse if reuse is not None else self.mt_suggest(tr, fname, e["k"])
            except mt.MTError as exc:
                if reuse is None:
                    spent += clock() - t0
                    asked += 1
                errors.append(f"{e['k']}: {exc}")
                in_a_row += 1
                kind = getattr(exc, "kind", "")
                no_answer = no_answer + 1 if kind == "conexao" else 0
                if kind == "fatal":
                    stopped = f"o serviço recusou o pedido: {exc}"
                elif no_answer >= self.MT_MAX_SEM_RESPOSTA:
                    stopped = (f"o serviço não respondeu em {no_answer} falas seguidas: {exc}")
                elif in_a_row >= self.MT_MAX_ERROS:
                    stopped = f"{in_a_row} falas seguidas deram erro. A última: {exc}"
                if stopped:
                    break
                continue
            if reuse is None:
                spent += clock() - t0
                asked += 1
            no_answer = in_a_row = 0
            self.set_translation(fname, e["k"], val, "mt")
            if reuse is not None:
                copied += 1
            else:
                done += 1
                if done % 10 == 0:
                    self.save()
        self.save()
        remaining = sum(1 for e in todo if not (self.translated(fname, e["k"]) or {}).get("t"))
        return {"file": fname, "translated": done, "copied": copied, "total": n,
                "errors": errors[-10:], "error_count": len(errors), "cancelled": cancelled(),
                "stopped": stopped, "remaining": remaining,
                "per_line": round(spent / asked, 1) if asked else None}

    # ------------------------------------------- traducao automatica pela historia
    def story_groups(self) -> List[list]:
        """Capitulos da historia com os arquivos que existem neste projeto; o que sobra vai em
        "Outros" no fim."""
        names = {n.lower(): n for n in self.by_name}
        used, out = set(), []
        for title, files in story_order():
            fs = [names[f.lower()] for f in files if f.lower() in names]
            used.update(fs)
            if fs:
                out.append([title, fs])
        rest = sorted(n for n in self.by_name if n not in used)
        if rest:
            out.append(["Outros", rest])
        return out

    def _pending(self, fname: str) -> List[dict]:
        f = self.by_name[fname]
        return [e for e in f["entries"]
                if not (e.get("raw") or e.get("dbg") or not e["body"].strip())
                and not (self.translated(fname, e["k"]) or {}).get("t")]

    def story_info(self) -> List[dict]:
        """Por capitulo: falas sem traducao e quantos caracteres o servico vai receber (falas
        iguais contam uma vez so')."""
        seen = set()
        for fn in self.by_name:                      # falas iguais ja' traduzidas nao vao ao servico
            for e in self.by_name[fn]["entries"]:
                if (self.translated(fn, e["k"]) or {}).get("t"):
                    seen.add(e["body"])
        out = []
        for title, files in self.story_groups():
            lines = chars = 0
            for fn in files:
                for e in self._pending(fn):
                    lines += 1
                    if e["body"] not in seen:
                        seen.add(e["body"])
                        chars += len(e["body"])
            out.append({"title": title, "files": len(files), "lines": lines, "chars": chars})
        return out

    def mt_story(self, tr: "mt.Translator", first: int, last: int, progress=None,
                 cancelled=lambda: False, clock=None) -> dict:
        """Traducao automatica de todos os capitulos de first a last (contando de 0), na ordem
        da historia. Usa a mesma parada automatica do mt_file e para tudo se um arquivo parar."""
        import time
        clock = clock or time.monotonic
        groups = self.story_groups()
        first = max(0, int(first))
        last = min(len(groups) - 1, int(last))
        todo = [(gi, fn) for gi in range(first, last + 1) for fn in groups[gi][1] if self._pending(fn)]
        total = sum(len(self._pending(fn)) for _gi, fn in todo)
        base = 0
        t0 = clock()
        res = {"translated": 0, "copied": 0, "error_count": 0, "errors": [], "stopped": "",
               "cancelled": False, "files": 0, "total": total, "last_file": "", "last_chapter": ""}
        for gi, fn in todo:
            if cancelled():
                break
            title = groups[gi][0]
            n_here = len(self._pending(fn))

            def prog(_label, cur, _n, gi=gi, fn=fn, title=title):
                if not progress:
                    return
                done = base + cur
                label = (f"Capítulo {gi + 1} de {len(groups)}: {title} · "
                         f"{fn.replace('.sct', '')} · fala {done + 1} de {total}")
                if done:
                    per = (clock() - t0) / done
                    label += f" · {_fmt_secs(per)} por fala"
                    left = per * (total - done)
                    if left >= 60:
                        label += f" · faltam cerca de {_fmt_secs(left)}"
                progress(label, done, total)

            r = self.mt_file(tr, fn, progress=prog, cancelled=cancelled, clock=clock)
            base += n_here
            res["files"] += 1
            res["translated"] += r["translated"]
            res["copied"] += r["copied"]
            res["error_count"] += r["error_count"]
            res["errors"] = (res["errors"] + r["errors"])[-10:]
            res["last_file"], res["last_chapter"] = fn, title
            if r.get("stopped"):
                res["stopped"] = r["stopped"]
                break
            if r.get("cancelled"):
                break
        res["cancelled"] = bool(cancelled())
        res["remaining"] = sum(len(self._pending(fn)) for gi in range(first, last + 1)
                               for fn in groups[gi][1])
        res["per_line"] = None
        done_lines = res["translated"] + res["copied"]
        if done_lines:
            res["per_line"] = round((clock() - t0) / done_lines, 1)
        return res

    # ------------------------------------------------------------ destinos
    def targets(self) -> List[dict]:
        """Pastas onde a traducao e' gravada: a do jogo aberto e, se marcado, a do recomp."""
        out = []
        main = self.meta.get("game_root")
        if main:
            out.append(self._target(main))
        extra = self.meta.get("recomp_root")
        if extra and self.meta.get("use_recomp") and os.path.isdir(extra):
            t = self._target(extra)
            if all(os.path.normcase(t["field"]) != os.path.normcase(o["field"]) for o in out):
                out.append(t)
        return out

    def _target(self, root: str) -> dict:
        field, fnt = find_game(root)
        is_rc = recomp.is_recomp_game(root)
        tag = hashlib.sha1(os.path.normcase(os.path.abspath(field)).encode("utf-8")).hexdigest()[:8]
        fst = os.path.join(root, "sys", "fst.bin")
        return {"root": os.path.abspath(root), "field": field, "font": fnt, "recomp": is_rc, "tag": tag,
                "fst": fst if (is_rc and os.path.exists(fst)) else None,
                "manifest": os.path.join(self.dir, f"gravacao_{tag}.json"),
                "backup": os.path.join(self.dir, "copias_do_destino", tag)}

    def set_recomp(self, root: Optional[str], use: bool):
        if self.eu and (root or use):
            raise ProjectError("O recomp so' roda a versao americana; a versao europeia e' gravada "
                               "so' na pasta do jogo.")
        with self.lock:
            if root:
                gid = recomp.game_id(root)
                if gid != recomp.SUPPORTED_ID:
                    raise ProjectError("O jogo importado no recomp nao e' a versao americana (GEAE8P).")
                find_game(root)
                self.meta["recomp_root"] = os.path.abspath(root)
            self.meta["use_recomp"] = bool(use)
            self.touch()
        self.save()

    @staticmethod
    def _sha1_file(path: str) -> Optional[str]:
        try:
            with open(path, "rb") as fh:
                return hashlib.sha1(fh.read()).hexdigest()
        except OSError:
            return None

    @staticmethod
    def _load_manifest(t: dict) -> dict:
        try:
            with open(t["manifest"], encoding="utf-8") as fh:
                m = json.load(fh)
            if m.get("field") == t["field"] and isinstance(m.get("files"), dict):
                return m
        except (OSError, ValueError):
            pass
        return {"field": t["field"], "files": {}, "first": True}

    def _keep_copy(self, t: dict, rel: str, current: str, original: Optional[bytes]):
        """Antes de sobrescrever pela primeira vez um arquivo do destino que nao e' igual ao
        original guardado (outro romhack, outra traducao), guarda uma copia dele."""
        dst = os.path.join(t["backup"], rel)
        if os.path.exists(dst) or not os.path.exists(current):
            return False
        with open(current, "rb") as fh:
            cur = fh.read()
        if original is not None and cur == original:
            return False
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        _atomic_write(dst, cur)
        return True

    # ------------------------------------------------------------ gravar no jogo
    def _new_texts(self, f: dict, enc: text.Encoder, report: dict):
        tr = self.tr.get(f["name"], {})
        names = self.names
        new_sec: Dict[int, bytes] = {}
        new_foot: Dict[int, bytes] = {}
        for e in f["entries"]:
            if e.get("raw"):
                continue
            t = tr.get(e["k"], {}).get("t", "")
            head = e.get("head")
            new_head = names.get(head, head) if (head and e.get("br")) else head
            if not t and new_head == head:
                continue
            body = t if t else e["body"]
            if t:
                report["entries"] += 1
                issues = self.check_text(t)
                if issues:
                    report["long"].append({"file": f["name"], "k": e["k"], "issue": issues[0]})
            raw = enc.encode(text.GameText(new_head, bool(e.get("br")), body, e["end"], e.get("bs", "jp")))
            if e["i"] >= 0:
                new_sec[e["i"]] = raw
            else:
                new_foot[e["pos"]] = raw
        return new_sec, new_foot

    def build(self, progress=None) -> dict:
        """Grava os .sct traduzidos (e a fonte com acentos) em cada destino."""
        with self.lock:
            self.save()
            targets = self.targets()
            if not targets:
                raise ProjectError("Nenhuma pasta de destino.")
            cm = self.charmap_codes()
            enc = text.Encoder(cm, eu=self.eu)
            pad = bool(self.settings.get("keep_states"))
            report = {"entries": 0, "long": [], "errors": [], "targets": []}
            states = []
            for t in targets:
                os.makedirs(t["field"], exist_ok=True)
                m = self._load_manifest(t)
                states.append({"t": t, "m": m, "first": bool(m.pop("first", False)),
                               "r": {"root": t["root"], "recomp": t["recomp"], "written": 0, "restored": 0,
                                     "unchanged": 0, "kept": 0, "font": "", "fst": "", "note": ""}})
            n = len(self.files)
            for i, f in enumerate(self.files):
                if progress:
                    progress("Gravando " + f["name"], i, n)
                name = f["name"]
                try:
                    with open(os.path.join(self.orig_field, name), "rb") as fh:
                        orig = fh.read()
                    if f.get("error") and not f["entries"]:
                        new_sec, new_foot = {}, {}
                    else:
                        new_sec, new_foot = self._new_texts(f, enc, report)
                    plain = digest = raw = None
                    if new_sec or new_foot:
                        s = sct.SctFile(orig, name)
                        plain = s.rebuild(new_sec, new_foot, compress=False)
                        digest = hashlib.sha1(plain).hexdigest()
                    for st in states:
                        t, mf, r = st["t"], st["m"]["files"], st["r"]
                        dst = os.path.join(t["field"], name)
                        if st["first"] and self._keep_copy(t, os.path.join("field", name), dst, orig):
                            r["kept"] += 1
                        if plain is None:
                            if mf.pop(name, None) or self._sha1_file(dst) != hashlib.sha1(orig).hexdigest():
                                _atomic_write(dst, orig)
                                r["restored"] += 1
                            continue
                        do_pad = pad and t["recomp"]
                        old = mf.get(name) or {}
                        if old.get("plain") == digest and old.get("pad") == do_pad and \
                                self._sha1_file(dst) == old.get("out"):
                            r["unchanged"] += 1
                            continue
                        if raw is None:
                            # confere o arquivo novo antes de gravar: abre sem erro e mantem os links
                            chk = sct.SctFile(plain, name)
                            if chk.problems or len(chk.links) != len(s.links) or \
                                    len(chk.sections) != len(s.sections):
                                raise ProjectError("o arquivo reconstruido nao passou na conferencia")
                            raw = aklz.compress(plain) if s.was_compressed else plain
                        out = recomp.pad_to_block(raw) if do_pad else raw
                        _atomic_write(dst, out)
                        mf[name] = {"plain": digest, "out": hashlib.sha1(out).hexdigest(), "pad": do_pad}
                        r["written"] += 1
                except (sct.SctError, ProjectError, OSError, ValueError) as exc:
                    report["errors"].append({"file": name, "error": str(exc)})
            # fonte
            of = self.orig_font
            fdata = fnew = None
            if of:
                try:
                    with open(of, "rb") as fh:
                        fdata = fh.read()
                    if cm:
                        fnt = fontmod.Font(fdata)
                        failed = fontmod.apply_charmap(fnt, dict(cm))
                        fnew = fnt.build()
                        font_note = "acentos desenhados na fonte"
                        if failed:
                            font_note += " (sem desenho para: " + " ".join(failed) + ")"
                    else:
                        fnew, font_note = fdata, "fonte original"
                except (fontmod.FontError, OSError) as exc:
                    report["errors"].append({"file": os.path.basename(of), "error": str(exc)})
            for st in states:
                t, r = st["t"], st["r"]
                try:
                    if fnew is not None:
                        dstf = t["font"] or os.path.join(os.path.dirname(t["field"]), os.path.basename(of))
                        if st["first"] and self._keep_copy(t, os.path.basename(dstf), dstf, fdata):
                            r["kept"] += 1
                        if self._sha1_file(dstf) != hashlib.sha1(fnew).hexdigest():
                            _atomic_write(dstf, fnew)
                        r["font"] = font_note
                    elif cm:
                        r["font"] = "arquivo de fonte nao encontrado: os acentos vao aparecer como simbolos"
                    if t["fst"]:
                        r["fst"] = self._update_fst(t)
                    if t["recomp"]:
                        r["states"] = recomp.count_states(os.path.dirname(os.path.dirname(t["root"])))
                    _atomic_write(t["manifest"], json.dumps(st["m"]).encode("utf-8"))
                except (recomp.FstError, OSError) as exc:
                    report["errors"].append({"file": t["root"], "error": str(exc)})
                report["targets"].append(r)
            report["stripped"] = enc.stripped
            report["missing"] = enc.missing
            if progress:
                progress("Pronto", n, n)
            return report

    def _update_fst(self, t: dict) -> str:
        """Atualiza no sys/fst.bin do destino o tamanho dos arquivos que a traducao mexe.
        Parte sempre do fst.bin original, guardado na primeira gravacao."""
        keep = os.path.join(t["backup"], "fst.bin.original")
        if not os.path.exists(keep):
            os.makedirs(t["backup"], exist_ok=True)
            shutil.copy2(t["fst"], keep)
        with open(keep, "rb") as fh:
            base = fh.read()
        fst = recomp.Fst(base)
        files_dir = os.path.dirname(t["field"])
        changed = 0
        paths = [("field/" + f, os.path.join(t["field"], f)) for f in os.listdir(t["field"])
                 if f.lower().endswith(".sct")]
        if t["font"]:
            paths.append((os.path.basename(t["font"]), t["font"]))
        for rel, full in paths:
            size = os.path.getsize(full)
            old = fst.size(rel)
            if old is not None and old != size:
                fst.set_size(rel, size)
                changed += 1
        new = fst.build()
        with open(t["fst"], "rb") as fh:
            cur = fh.read()
        if new != cur:
            _atomic_write(t["fst"], new)
        if new == base:
            return "tabela de arquivos original (nenhum tamanho mudou)"
        return f"tabela de arquivos atualizada ({changed} tamanhos)"

    def restore_originals(self) -> dict:
        """Devolve os arquivos originais a cada destino."""
        with self.lock:
            out = []
            for t in self.targets():
                n = 0
                for f in os.listdir(self.orig_field):
                    src = os.path.join(self.orig_field, f)
                    dst = os.path.join(t["field"], f)
                    kept = os.path.join(t["backup"], "field", f)
                    shutil.copy2(kept if os.path.exists(kept) else src, dst)
                    n += 1
                of = self.orig_font
                if of and t["font"]:
                    kept = os.path.join(t["backup"], os.path.basename(t["font"]))
                    shutil.copy2(kept if os.path.exists(kept) else of, t["font"])
                keep_fst = os.path.join(t["backup"], "fst.bin.original")
                if t["fst"] and os.path.exists(keep_fst):
                    shutil.copy2(keep_fst, t["fst"])
                try:
                    os.remove(t["manifest"])
                except OSError:
                    pass
                out.append({"root": t["root"], "files": n})
            return {"targets": out, "restored": sum(x["files"] for x in out)}
