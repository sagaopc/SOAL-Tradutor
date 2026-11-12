"""SOAL Tradutor - abre numa janela propria, sem console. De dois cliques neste arquivo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from soal.app import main  # noqa: E402

sys.exit(main())
