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
from . import intro, mt, recomp, sct, sistema, text

PROJECT_FILE = "projeto.json"
CACHE_FILE = "textos.json"
ORIG_DIR = "originais"
CACHE_VERSION = 7

CATEGORIES = [
    ("cidades", "Cidades e ilhas"),
    ("masmorras", "Masmorras"),
    ("cenas", "Cenas"),
    ("navios", "Batalhas de navio"),
    ("mundo", "Mundo aberto"),
    ("outros", "Testes e outros"),
    ("sistema", "Itens, menus e sistema"),
    ("intro", "Introdução"),
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
    "eu_slot": "en",         # versao europeia: idioma do jogo que recebe a traducao (en, es, fr, de)
    "intro_font": "uncial",  # fonte da introducao: uncial (como a americana) ou gotica (como a europeia)
    "mt_source": "en",       # versao europeia: idioma do original mandado a traducao automatica
}

EU_SLOTS = {"en": "", "es": "S", "fr": "F", "de": "G"}
EU_SLOT_NAMES = {"en": "inglês", "es": "espanhol", "fr": "francês", "de": "alemão"}

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
    def orig_extra(self) -> str:
        """Originais do que nao e' dialogo: main.dol ou .sot (sistema) e a introducao."""
        return os.path.join(self.dir, ORIG_DIR, "extras")

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
        p._ensure_extras()
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
        if p._ensure_extras():
            p.touch()
            p.save()
        p.extract(progress)
        return p

    # ------------------------------------------------------------ itens, menus e introducao
    @staticmethod
    def _game_dirs(root: str) -> Tuple[str, str]:
        """Pastas files/ e sys/ de uma extracao do jogo."""
        field, _fnt = find_game(root)
        files = os.path.dirname(field)
        return files, os.path.join(os.path.dirname(files), "sys")

    def extra_sources(self) -> List[Tuple[str, str]]:
        """(nome guardado em originais/extras, caminho relativo a pasta do jogo)."""
        if self.eu:
            out = [(n, "files/" + n) for n in sistema.EU_SOT_FILES.values()]
            out += [(n, "files/field/" + n) for n in intro.EU_FILES.values()]
        else:
            out = [("main.dol", "sys/main.dol"), (intro.US_FILE, "files/field/" + intro.US_FILE)]
        return out

    def _extra_path(self, root: str, rel: str) -> str:
        files, sysd = self._game_dirs(root)
        top, _, rest = rel.partition("/")
        return os.path.join(sysd if top == "sys" else files, *rest.split("/"))

    def _ensure_extras(self) -> bool:
        """Guarda, uma unica vez, os originais do main.dol (ou dos .sot) e da introducao.
        Arquivo que ja' nao e' o original (sha1 conhecido diferente) nao e' guardado."""
        root = self.meta.get("game_root")
        if not root or not os.path.isdir(root):
            return False
        os.makedirs(self.orig_extra, exist_ok=True)
        notes = []
        changed = False
        for name, rel in self.extra_sources():
            dst = os.path.join(self.orig_extra, name)
            if os.path.exists(dst):
                continue
            try:
                src = self._extra_path(root, rel)
            except ProjectError:
                continue
            if not os.path.exists(src):
                continue
            want = sistema.KNOWN_SHA1.get(name) or intro.KNOWN_SHA1.get(name)
            if want and self._sha1_file(src) != want:
                notes.append(name)
                continue
            shutil.copy2(src, dst)
            changed = True
            if name in self.meta.get("extras_not_original", []):
                self.meta["extras_not_original"] = [n for n in self.meta["extras_not_original"] if n != name]
        if notes:
            self.meta["extras_not_original"] = sorted(set(self.meta.get("extras_not_original", []) + notes))
            changed = True
        return changed

    def _extra_orig(self, name: str) -> Optional[bytes]:
        try:
            with open(os.path.join(self.orig_extra, name), "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def _virtual_files(self) -> List[dict]:
        out: List[dict] = []
        notes = []
        try:
            if self.eu:
                raw = self._extra_orig("english.sot")
                if raw:
                    others = {}
                    for lang, name in sistema.EU_SOT_FILES.items():
                        o = self._extra_orig(name)
                        if lang != "en" and o:
                            others[EU_SLOTS[lang]] = o
                    out += sistema.eu_files(raw, others)
            else:
                raw = self._extra_orig("main.dol")
                if raw:
                    out += sistema.us_files(raw)
                    self._sys_orig_len = {x["k"]: raw.find(b"\0", x["off"]) - x["off"]
                                          for x in sistema.us_map()["entries"]}
        except (sistema.SistemaError, OSError, ValueError) as exc:
            notes.append(f"itens e menus: {exc}")
        name = intro.file_for(self.eu, "en")
        raw = self._extra_orig(name)
        if raw:
            try:
                intro.Mld(raw)
                out += intro.entries()
            except (intro.IntroError, ValueError) as exc:
                notes.append(f"introdução: {exc}")
        for f in out:
            for e in f["entries"]:
                e["virt"] = f["virt"]
        self.extra_errors = notes
        return out

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
                    self._set_files(c["files"] + self._virtual_files())
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
        self._set_files(files + self._virtual_files())

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
        by_name = {x.name: x for x in secs} if eu else {}
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
            if eu and sec.name[:1] == "M" and n == 0:
                # as mesmas falas em espanhol, frances e alemao: a traducao pode ir para uma delas
                alt = {}
                for lang in "SFG":
                    o = by_name.get("M" + lang + sec.name[1:])
                    if o is None or o.name not in skip:
                        continue
                    try:
                        og = text.decode(s.text_bytes(o), True)
                        alt[lang] = [o.index, og.head, og.brackets, og.style, og.end, og.body]
                    except text.TextError:
                        continue
                if alt:
                    e["alt"] = alt
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

    @staticmethod
    def _skey(e: dict) -> str:
        """Chave das falas iguais: os textos de menus e da introducao so' se repetem entre si,
        nunca com os dialogos (os limites de tamanho sao outros)."""
        v = e.get("virt")
        return ("\0" + v + "\0" + e["body"]) if v else e["body"]

    def _set_files(self, files: List[dict]):
        self.files = files
        self.by_name = {f["name"]: f for f in files}
        self.same = {}
        for f in files:
            f["_idx"] = {e["k"]: e for e in f["entries"]}
            for e in f["entries"]:
                if e["body"] and not e.get("raw"):
                    self.same.setdefault(self._skey(e), []).append((f["name"], e["k"]))

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
            item = {"name": f["name"], "cat": f["cat"], "total": t, "done": d,
                    "count": len(f["entries"]), "error": f.get("error")}
            if f.get("virt"):
                item["label"] = f.get("label")
                item["virt"] = f["virt"]
            out.append(item)
        return {"files": out, "total": gt, "done": gd,
                "unique": len(self.same), "categories": CATEGORIES, "story": story_order(),
                "extra_errors": getattr(self, "extra_errors", []),
                "extras_not_original": self.meta.get("extras_not_original", [])}

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
            row["dup"] = len(self.same.get(self._skey(e), ())) if e["body"] else 0
            st_ = self.source_text(e)
            if st_:
                row["src"] = st_
            row.pop("alt", None)
            rows.append(row)
        out = {"name": fname, "cat": f["cat"], "entries": rows, "error": f.get("error")}
        if f.get("virt"):
            out["label"] = f.get("label")
            out["virt"] = f["virt"]
            if f["virt"] == "sistema" and not self.eu:
                out["pools"] = self.pool_usage(fname)
        return out

    def pool_usage(self, fname: str) -> Dict[str, dict]:
        """Blocos de textos do main.dol usados por este arquivo: espaco total e quanto os
        textos de outros arquivos ja' ocupam (cada texto conta em blocos de 4 bytes)."""
        m = sistema.us_map()
        here = {e["k"] for e in self.by_name[fname]["entries"]}
        loc = {}
        for f in self.files:
            if f.get("virt") == "sistema":
                for e in f["entries"]:
                    loc[e["k"]] = (f["name"], e)
        out = {}
        for i, p in enumerate(m["pools"]):
            if not here.intersection(p["keys"]):
                continue
            other = 0
            for k in p["keys"]:
                if k in here:
                    continue
                fn, e = loc.get(k, (None, None))
                if e is None:
                    continue          # texto do bloco que nao aparece na lista: fica como esta'
                t = (self.translated(fn, k) or {}).get("t") or e["body"]
                other += (self.sys_bytes(t) + 1 + 3) & ~3
            hidden = 0
            for k in p["keys"]:
                if k not in loc:
                    hidden += (getattr(self, "_sys_orig_len", {}).get(k, 3) + 1 + 3) & ~3
            out[str(i)] = {"cap": p["end"] - p["start"], "other": other + hidden,
                           "keys": [k for k in p["keys"] if k in here]}
        return out

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
                for of, ok in self.same.get(self._skey(e), ()):
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

    def sys_bytes(self, t: str) -> int:
        """Tamanho em bytes de um texto de menu da versao americana."""
        return len(sistema.UsEncoder(self.charmap_codes()).encode(t))

    def limit_text(self, e: dict) -> str:
        lim = e.get("lim") or {}
        if e.get("virt") == "intro":
            return "introdução: 2 linhas curtas, desenhadas como imagem"
        parts = []
        if lim.get("bytes"):
            parts.append(f"no máximo {lim['bytes']} letras")
        if lim.get("lines", 1) > 1:
            parts.append(f"até {lim['lines']} linhas de {lim.get('cols')} colunas")
        elif lim.get("cols"):
            parts.append(f"uma linha (o original mais longo desta lista tem {lim['cols']} colunas)")
        if e.get("pool") is not None:
            parts.append("divide o espaço com os outros textos do mesmo bloco")
        return "menu: " + "; ".join(parts) if parts else "menu"

    def fit(self, e: dict, val: str) -> str:
        """Quebra as linhas para caber: dialogos na caixa de dialogo, menus no limite deles."""
        if not val:
            return val
        if e.get("virt") == "intro":
            return val
        if e.get("virt"):
            lim = e.get("lim") or {}
            if lim.get("lines", 1) > 1 and lim.get("cols"):
                val, _ = text.wrap(val, int(lim["cols"]), int(lim["lines"]), self.charmap_codes(), self.eu)
            return val
        if text.is_menu(e["body"]):
            return val
        val, _ = text.wrap(val, int(self.settings.get("cols", 48)), int(self.settings.get("lines", 3)),
                           self.charmap_codes(), self.eu)
        return val

    def check_text(self, body: str, e: Optional[dict] = None) -> List[str]:
        if e is not None and e.get("virt"):
            return self._check_virtual(body, e)
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

    def _check_virtual(self, body: str, e: dict) -> List[str]:
        lim = e.get("lim") or {}
        issues = []
        if e.get("virt") == "intro":
            n = len([l for l in body.split("\n") if l.strip()])
            if n > 3:
                issues.append(f"{n} linhas; a página comporta 2 ou 3")
            return issues
        lines = body.split("\n")
        if len(lines) > lim.get("lines", 1):
            issues.append(f"{len(lines)} linhas (o original usa até {lim.get('lines', 1)})")
        cols = lim.get("cols")
        if cols and lim.get("lines", 1) > 1:
            for ln in lines:
                if len(ln) > cols:
                    issues.append(f"linha com {len(ln)} colunas (limite {cols})")
        if lim.get("bytes") and not self.eu:
            n = self.sys_bytes(body)
            if n > lim["bytes"]:
                issues.append(f"{n} letras; cabem {lim['bytes']}")
        if sistema.placeholders(body) != sistema.placeholders(e["body"]):
            issues.append("mantenha os códigos do original (" + " ".join(sistema.placeholders(e["body"])) + ")")
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
                sk = self._skey(e)
                if sk not in seen:
                    seen.add(sk)
                    t = tr.get(e["k"], {})
                    if e.get("virt"):
                        kind = self.limit_text(e)
                    else:
                        kind = ("menu: mantenha uma opcao por linha" if text.is_menu(body)
                                else f"fala: ate {maxl} linhas de {cols} colunas")
                    w.writerow([f["name"], e["k"], who or "", kind, len(self.same.get(self._skey(e), ())) or 1,
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
                if val:
                    nv = self.fit(e, val)
                    wrapped += nv != val
                    val = nv
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
                    for of, ok in self.same.get(self._skey(e), ()):
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
                    tf = f
                    e = tf["_idx"].get(key) if tf else None
                    oe0 = of["_idx"].get(key) if of else None
                    if e is None and oe0 is not None and oe0.get("virt"):
                        # itens e menus: as chaves mudam entre as versoes; liga pelo texto ingles
                        hits = self.same.get(self._skey(oe0), [])
                        if hits:
                            tf = self.by_name[hits[0][0]]
                            key = hits[0][1]
                            e = tf["_idx"][key]
                    if e is None:
                        rep["missing"] += 1
                        if len(rep["missing_list"]) < 200:
                            rep["missing_list"].append(f"{fname}/{key}")
                        continue
                    ft = self.tr.setdefault(tf["name"], {})
                    if (ft.get(key) or {}).get("t") and not ft[key].get("auto"):
                        rep["kept"] += 1
                        continue
                    oe = oe0 if oe0 is not None and oe0.get("virt") else (of["_idx"].get(key) if of else None)
                    val = self.fit(e, t["t"])
                    st = t.get("st", "")
                    if oe is not None and oe.get("body") == e["body"]:
                        rep["same"] += 1
                    else:
                        rep["changed"] += 1
                        st = "rev"
                        if len(rep["changed_list"]) < 200:
                            rep["changed_list"].append(f"{tf['name']}/{key}")
                    ft[key] = {"t": val, "st": st}
                    touched = True
                    for sf, sk in self.same.get(self._skey(e), ()):
                        if (sf, sk) == (tf["name"], key):
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
        if f.get("virt"):
            e = f["_idx"][key]
            return {"body": e["body"], "who": None, "prev": None, "menu": False, "note": self._mt_note(f, e)}
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

    def mt_source(self) -> str:
        """Idioma do original mandado a traducao automatica (so' na versao europeia)."""
        src = self.settings.get("mt_source") or "en"
        return src if self.eu and src in EU_SLOTS else "en"

    def source_text(self, e: dict) -> Optional[str]:
        """O mesmo texto no idioma escolhido como origem (espanhol, frances ou alemao)."""
        src = self.mt_source()
        if src == "en":
            return None
        letter = EU_SLOTS[src]
        alt = (e.get("alt") or {}).get(letter)
        if alt and len(alt) > 5 and alt[5].strip():
            return alt[5]
        t = (e.get("src") or {}).get(letter)
        return t if t and t.strip() else None

    def _mt_note(self, f: dict, e: dict) -> str:
        if f.get("virt") == "intro":
            return ("introdução do jogo, texto poético mostrado em uma página; responda com 2 linhas "
                    "curtas separadas por quebra de linha, no mesmo tom do original")
        lim = e.get("lim") or {}
        what = f"{f.get('label', '')}, {e.get('sec', '')}".strip(", ")
        note = f"menu do jogo ({what}). Não é fala de personagem."
        if lim.get("bytes"):
            note += f" Use no máximo {lim['bytes']} letras: abrevie se precisar."
        elif lim.get("lines", 1) == 1 and lim.get("cols"):
            note += f" Texto curto, de preferência até {lim['cols']} letras."
        if e["body"] != e["body"].strip(" "):
            note += " Os espaços no começo e no fim do original servem para centralizar; não os inclua."
        return note

    def mt_suggest(self, tr: "mt.Translator", fname: str, key: str) -> str:
        c = self.mt_context(fname, key)
        f = self.by_name[fname]
        e = f["_idx"][key]
        src_text = self.source_text(e)
        src = self.mt_source() if src_text else "en"
        if c.get("note"):
            body = (src_text or c["body"]).strip(" ")
            out = tr.translate(body, None, None, False, self._mt_extra_glossary(), note=c["note"],
                               src=src, gloss_text=c["body"])
            if f.get("virt") == "intro":
                if "\n" not in out:
                    out, _ = text.wrap(out, max(14, len(out) // 2 + 2), 3)
                return out
            out = out.replace("\n", " ") if (e.get("lim") or {}).get("lines", 1) == 1 else out
            pad = len(e["body"]) - len(e["body"].lstrip(" "))
            if pad and (e.get("lim") or {}).get("cols"):
                # original centralizado com espacos: centraliza a traducao na mesma largura
                w = len(e["body"])
                if len(out) < w:
                    left = (w - len(out)) // 2
                    out = " " * left + out + " " * (w - len(out) - left)
            return self.fit(e, out)
        if src_text and c["menu"] and src_text.count("\n") != c["body"].count("\n"):
            src_text = None          # menu com outra quantidade de opcoes: vai pelo ingles
        if src_text:
            out = tr.translate(src_text, c["who"], c["prev"], c["menu"], self._mt_extra_glossary(),
                               src=src, gloss_text=c["body"])
        else:
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
            for of, ok in self.same.get(self._skey(e), ()):
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

    def intro_page(self, n: int, t: Optional[str] = None, font: Optional[str] = None) -> bytes:
        """Imagem (PNG) de uma pagina da introducao: a original ou, com t, desenhada com t."""
        if not intro.have_pillow():
            raise ProjectError("Falta o Pillow para mostrar a introdução (o .exe já vem com ele).")
        raw = self._extra_orig(intro.file_for(self.eu, (self.settings.get("eu_slot") or "en") if self.eu else ""))
        if raw is None:
            raw = self._extra_orig(intro.file_for(self.eu, "en"))
        if raw is None:
            raise ProjectError("A introdução não foi encontrada na pasta do jogo.")
        m = intro.Mld(raw)
        if not 0 <= n < len(m.tex):
            raise ProjectError("página inexistente")
        if t:
            return intro.preview_png(m.page(n), t, font or self.settings.get("intro_font") or "uncial")
        return intro.page_png(m, n)

    MT_NAME_NOTE = ("nome de quem fala, mostrado acima da caixa de diálogo. Nomes próprios de pessoas, "
                    "navios e lugares ficam iguais; traduza cargos, profissões e descrições (ex.: "
                    "'Valuan Soldier' = 'Soldado Valuano', 'Old Man' = 'Velho'). Responda só com o nome.")

    def mt_names(self, tr: "mt.Translator", progress=None, cancelled=lambda: False) -> dict:
        """Traducao automatica dos nomes de quem fala que ainda nao tem traducao. Quando o
        servico devolve o mesmo nome (nome proprio), ele continua sem traducao."""
        todo = [n["name"] for n in self.name_list() if not n["t"] and not text.has_japanese(n["name"])
                and n["name"].strip()]
        done = same = 0
        errors: List[str] = []
        in_a_row = no_answer = 0
        stopped = ""
        for i, name in enumerate(todo):
            if cancelled():
                break
            if progress:
                progress(f"Traduzindo nomes ({i + 1} de {len(todo)}): {name}", i, len(todo))
            try:
                out = tr.translate(name, None, None, False, self._mt_extra_glossary(), note=self.MT_NAME_NOTE)
            except mt.MTError as exc:
                errors.append(f"{name}: {exc}")
                in_a_row += 1
                no_answer = no_answer + 1 if getattr(exc, "kind", "") == "conexao" else 0
                if getattr(exc, "kind", "") == "fatal":
                    stopped = f"o serviço recusou o pedido: {exc}"
                elif no_answer >= self.MT_MAX_SEM_RESPOSTA or in_a_row >= self.MT_MAX_ERROS:
                    stopped = f"o serviço falhou em {in_a_row} nomes seguidos: {exc}"
                if stopped:
                    break
                continue
            in_a_row = no_answer = 0
            out = out.replace("\n", " ").strip().strip('"“”')
            if not out or out.casefold() == name.casefold() or len(out) > max(30, 2 * len(name)):
                same += 1
                continue
            self.set_name(name, out)
            done += 1
        self.save()
        return {"translated": done, "kept": same, "total": len(todo), "errors": errors[-10:],
                "error_count": len(errors), "stopped": stopped, "cancelled": cancelled()}

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
        rest = sorted(n for n in self.by_name if n not in used and not self.by_name[n].get("virt"))
        if rest:
            out.append(["Outros", rest])
        for cat, label in CATEGORIES:
            fs = [f["name"] for f in self.files if f.get("virt") and f["cat"] == cat]
            if fs:
                out.append([label, fs])
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
    def eu_slot(self) -> str:
        """Letra do idioma europeu que recebe a traducao ("" = ingles)."""
        if not self.eu:
            return ""
        return EU_SLOTS.get(self.settings.get("eu_slot") or "en", "")

    def _new_texts(self, f: dict, enc: text.Encoder, report: dict):
        tr = self.tr.get(f["name"], {})
        names = self.names
        new_sec: Dict[int, bytes] = {}
        new_foot: Dict[int, bytes] = {}
        slot = self.eu_slot()
        for e in f["entries"]:
            if e.get("raw"):
                continue
            t = tr.get(e["k"], {}).get("t", "")
            if slot and e["i"] >= 0:
                # versao europeia, traducao no lugar de outro idioma: so' as falas traduzidas
                # mudam; o resto continua no idioma original desse lugar
                alt = (e.get("alt") or {}).get(slot)
                if not t or not alt:
                    continue
                idx, ohead, obr, ostyle, oend = alt[:5]
                head = e.get("head")
                new_head = names.get(head) if (head and e.get("br") and names.get(head)) else ohead
                report["entries"] += 1
                issues = self.check_text(t)
                if issues:
                    report["long"].append({"file": f["name"], "k": e["k"], "issue": issues[0]})
                new_sec[idx] = enc.encode(text.GameText(new_head, bool(obr), t, oend, ostyle))
                continue
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
            sct_files = [f for f in self.files if not f.get("virt")]
            n = len(sct_files)
            for i, f in enumerate(sct_files):
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
            # itens, menus e introducao
            if progress:
                progress("Gravando itens, menus e a introdução", n, n)
            self._build_extras(states, report, cm)
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
            for ch, k in (report.pop("stripped_sys", None) or {}).items():
                report["stripped"][ch] = report["stripped"].get(ch, 0) + k
            extra_missing = report.get("missing") or {}
            report["missing"] = dict(enc.missing)
            for ch, k in extra_missing.items():
                report["missing"][ch] = report["missing"].get(ch, 0) + k
            if progress:
                progress("Pronto", n, n)
            return report

    def _extra_outputs(self, report: dict, cm: Dict[str, int]) -> List[Tuple[str, str, Optional[bytes]]]:
        """(nome do original, caminho relativo no jogo, conteudo novo ou None = original)."""
        out = []
        sys_tr: Dict[str, str] = {}
        sys_entries: Dict[str, dict] = {}
        intro_tr: Dict[int, str] = {}
        for f in self.files:
            v = f.get("virt")
            if not v:
                continue
            tr = self.tr.get(f["name"], {})
            for e in f["entries"]:
                t = tr.get(e["k"], {}).get("t", "")
                if not t:
                    continue
                if v == "intro":
                    intro_tr[e["page"]] = t
                else:
                    sys_tr[e["tab"] if self.eu else e["k"]] = t
                    sys_entries[e["tab"] if self.eu else e["k"]] = (f, e)
        long = report["long"]
        # sistema
        if self.eu:
            slot = self.settings.get("eu_slot") or "en"
            en = self._extra_orig("english.sot")
            for lang, name in sistema.EU_SOT_FILES.items():
                orig = self._extra_orig(name)
                if orig is None or en is None:
                    continue
                new = None
                if lang == slot and sys_tr:
                    r = {"entries": 0, "missing": {}}
                    new = sistema.build_eu(orig, en, sys_tr, r)
                    report["entries"] += r["entries"]
                    for ch, k in r["missing"].items():
                        report.setdefault("missing", {})
                        report["missing"][ch] = report["missing"].get(ch, 0) + k
                    if len(new) > 135308:
                        report["errors"].append({"file": name, "error": "ficou maior que o maior .sot original "
                                                 "(o alemão); se o jogo travar nos menus, encurte os textos"})
                out.append((name, "files/" + name, new))
        else:
            orig = self._extra_orig("main.dol")
            if orig is not None:
                new = None
                if sys_tr:
                    enc = sistema.UsEncoder(cm)
                    r = {"entries": 0, "long": []}
                    new = sistema.build_us(orig, sys_tr, enc, r)
                    report["entries"] += r["entries"]
                    for x in r["long"]:
                        f, e = sys_entries[x["k"]]
                        long.append({"file": f["name"], "k": x["k"], "issue": x["issue"] + " (ficou em inglês)"})
                    for ch, k in enc.stripped.items():
                        report.setdefault("stripped_sys", {})
                        report["stripped_sys"][ch] = report["stripped_sys"].get(ch, 0) + k
                out.append(("main.dol", "sys/main.dol", new))
        # introducao
        slot = (self.settings.get("eu_slot") or "en") if self.eu else ""
        names = intro.EU_FILES.items() if self.eu else [("", intro.US_FILE)]
        for lang, name in names:
            orig = self._extra_orig(name)
            if orig is None:
                continue
            new = None
            if intro_tr and lang == slot:
                if not intro.have_pillow():
                    report["errors"].append({"file": name, "error": "falta o Pillow para desenhar a introdução"})
                else:
                    new = intro.build(orig, intro_tr, self.settings.get("intro_font") or "uncial")
                    report["intro"] = len(intro_tr)
            out.append((name, "files/field/" + name, new))
        return out

    def _build_extras(self, states: List[dict], report: dict, cm: Dict[str, int]):
        try:
            outs = self._extra_outputs(report, cm)
        except (sistema.SistemaError, intro.IntroError, OSError, ValueError) as exc:
            report["errors"].append({"file": "itens, menus e introdução", "error": str(exc)})
            return
        for name, rel, new in outs:
            orig = self._extra_orig(name)
            digest = hashlib.sha1(new).hexdigest() if new is not None else None
            for st in states:
                t, mf, r = st["t"], st["m"]["files"], st["r"]
                try:
                    dst = self._extra_path(t["root"], rel)
                except ProjectError:
                    continue
                if not os.path.isdir(os.path.dirname(dst)):
                    continue
                try:
                    if st["first"] and self._keep_copy(t, rel, dst, orig):
                        r["kept"] += 1
                    if new is None:
                        if mf.pop(rel, None) or (os.path.exists(dst) and
                                                 self._sha1_file(dst) != hashlib.sha1(orig).hexdigest()):
                            _atomic_write(dst, orig)
                            r["restored"] += 1
                        continue
                    old = mf.get(rel) or {}
                    if old.get("plain") == digest and self._sha1_file(dst) == digest:
                        r["unchanged"] += 1
                        continue
                    _atomic_write(dst, new)
                    mf[rel] = {"plain": digest, "out": digest, "pad": False}
                    r["written"] += 1
                except OSError as exc:
                    report["errors"].append({"file": rel, "error": str(exc)})

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
        for name, rel in self.extra_sources():
            if rel.startswith("files/"):
                full = os.path.join(files_dir, *rel[len("files/"):].split("/"))
                if os.path.exists(full):
                    paths.append((rel[len("files/"):], full))
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
                for name, rel in self.extra_sources():
                    src = os.path.join(self.orig_extra, name)
                    if not os.path.exists(src):
                        continue
                    try:
                        dst = self._extra_path(t["root"], rel)
                    except ProjectError:
                        continue
                    kept = os.path.join(t["backup"], *rel.split("/"))
                    if os.path.isdir(os.path.dirname(dst)):
                        shutil.copy2(kept if os.path.exists(kept) else src, dst)
                        n += 1
                keep_fst = os.path.join(t["backup"], "fst.bin.original")
                if t["fst"] and os.path.exists(keep_fst):
                    shutil.copy2(keep_fst, t["fst"])
                try:
                    os.remove(t["manifest"])
                except OSError:
                    pass
                out.append({"root": t["root"], "files": n})
            return {"targets": out, "restored": sum(x["files"] for x in out)}
