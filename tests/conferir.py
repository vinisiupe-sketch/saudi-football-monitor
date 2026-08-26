"""
Roda as conferências todas de uma vez.

    py -3 tests/conferir.py

POR QUE ISTO EXISTE
    Eu vinha escrevendo os testes numa pasta temporária, e duas vezes eles
    sumiram quando a sessão reiniciou. Teste que some não é teste — é uma
    conferência que eu fiz uma vez e não consigo repetir. Daqui em diante eles
    ficam aqui, dentro do projeto, versionados junto com o código que testam.
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)


def main() -> int:
    testes = sorted(a for a in os.listdir(AQUI)
                    if a.startswith("teste_") and a.endswith(".py"))
    if not testes:
        print("nenhum teste encontrado")
        return 1
    largura = max(len(t) for t in testes)
    ruins = []
    for t in testes:
        r = subprocess.run([sys.executable, os.path.join(AQUI, t)],
                           cwd=RAIZ, capture_output=True, text=True)
        marca = "ok" if r.returncode == 0 else "FALHOU"
        print(f"  {t:{largura}}  {marca}")
        if r.returncode != 0:
            ruins.append((t, (r.stdout or "") + (r.stderr or "")))
    print()
    for t, saida in ruins:
        print(f"── {t} " + "─" * 50)
        print(saida.strip()[-1500:])
        print()
    print(f"{len(testes) - len(ruins)} de {len(testes)} passaram")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
