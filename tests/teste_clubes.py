"""
Um clube, uma grafia — e ela é escolhida na GRAVAÇÃO.

O QUE ESTE TESTE DEFENDE
    A medição de 27/08 achou 29 clubes escritos de mais de um jeito dentro do
    app: 'Al Hilal' nas lesões, 'Al-Hilal SFC' na janela, 'Al-Hilal Saudi FC'
    na prévia, 'Al Diraiyah' na arbitragem.

    Nenhuma dessas grafias foi inventada aqui — são o Transfermarkt, a
    API-Football e o SAFF escrevendo cada um do seu jeito. O erro era guardar
    o texto cru e traduzir só na hora de mostrar. Isso faz UMA tela ficar
    certa e impede qualquer cruzamento entre duas.

    Por isso o teste olha o `database.py`: o lugar onde o clube é gravado tem
    que passar pelo glossário. Padronizar na tela seria o defeito de volta,
    com outra roupa.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import glossary

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def testar():
    falhas.clear()

    # ── as grafias que a medição encontrou de verdade ───────────────────
    # Cada linha aqui saiu de /api/diag/nomes rodando contra o banco real.
    reais = {
        "Al Hilal": ["Al Hilal", "Al-Hilal", "Al-Hilal SFC", "Al-Hilal Saudi FC"],
        "Al Nassr": ["Al Nassr", "Al-Nassr", "Al-Nasr", "Al-Nassr FC"],
        "Al Diriyah": ["Al Diraiyah", "Al-Diriyah", "Al-Diriyah FC"],
        "Al Khaleej": ["Al Khaleej", "Al Khaleej Saihat", "Al-Khaleej", "Al-Khaleej FC"],
        "Al Ahli": ["Al Ahli", "Al Ahly", "Al-Ahli", "Al-Ahli SFC"],
        "Al Taawoun": ["Al Taawon", "Al-Taawoun", "Al-Taawoun FC"],
        "Al Ittihad": ["Al Ittihad", "Al-Ittihad", "Al-Ittihad Club"],
        "Abha": ["Abha", "Abha Club"],
        "Al Tai": ["Al Taee", "Al-Tai"],
        "Al Orobah": ["Al Orubah", "Al-Orobah"],
    }
    for canonico, variantes in reais.items():
        saida = {glossary.clube_para_guardar(v) for v in variantes}
        conferir(f"{canonico} ({len(variantes)} grafias)", saida, {canonico})

    # ── o que NÃO pode ser forçado para dentro da tabela saudita ────────
    # Clube estrangeiro e time sub-21 caem no "não sei" de propósito. Forçar
    # o mais parecido inventaria um clube que não existe na Roshn — e o erro
    # sairia assinado por você, num post.
    for fora in ["Ajax", "Atalanta", "Anderlecht", "AEK Atenas", "Al-Duhail SC",
                 "Al-Jazira", "Ajman Club"]:
        conferir(f"estrangeiro intacto: {fora}",
                 glossary.clube_para_guardar(fora), fora)
    for sub in ["Al-Hilal U21", "Al-Ittihad U21", "Al-Ula U21"]:
        conferir(f"sub-21 não vira o time principal: {sub}",
                 glossary.clube_para_guardar(sub), sub)

    # ── a função é idempotente ──────────────────────────────────────────
    # Precisa ser: a varredura que conserta o que já está gravado pode rodar
    # de novo, e canônico de canônico tem que ser ele mesmo.
    for canonico in reais:
        conferir(f"idempotente: {canonico}",
                 glossary.clube_para_guardar(glossary.clube_para_guardar(canonico)),
                 canonico)

    # ── entradas degeneradas não podem explodir ─────────────────────────
    for vazio in ["", "   ", None]:
        conferir(f"vazio vira vazio: {vazio!r}",
                 glossary.clube_para_guardar(vazio), "")
    conferir("espaço duplo colapsa",
             glossary.clube_para_guardar("Al   Hilal"), "Al Hilal")

    # ── e agora o que importa: isso acontece na GRAVAÇÃO ────────────────
    fonte = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    arvore = ast.parse(fonte)

    ok("def _clube(" in fonte,
       "database.py não tem a função única que padroniza clube")

    # Cada função que grava clube tem que chamar _clube. Se alguém acrescentar
    # uma tabela nova com nome de time e esquecer, é aqui que aparece.
    GRAVAM_CLUBE = {
        "salvar_arbitragem": 2,        # casa e fora
        "salvar_previa": 2,            # casa e fora
        "upsert_injury": 1,            # club
        "upsert_window_transfers": 2,  # entrou e saiu
    }
    for nome, quantos in GRAVAM_CLUBE.items():
        fn = next((n for n in ast.walk(arvore)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == nome), None)
        ok(fn is not None, f"não achei {nome} no database.py")
        if not fn:
            continue
        usos = sum(1 for ch in ast.walk(fn)
                   if isinstance(ch, ast.Call) and isinstance(ch.func, ast.Name)
                   and ch.func.id == "_clube")
        ok(usos >= quantos,
           f"{nome} grava {quantos} nome(s) de clube mas chama _clube {usos} vez(es)")

    # A correção do que já está gravado tem que existir e ser guardada por um
    # marcador — varrer quatro tabelas em toda subida é desperdício.
    ok("def padronizar_clubes_gravados(" in fonte,
       "não existe a varredura que conserta o que já está no banco")
    ok('get_state("clubes_padronizados")' in fonte,
       "a varredura roda toda vez em vez de uma vez só")

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    total = sum(len(v) for v in reais.values())
    print(f"  ✓ clubes: {total} grafias reais viram {len(reais)} nomes, "
          f"e a padronização é na gravação")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
