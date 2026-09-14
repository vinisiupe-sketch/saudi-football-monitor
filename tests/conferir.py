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

# ── O CONSOLE DO WINDOWS NÃO FALA UTF-8 POR PADRÃO ──────────────────────────
#
# Em 14/09/26 o gancho de envio barrou o push do Vini com quase tudo
# "FALHOU" — e não havia teste quebrado nenhum. O console do Git Bash abre em
# cp1252, os testes imprimem "✓", "─" e acentos, e o Python estoura com
# UnicodeEncodeError. O processo morre com código diferente de zero, e quem
# está de fora lê isso como teste vermelho.
#
# É o pior tipo de falso alarme: ele acusa o código honesto e esconde o
# problema real, que é a saída do terminal. Pior ainda num gancho que BLOQUEIA
# o envio — vira um obstáculo sem explicação, que é exatamente o que eu disse
# que não queria quando escrevi a rede de proteção.
#
# Duas frentes, porque o estrago tem dois lugares:
#   1. a minha própria saída, abaixo;
#   2. a de cada teste, que roda num processo filho e não herda isto — por
#      isso o PYTHONIOENCODING vai no ambiente que eu passo a eles.
for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # Python antigo ou fluxo redirecionado: sigo em frente. Não conseguir
        # melhorar a saída não é motivo para não rodar os testes.
        pass

AMBIENTE = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


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
                           cwd=RAIZ, capture_output=True, text=True,
                           env=AMBIENTE, encoding="utf-8", errors="replace")
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
