"""Entrada usada pelo PyInstaller para gerar o SOAL Tradutor.exe."""
import sys

from soal.app import main

if __name__ == "__main__":
    sys.exit(main())
