"""
Clipe automático pelo ALERTA DE GOL, e não mais pelo placar da imagem.

POR QUE MUDOU (03/09/26)
    A leitura do placar no vídeo olhava uma posição fixa da tela. A
    transmissão move o placar: quando entra o letreiro em L da casa de
    apostas, a imagem inteira encolhe e o recorte cai na grama. Resultado
    medido em jogo real: clipes de nada a cada troca de câmera, e mais um
    quando a emissora cortava para o gol de OUTRA partida. Posição fixa era
    uma suposição sobre uma tela que muda o tempo todo.

    O alerta da API-Football não sabe o instante exato — ele chega depois.
    Em troca, ele sabe QUE houve gol e em QUAL jogo, que é o que a leitura de
    imagem errava. A janela larga (20s de cada lado) paga o preço da
    imprecisão: sobra de vídeo a fita de corte resolve; falta, não.

O QUE ESTE ARQUIVO VIGIA
    Que o clipe só nasça para o jogo CERTO. Com quatro partidas ao mesmo
    tempo, clipar a errada é pior que não clipar: sai um vídeo com cara de
    certo, e ninguém confere antes de publicar.
"""
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))
os.chdir(RAIZ)

if "psycopg2" not in sys.modules:
    talo = types.ModuleType("psycopg2")
    talo.extras = types.ModuleType("psycopg2.extras")
    talo.extras.RealDictCursor = object
    talo.Error = Exception
    sys.modules["psycopg2"] = talo
    sys.modules["psycopg2.extras"] = talo.extras

import ast

import ajustes
import glossary
import liga_spl

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def _corpo(nome):
    for n in ast.walk(ast.parse(FONTE)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome:
            return "\n".join(FONTE.split("\n")[n.lineno - 1:n.end_lineno])
    return ""


# A REGRA DE VERDADE, e não uma cópia dela. Reimplementar aqui o casamento de
# clubes seria o teste conferindo a si mesmo: eu troquei o `==` por `&` no
# main.py de propósito, para ver, e a versão copiada continuou passando verde.
_casa_com = liga_spl.mesmo_jogo


def _dentro_do_if_de_gol_novo() -> bool:
    """O pedido de clipe está DENTRO do `if registrar_gol(...)`?

    Olhado pela árvore do código, e não por ordem de linhas: tirar a
    indentação faz a chamada rodar a cada passagem do coletor, no mesmo gol,
    e uma checagem de "quem vem antes no arquivo" não vê diferença nenhuma
    nisso — foi o que aconteceu quando testei a mutação.
    """
    for no in ast.walk(ast.parse(FONTE)):
        if not isinstance(no, ast.If):
            continue
        teste = ast.dump(no.test)
        if "registrar_gol" not in teste or "api_football" not in teste:
            continue
        for dentro in ast.walk(no):
            if (isinstance(dentro, ast.Call)
                    and getattr(dentro.func, "id", "") == "_clipe_automatico_do_gol"):
                return True
    return False


def testar():
    falhas.clear()

    # ── 1. os ajustes novos, com os números que o Vini pediu ──────────────
    for chave, padrao in (("clipe_auto_ligado", "ligado"),
                          ("clipe_auto_antes_seg", 20),
                          ("clipe_auto_depois_seg", 20),
                          ("clipe_auto_atraso_alerta_seg", 45)):
        ok(chave in ajustes.POR_CHAVE, f"sumiu o ajuste {chave}")
        if chave in ajustes.POR_CHAVE:
            conferir(f"padrão de {chave}",
                     ajustes.POR_CHAVE[chave]["padrao"], padrao)

    # A janela automática é MAIOR que a do botão. Se um dia alguém igualar as
    # duas, o clipe automático volta a perder o lance — e o motivo de elas
    # serem diferentes não está escrito em lugar nenhum além daqui.
    ok(ajustes.POR_CHAVE["clipe_auto_antes_seg"]["padrao"]
       > ajustes.POR_CHAVE["clipe_antes_seg"]["padrao"],
       "a janela do clipe automático deixou de ser mais larga que a do botão")

    # ── 2. a leitura do placar do vídeo nasce DESLIGADA ───────────────────
    conferir("a leitura do placar do vídeo está desligada por padrão",
             ajustes.POR_CHAVE["gravador_placar_ativo"]["padrao"], "desligado")

    # ── 3. o casamento do jogo: os DOIS clubes, pelo glossário ────────────
    titulo = "AL DIRIYAH X AL QADSIAH | AO VIVO E COM IMAGENS | SAUDI PRO LEAGUE"
    ok(_casa_com(titulo, "Al Diriyah", "Al-Qadisiyah FC"),
       "o jogo do título não casou com os nomes da API — o clipe automático "
       "nunca sairia")
    ok(not _casa_com(titulo, "Al Hilal", "Al Khaleej"),
       "casou com OUTRO jogo: com quatro partidas no ar isso clipa a errada")
    ok(not _casa_com(titulo, "Al Diriyah", "Al Hilal"),
       "bastou UM clube bater para casar — os dois têm que bater")
    ok(not _casa_com("TRANSMISSÃO ESPECIAL", "Al Diriyah", "Al Qadsiah"),
       "casou com um título que não diz jogo nenhum")

    # ── 4. o gancho está no lugar certo: só para gol NOVO ─────────────────
    coletor = _corpo("coletar_gols_ao_vivo")
    ok("_clipe_automatico_do_gol(nc, nf)" in coletor,
       "o coletor de gols parou de pedir o clipe automático — ou parou de "
       "usar os nomes do glossário (nc/nf), que é o que faz "
       "'Al-Qadisiyah FC' casar com 'AL QADSIAH' do título da live")
    ok(_dentro_do_if_de_gol_novo(),
       "o pedido de clipe saiu de dentro do 'if registrar_gol(...)' — fora "
       "dali ele dispara a cada passagem do coletor, no mesmo gol")

    # ── 5. a função em si ─────────────────────────────────────────────────
    fn = _corpo("_clipe_automatico_do_gol")
    ok('ajuste("clipe_auto_ligado") != "ligado"' in fn,
       "o clipe automático perdeu o interruptor de desligar sem deploy")
    ok("_live_do_jogo(" in fn,
       "parou de conferir se o jogo está mesmo sendo gravado")
    ok("_ja_tem_clipe_automatico(" in fn,
       "parou de checar se o mesmo gol já virou clipe")
    ok("automatico=True" in fn,
       "o clipe do alerta parou de nascer marcado como automático")
    ok("_atraso_transmissao() - atraso_alerta" in fn,
       "a conta do instante mudou: o alerta é mais VELHO que o gol (recua) e "
       "a gravação está ATRÁS da transmissão (avança) — os dois sinais")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ clipe automático pelo alerta de gol, no jogo certo e com "
          "janela larga")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
