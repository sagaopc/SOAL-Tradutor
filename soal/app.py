"""Ponto de entrada da versao com janela (SOAL Tradutor.pyw e SOAL Tradutor.exe)."""
import json
import os
import sys
import traceback

LOG = os.path.join(os.path.expanduser("~"), ".soal_tradutor.log")


def _avisar(msg: str) -> None:
    try:
        import tkinter
        import tkinter.messagebox
        r = tkinter.Tk()
        r.withdraw()
        tkinter.messagebox.showerror("SOAL Tradutor", msg)
        r.destroy()
    except Exception:
        pass


def verificar_instalacao(out_path: str) -> int:
    """Confere se o pacote (inclusive o .exe) tem tudo o que precisa. Usado na compilacao."""
    linhas, ok = [], True

    def item(nome, fn):
        nonlocal ok
        try:
            r = fn()
            linhas.append(f"ok    {nome}" + (f": {r}" if r else ""))
        except Exception as exc:
            ok = False
            linhas.append(f"FALHA {nome}: {exc!r}")
    from soal import aklz, font, mt, project, recomp, sct, server, text  # noqa: F401
    item("interface", lambda: os.path.getsize(os.path.join(server.WEB_DIR, "index.html")))
    item("tabela de instrucoes", lambda: len(sct.instruction_table()))
    item("glossario", lambda: len(mt.GLOSSARY))
    item("originais conhecidos", lambda: len(json.load(open(os.path.join(os.path.dirname(sct.__file__), "data",
                                                                    "originais_geae8p.json"), encoding="utf-8"))["files"]))
    item("compressao AKLZ", lambda: aklz.decompress(aklz.compress(b"Skies of Arcadia " * 50)) == b"Skies of Arcadia " * 50 or 1 / 0)
    item("texto do jogo", lambda: text.decode(b"\\h(\x81\x73Vyse\x81\x74)Hey\x7fFina.\\e").body)
    item("tkinter", lambda: __import__("tkinter.filedialog") and "")
    item("ssl", lambda: __import__("ssl").create_default_context() and "")
    item("versao", lambda: server.VERSION)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--escolher-pasta"] and len(argv) > 1:
        from soal import picker
        picker.run(argv[1])
        return 0
    if argv[:1] == ["--verificar-instalacao"] and len(argv) > 1:
        return verificar_instalacao(argv[1])
    if sys.stdout is None or getattr(sys, "frozen", False) or os.path.basename(sys.executable).lower().startswith("pythonw"):
        try:
            log = open(LOG, "w", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = log
        except OSError:
            pass
    if sys.version_info < (3, 8):
        _avisar("Este programa precisa do Python 3.8 ou mais novo.")
        return 1
    try:
        from soal import server
        server.serve(window="--navegador" not in argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            _avisar(str(exc.code))
            return 1
    except Exception:
        traceback.print_exc()
        _avisar("O SOAL Tradutor encontrou um erro e precisou fechar.\n\nDetalhes em:\n" + LOG)
        return 1
    return 0
