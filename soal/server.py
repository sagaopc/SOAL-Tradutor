"""Servidor local: entrega a interface (web/index.html) e a API usada por ela.

So' aceita conexoes da propria maquina (127.0.0.1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import font as fontmod
from . import project as pj
from . import janela, mt, recomp, text

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".soal_tradutor.json")
VERSION = "0.5.0"


class App:
    def __init__(self):
        self.project: Optional[pj.Project] = None
        self.job = {"running": False, "label": "", "cur": 0, "total": 0, "error": None,
                    "result": None, "kind": ""}
        self.cancel = False
        self.job_lock = threading.Lock()
        self.config = self._load_config()
        self._glyph_cache = None
        self.last_ping = 0.0
        threading.Thread(target=self._autosave, daemon=True).start()

    # --------------------------------------------------------------- config
    def _load_config(self) -> dict:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                c = json.load(fh)
                if isinstance(c, dict):
                    return c
        except (OSError, ValueError):
            pass
        return {"recent": []}

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.config, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def _remember(self, p: pj.Project):
        rec = [r for r in self.config.get("recent", []) if r.get("dir") != p.dir]
        rec.insert(0, {"dir": p.dir, "game": p.meta.get("game_root", "")})
        self.config["recent"] = rec[:6]
        self._save_config()

    def _autosave(self):
        while True:
            time.sleep(2.0)
            p = self.project
            if p is not None:
                try:
                    p.save()
                except OSError:
                    pass

    # ----------------------------------------------------------------- jobs
    def _progress(self, label: str, cur: int, total: int):
        self.job.update(label=label, cur=cur, total=total)

    def start_job(self, kind: str, fn):
        with self.job_lock:
            if self.job["running"]:
                raise pj.ProjectError("Ja' existe uma tarefa em andamento.")
            self.job.update(running=True, label="Preparando", cur=0, total=0, error=None,
                            result=None, kind=kind)
            self.cancel = False

        def run():
            try:
                self.job["result"] = fn()
            except (pj.ProjectError, OSError, mt.MTError) as exc:
                self.job["error"] = str(exc)
            except Exception as exc:  # erro inesperado: mostra na tela em vez de sumir
                traceback.print_exc()
                self.job["error"] = f"Erro inesperado: {exc}"
            finally:
                self.job["running"] = False

        threading.Thread(target=run, daemon=True).start()

    def open_game(self, game_root: str):
        def fn():
            p = pj.Project.create_or_open(game_root, progress=self._progress)
            self.project = p
            self._glyph_cache = None
            self._remember(p)
            return {"opened": p.dir}
        self.start_job("open", fn)

    def open_project(self, project_dir: str):
        def fn():
            p = pj.Project.open(project_dir, progress=self._progress)
            self.project = p
            self._glyph_cache = None
            self._remember(p)
            return {"opened": p.dir}
        self.start_job("open", fn)

    def build(self):
        p = self.need()
        self.start_job("build", lambda: p.build(progress=self._progress))

    # ------------------------------------------------------- traducao automatica
    def mt_cfg(self) -> dict:
        c = self.config.get("mt")
        return c if isinstance(c, dict) else {}

    def translator(self) -> "mt.Translator":
        return mt.Translator(self.mt_cfg())

    def mt_file(self, fname: str):
        p = self.need()
        tr = self.translator()
        self.start_job("mt", lambda: p.mt_file(tr, fname, progress=self._progress,
                                               cancelled=lambda: self.cancel))

    def need(self) -> pj.Project:
        if self.project is None:
            raise pj.ProjectError("Nenhum projeto aberto.")
        return self.project

    # ------------------------------------------------------------- consultas
    def state(self) -> dict:
        p = self.project
        try:
            found = recomp.find_install(self.config.get("recomp_hint"))
        except OSError:
            found = None
        out = {"version": VERSION, "job": dict(self.job), "recent": self.config.get("recent", []),
               "project": None, "recomp": found}
        if p is not None:
            if found and found["supported"] and not p.meta.get("recomp_root"):
                # lembra onde o recomp esta'; gravar nele continua sendo escolha do usuario
                p.meta["recomp_root"] = found["game_root"]
                p.touch()
            out["project"] = {
                "dir": p.dir, "game_root": p.meta.get("game_root"), "game_field": p.meta.get("game_field"),
                "has_font": bool(p.orig_font), "settings": p.settings,
                "free_slots": pj.FREE_SLOTS, "summary": p.summary(),
                "not_original": p.meta.get("not_original") or [],
                "is_recomp": recomp.is_recomp_game(p.meta.get("game_root") or ""),
                "recomp_root": p.meta.get("recomp_root"), "use_recomp": bool(p.meta.get("use_recomp")),
                "targets": [{"root": t["root"], "recomp": t["recomp"]} for t in p.targets()],
            }
        return out

    def glyphs(self) -> dict:
        """Desenhos da fonte do jogo (12x24, um digito hexadecimal por pixel) para a previa."""
        p = self.need()
        if self._glyph_cache is not None:
            return self._glyph_cache
        out = {"w": fontmod.HALF, "h": fontmod.CELL, "glyphs": {}, "ok": False}
        of = p.orig_font
        if of:
            try:
                with open(of, "rb") as fh:
                    fnt = fontmod.Font(fh.read())

                def pack(g):
                    return "".join("%x" % v for row in g for v in row)
                for code in range(0x21, 0x7F):
                    ch = chr(code)
                    if code == 0x5B:
                        ch = text.LQUOTE
                    elif code == 0x5D:
                        ch = text.RQUOTE
                    elif code == 0x5C:
                        continue
                    out["glyphs"][ch] = pack(fnt.glyph(code))
                accents = {}
                for ch in "áàâãäéèêíìîóòôõö" \
                          "úùûüçñÁÀÂÃÉÊÍÓ" \
                          "ÔÕÚÜÇÑ":
                    g = fontmod.accented_glyph(fnt, ch)
                    if g:
                        accents[ch] = pack(g)
                out["accents"] = accents
                out["ok"] = True
            except (fontmod.FontError, OSError):
                pass
        self._glyph_cache = out
        return out


def pick_folder() -> Optional[str]:
    """Abre a janela de escolher pasta do sistema num processo separado (o tkinter precisa
    da linha principal do programa). No .exe, o proprio executavel faz esse papel."""
    import tempfile
    fd, out = tempfile.mkstemp(prefix="soal_pasta_", suffix=".txt")
    os.close(fd)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--escolher-pasta", out]
    else:
        exe = sys.executable
        if sys.platform.startswith("win"):
            w = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(w):
                exe = w
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [exe, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from soal import picker; picker.run(sys.argv[2])",
               root, out]
    try:
        subprocess.run(cmd, timeout=600, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=flags)
        with open(out, encoding="utf-8") as fh:
            path = fh.read().strip()
        return os.path.normpath(path) if path else None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SOALTradutor/" + VERSION

        def log_message(self, fmt, *args):  # silencioso
            pass

        # ----------------------------------------------------------- respostas
        def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _local(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        # ----------------------------------------------------------------- GET
        def do_GET(self):
            if not self._local():
                return self._send(403, b"forbidden", "text/plain")
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            try:
                if u.path in ("/", "/index.html"):
                    with open(os.path.join(WEB_DIR, "index.html"), "rb") as fh:
                        return self._send(200, fh.read(), "text/html; charset=utf-8")
                if u.path == "/api/state":
                    return self._json(app.state())
                if u.path == "/api/job":
                    return self._json(app.job)
                if u.path == "/api/ping":
                    app.last_ping = time.time()
                    return self._json({"ok": True})
                if u.path == "/api/file":
                    return self._json(app.need().file_entries(q.get("name", [""])[0]))
                if u.path == "/api/search":
                    return self._json({"results": app.need().search(q.get("q", [""])[0])})
                if u.path == "/api/names":
                    return self._json({"names": app.need().name_list()})
                if u.path == "/api/mt":
                    return self._json(mt.public_config(app.mt_cfg()))
                if u.path == "/api/glyphs":
                    return self._json(app.glyphs())
                if u.path == "/api/export_unicas.csv":
                    data = app.need().export_unique_csv()
                    return self._send(200, data, "text/csv; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="soal_textos_para_traduzir.csv"'})
                if u.path == "/api/export.csv":
                    data = app.need().export_csv()
                    return self._send(200, data, "text/csv; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="soal_traducao.csv"'})
                return self._send(404, b"not found", "text/plain")
            except pj.ProjectError as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception as exc:
                traceback.print_exc()
                return self._json({"error": f"Erro inesperado: {exc}"}, 500)

        # ---------------------------------------------------------------- POST
        def do_POST(self):
            if not self._local() or self.headers.get("X-SOAL") != "1":
                return self._send(403, b"forbidden", "text/plain")
            u = urllib.parse.urlparse(self.path)
            raw = self._body()
            try:
                if u.path == "/api/import":
                    return self._json(app.need().import_csv(raw))
                data = json.loads(raw.decode("utf-8")) if raw else {}
                if u.path == "/api/pick":
                    return self._json({"path": pick_folder()})
                if u.path == "/api/open":
                    if data.get("project_dir"):
                        app.open_project(data["project_dir"])
                    else:
                        root = (data.get("game_root") or "").strip().strip('"')
                        if not root or not os.path.isdir(root):
                            raise pj.ProjectError("Essa pasta nao existe. Confira o caminho.")
                        app.open_game(root)
                    return self._json({"ok": True})
                if u.path == "/api/save":
                    r = app.need().set_translation(data["file"], data["k"], data.get("t", ""), data.get("st"))
                    return self._json(r)
                if u.path == "/api/status":
                    app.need().set_status(data["file"], data["k"], data.get("st", ""))
                    return self._json({"ok": True})
                if u.path == "/api/name":
                    app.need().set_name(data["name"], data.get("t", ""))
                    return self._json({"ok": True})
                if u.path == "/api/settings":
                    p = app.need()
                    with p.lock:
                        st = p.settings
                        if "cols" in data:
                            st["cols"] = max(10, min(80, int(data["cols"])))
                        if "lines" in data:
                            st["lines"] = max(1, min(8, int(data["lines"])))
                        if data.get("accents") in ("font", "strip"):
                            st["accents"] = data["accents"]
                        if "autofill" in data:
                            st["autofill"] = bool(data["autofill"])
                        if "keep_states" in data:
                            st["keep_states"] = bool(data["keep_states"])
                        if isinstance(data.get("charmap"), dict):
                            cm = {}
                            used = set()
                            for ch, sym in data["charmap"].items():
                                if (isinstance(ch, str) and isinstance(sym, str) and len(ch) == 1
                                        and len(sym) == 1 and sym in pj.FREE_SLOTS and sym not in used):
                                    cm[ch] = sym
                                    used.add(sym)
                            st["charmap"] = cm
                        p.touch()
                    p.save()
                    return self._json({"settings": p.settings})
                if u.path == "/api/mt/config":
                    cur = dict(app.mt_cfg())
                    prov = data.get("provider", "")
                    if prov and prov not in mt.PROVIDERS:
                        raise pj.ProjectError("serviço desconhecido")
                    if prov != cur.get("provider"):
                        cur["key"] = ""          # chave de outro servico nao serve
                    cur["provider"] = prov
                    for k in ("url", "model"):
                        if k in data:
                            cur[k] = str(data[k]).strip()
                    if data.get("key"):
                        cur["key"] = str(data["key"]).strip()
                    if data.get("clear_key"):
                        cur["key"] = ""
                    app.config["mt"] = cur
                    app._save_config()
                    return self._json(mt.public_config(cur))
                if u.path == "/api/mt/test":
                    t = app.translator().translate("Hey, Fina! How are you feeling?\nLooks like it's going to be a piece of cake.",
                                                   "Vyse", None, False)
                    return self._json({"t": t})
                if u.path == "/api/mt/one":
                    p = app.need()
                    t = p.mt_suggest(app.translator(), data["file"], data["k"])
                    r = p.set_translation(data["file"], data["k"], t, "mt")
                    return self._json({"t": t, "filled": r["filled"]})
                if u.path == "/api/mt/file":
                    app.mt_file(data["file"])
                    return self._json({"ok": True})
                if u.path == "/api/job/cancel":
                    app.cancel = True
                    return self._json({"ok": True})
                if u.path == "/api/recomp":
                    root = (data.get("root") or "").strip().strip('"')
                    if root:
                        found = recomp.find_install(root)
                        if not found:
                            raise pj.ProjectError(
                                "Nao achei um jogo importado pelo recomp nessa pasta. Indique a pasta de "
                                "dados do port (a que tem 'games' e 'StateSaves') ou a pasta do programa.")
                        app.config["recomp_hint"] = root
                        app._save_config()
                        root = found["game_root"]
                    app.need().set_recomp(root or None, bool(data.get("use")))
                    return self._json({"ok": True})
                if u.path == "/api/build":
                    app.build()
                    return self._json({"ok": True})
                if u.path == "/api/restore":
                    return self._json(app.need().restore_originals())
                if u.path == "/api/close":
                    if app.project is not None:
                        app.project.save()
                    app.project = None
                    return self._json({"ok": True})
                return self._send(404, b"not found", "text/plain")
            except (pj.ProjectError, mt.MTError, KeyError, ValueError) as exc:
                msg = str(exc) if isinstance(exc, (pj.ProjectError, mt.MTError)) else f"Pedido invalido ({exc})"
                return self._json({"error": msg}, 400)
            except Exception as exc:
                traceback.print_exc()
                return self._json({"error": f"Erro inesperado: {exc}"}, 500)

    return Handler


def serve(port: int = 8787, open_browser: bool = True, reopen_last: bool = True, window: bool = True):
    """window=True abre numa janela propria (Edge/Chrome no modo aplicativo) e encerra quando
    ela fecha. Sem Edge/Chrome, ou com window=False, abre no navegador padrao."""
    app = App()
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(app))
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("Nao consegui abrir uma porta local para a interface.")
    url = f"http://127.0.0.1:{port}/"
    if reopen_last:
        rec = app.config.get("recent") or []
        if rec and os.path.exists(os.path.join(rec[0].get("dir", ""), pj.PROJECT_FILE)):
            try:
                app.open_project(rec[0]["dir"])
            except pj.ProjectError:
                pass
    print("SOAL Tradutor", VERSION)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    proc = None
    started = time.time()
    if open_browser and window:
        proc = janela.open_window(url)
        if proc is None:
            print("Edge/Chrome nao encontrado: abrindo no navegador padrao.")
    if open_browser and proc is None:
        import webbrowser
        webbrowser.open(url)
    print("Interface em", url)
    try:
        while True:
            time.sleep(1.0)
            if proc is not None and proc.poll() is not None:
                if time.time() - started > 3:
                    break                        # a janela foi fechada
                proc = None                      # o Edge passou a janela para outro processo
            if proc is None and open_browser and window and app.last_ping:
                # sem processo para acompanhar: encerra quando a pagina para de dar sinal
                if time.time() - app.last_ping > 150 and not app.job.get("running"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if app.project is not None:
            try:
                app.project.save()
            except OSError:
                pass
        httpd.shutdown()
        httpd.server_close()
