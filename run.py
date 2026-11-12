#!/usr/bin/env python3
"""SOAL Tradutor - ferramenta de traducao dos dialogos de Skies of Arcadia Legends (GameCube).

Uso:  python run.py            abre a interface no navegador
      python run.py --porta 9000 --sem-navegador
"""
import argparse
import os
import sys

if sys.version_info < (3, 8):
    sys.exit("Este programa precisa do Python 3.8 ou mais novo.")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from soal import server  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="SOAL Tradutor")
    ap.add_argument("--porta", type=int, default=8787)
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--nao-reabrir", action="store_true", help="nao reabre o ultimo projeto")
    a = ap.parse_args()
    server.serve(a.porta, not a.sem_navegador, not a.nao_reabrir)


if __name__ == "__main__":
    main()
