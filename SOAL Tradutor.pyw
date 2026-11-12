"""SOAL Tradutor - abre numa janela propria, sem console. De dois cliques neste arquivo."""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOG = os.path.join(os.path.expanduser("~"), ".soal_tradutor.log")

try:
    log = open(LOG, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
except OSError:
    log = None


def avisar(msg):
    try:
        import tkinter
        import tkinter.messagebox
        r = tkinter.Tk()
        r.withdraw()
        tkinter.messagebox.showerror("SOAL Tradutor", msg)
        r.destroy()
    except Exception:
        pass


if sys.version_info < (3, 8):
    avisar("Este programa precisa do Python 3.8 ou mais novo.")
    sys.exit(1)

try:
    from soal import server
    server.serve(window=True)
except SystemExit as exc:
    if exc.code not in (None, 0):
        avisar(str(exc.code))
except Exception:
    traceback.print_exc()
    avisar("O SOAL Tradutor encontrou um erro e precisou fechar.\n\nDetalhes em:\n" + LOG)
