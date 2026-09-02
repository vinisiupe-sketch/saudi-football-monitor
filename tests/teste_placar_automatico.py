"""
Clipe automático: ler o placar direto do vídeo, em vez de esperar uma API.

POR QUE ISTO EXISTE
    O botão GOL AGORA continua existindo — isto roda AO LADO dele, não no
    lugar. A peça nova é a máquina que grava notando, sozinha, que o número
    do placar mudou no vídeo que ela já está gravando, e pedindo um clipe
    sem ninguém apertar nada. Errar aqui tem dois jeitos, e os dois doem:

        1. Nunca disparar — a rotina existe e não faz nada, e ninguém sabe
           até faltar um gol.
        2. Disparar à toa — um clipe automático nascendo de um replay, um
           intervalo, ou uma trocada de layout do canal, poluindo a fila.

    Por isso o coração disto (a classe Placar, em gravador.py) precisa de
    teste de verdade: confirmar só depois de ver a mudança se repetir,
    voltar ao normal se ela reverter, e usar o instante da PRIMEIRA vez que
    o novo número apareceu — não o da confirmação — porque é isso que entra
    na conta do atraso do gráfico.

OS DOIS QUADROS REAIS
    tests/fixtures/placar_al_hilal_al_ahli_{0x0,1x0}.jpg são dois quadros de
    verdade, tirados da gravação de Al Hilal x Al Ahli de 01/09/26 (aos 10 e
    aos 30 minutos de gravação — o Al Hilal fez o primeiro gol nesse meio).
    Rodar _ler_placar contra os dois de verdade é a única forma de saber se
    a caixa medida (CAIXA_PLACAR) ainda bate com o overlay real do canal —
    um teste que só usasse imagem sintética não pegaria isso.
"""
import io
import re
import os
import sys
import types
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))
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

from banco_de_teste import Banco
from PIL import Image

import ajustes
import database
import gravador

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def com_banco(banco, fn, *a, **k):
    original = database.get_conn
    database.get_conn = banco
    try:
        return fn(*a, **k)
    finally:
        database.get_conn = original


def testar():
    falhas.clear()

    # ── 1. os ajustes existem e obedecem à faixa ──────────────────────────
    for chave in ("gravador_placar_ativo", "gravador_atraso_placar_seg"):
        ok(chave in ajustes.POR_CHAVE, f"o ajuste {chave} sumiu de ajustes.py")

    conferir("liga/desliga aceita 'desligado'",
             ajustes.limpar("gravador_placar_ativo", "desligado"), "desligado")
    conferir("liga/desliga recusa valor fora da lista",
             ajustes.limpar("gravador_placar_ativo", "talvez"), None)
    conferir("atraso do placar aceita 8",
             ajustes.limpar("gravador_atraso_placar_seg", "8"), 8)
    conferir("atraso do placar limita o máximo",
             ajustes.limpar("gravador_atraso_placar_seg", "999"), 30)
    conferir("o padrão do atraso é 8s — o número que o Vini mediu",
             ajustes.POR_CHAVE["gravador_atraso_placar_seg"]["padrao"], 8)

    # ── 2. criar_pedido_clipe grava o automatico, e não estraga o manual ──
    banco = Banco(("clipe",))
    alvo = datetime(2026, 9, 3, 18, 0, 0, tzinfo=timezone.utc)
    cid_manual = com_banco(banco, database.criar_pedido_clipe,
                           alvo, 12, 10, "live1", "gol")
    cid_auto = com_banco(banco, database.criar_pedido_clipe,
                         alvo, 12, 10, "live1", "gol", True)
    linhas = {r["id"]: r for r in banco.linhas("clipe")}
    ok(cid_manual in linhas and cid_auto in linhas,
       "os dois pedidos de clipe não foram gravados")
    conferir("clipe do botão manual NÃO nasce marcado como automático",
             bool(linhas[cid_manual]["automatico"]), False)
    conferir("clipe automático nasce marcado",
             bool(linhas[cid_auto]["automatico"]), True)

    # A listagem que a tela usa (clipes_recentes/clipes_a_cortar, e o que o
    # gravador recebe em /api/clipe/pendentes) monta a resposta a partir da
    # mesma _COLS_CLIPE — se "automatico" não estiver nessa lista, o selo
    # "⚡ automático" nunca teria o que mostrar em lugar nenhum.
    ok("automatico" in database._COLS_CLIPE.replace(" ", "").split(","),
       "'automatico' sumiu de _COLS_CLIPE — nenhuma tela chegaria a vê-lo")

    # ── 3. a tela mostra o selo, sem mexer no que já existia ──────────────
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    ok("c.automatico ? '<span class=\"selo s-automatico\">" in fonte,
       "o selo de clipe automático sumiu da montagem do card")
    ok("c.tipo === 'outro' ? '<span class=\"selo\">lance</span>'" in fonte,
       "mexer no selo automático estragou o selo de 'lance' que já existia")
    ok("c.guardado ? '<span class=\"selo s-guardado\">" in fonte,
       "mexer no selo automático estragou o selo de guardado (★) que já existia")

    # ── 4. a rota nova: autenticação de agente, o "desligar" na tela, e o
    #      resto do fluxo intacto ─────────────────────────────────────────
    import ast

    def _corpo(nome):
        for n in ast.walk(ast.parse(fonte)):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome:
                return "\n".join(fonte.split("\n")[n.lineno - 1:n.end_lineno])
        return ""

    rota = _corpo("api_clipe_gol_automatico")
    ok(rota, "a rota /api/clipe/gol-automatico sumiu")
    ok("_agente_autorizado(request)" in rota,
       "a rota do clipe automático parou de exigir o token do agente — "
       "qualquer um na internet poderia enfiar clipe na fila")
    ok('ajuste("gravador_placar_ativo") != "ligado"' in rota,
       "o botão de desligar na guia Configurações parou de valer nesta rota")
    ok("automatico=True" in rota,
       "a rota parou de marcar o clipe como automático")
    ok('any(l.get("id") == live_id for l in listar_lives())' in rota,
       "a rota parou de conferir se o jogo está mesmo sendo gravado")
    ok('int(ajuste("clipe_antes_seg"))' in rota and 'int(ajuste("clipe_depois_seg"))' in rota,
       "a janela do clipe automático parou de usar os mesmos ajustes do manual")

    # Com DUAS máquinas gravando (a do Vini e a de quem estiver com o PC de
    # pé), as duas veem a mesma mudança de placar e as duas pedem clipe. Sem
    # guarda, um gol vira dois clipes iguais na fila — e o corte é a parte
    # cara.
    ok("JANELA_GOL_REPETIDO_SEG" in rota,
       "sumiu a guarda contra dois gravadores pedirem o mesmo gol")
    ok('c.get("automatico")' in rota and 'c.get("live_id") != live_id' in rota,
       "a guarda parou de comparar por jogo e por origem automática — ela "
       "não pode engolir um pedido do botão manual")
    ok('"ja_pedido": True' in rota,
       "o segundo gravador deixou de receber a resposta de 'já pedido' — sem "
       "isso ele acha que falhou e tenta de novo")
    conferir("a janela do gol repetido",
             int(re.search(r"JANELA_GOL_REPETIDO_SEG = (\d+)", fonte).group(1)), 30)

    # O botão continua exatamente como estava.
    manual = _corpo("api_clipe_pedir")
    ok("atraso - reacao" in manual,
       "a rota do botão manual mudou — não deveria, isto é sobre a rota nova")

    # A rota nova está sob o mesmo prefixo livre de sessão que as outras do
    # agente (LIVRES tem "/api/clipe/" com barra, cobre todo mundo aqui).
    ok('"/api/clipe/"' in fonte,
       "o prefixo /api/clipe/ sumiu de LIVRES — a máquina que grava não "
       "tem cookie de sessão para autenticar de outro jeito")

    for falha in falhas:
        print("  ✗", falha)
    print(f"\nFALHAS até aqui: {len(falhas)}" if falhas else "")

    # ── 5. a leitura do placar em si (o coração da rotina) ────────────────
    testar_leitor_de_placar()
    testar_maquina_de_estados()

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ clipe automático: lê o placar do vídeo, confirma antes de "
          "disparar, e o botão manual continua intacto")
    return len(falhas)


def testar_leitor_de_placar():
    """_ler_placar contra dois quadros REAIS da gravação de 01/09/26."""
    caminho_00 = os.path.join(AQUI, "fixtures", "placar_al_hilal_al_ahli_0x0.jpg")
    caminho_10 = os.path.join(AQUI, "fixtures", "placar_al_hilal_al_ahli_1x0.jpg")
    if not (os.path.exists(caminho_00) and os.path.exists(caminho_10)):
        falhas.append("faltam os quadros de teste em tests/fixtures/ — "
                      "sem eles não dá para conferir a caixa do placar")
        return

    quadro_00 = Image.open(caminho_00).convert("RGB")
    quadro_10 = Image.open(caminho_10).convert("RGB")

    leitura_00 = gravador._ler_placar(quadro_00)
    leitura_10 = gravador._ler_placar(quadro_10)

    ok(leitura_00 is not None,
       "não consegui ler o placar 0x0 — a caixa medida não bate mais com "
       "o overlay real do canal (veja CAIXA_PLACAR em gravador.py)")
    ok(leitura_10 is not None,
       "não consegui ler o placar 1x0 — idem")
    if leitura_00 is None or leitura_10 is None:
        return

    esquerdo_00, direito_00 = leitura_00
    esquerdo_10, direito_10 = leitura_10
    # Entre os dois quadros o Al Hilal (esquerda) marcou — a caixa da
    # esquerda tem que ter mudado de figura, e a da direita (Al Ahli, que
    # não balançou a rede) tem que ter continuado a mesma.
    ok(not gravador._parecidas((esquerdo_00,), (esquerdo_10,)),
       "a leitura do placar da ESQUERDA não mudou entre 0x0 e 1x0 — um gol "
       "de verdade passaria batido")
    ok(gravador._parecidas((direito_00,), (direito_10,)),
       "a leitura do placar da DIREITA mudou à toa (ninguém marcou para o "
       "Al Ahli entre os dois quadros) — LIMIAR_MUDANCA está apertado "
       "demais para o ruído de compressão real")

    # Uma imagem sem o gráfico (grama pura, sem overlay) tem que devolver
    # None — silêncio é seguro, inventar placar não é.
    verde = Image.new("RGB", (1280, 720), (34, 139, 34))
    conferir("quadro sem o gráfico do placar não inventa leitura",
             gravador._ler_placar(verde), None)


def _sinal(bit_esq: int, bit_dir: int):
    """Uma leitura falsa, do mesmo formato que _ler_placar devolve: duas
    assinaturas de 80 pontos (8x10), uma por time. Preenchida toda com o
    mesmo bit — trocar 0 por 1 muda os 80 pontos de uma vez, bem acima do
    LIMIAR_MUDANCA, então serve para testar a máquina de estados sem
    depender do valor exato do limiar."""
    return (tuple([bit_esq] * 80), tuple([bit_dir] * 80))


def testar_maquina_de_estados():
    """A classe Placar: só confirma depois de ver a mudança se repetir."""
    t0 = datetime(2026, 9, 3, 18, 30, 0, tzinfo=timezone.utc)
    a = _sinal(0, 0)
    b = _sinal(1, 0)

    # Primeira leitura: só assenta a base, não dispara nada — não há "antes"
    # para comparar ainda.
    p = gravador.Placar()
    conferir("primeira leitura não dispara", p.observar(a, t0), None)

    # Uma leitura igual à base não muda nada.
    conferir("leitura repetida não dispara", p.observar(a, t0 + timedelta(seconds=2)), None)

    # Uma leitura NOVA, sozinha, ainda não é confirmação — pode ser um
    # quadro de transição (o número trocando na tela).
    t_mudou = t0 + timedelta(seconds=4)
    conferir("uma leitura nova sozinha ainda não confirma",
             p.observar(b, t_mudou), None)

    # A MESMA leitura nova de novo: agora confirma — e o instante devolvido
    # é o da PRIMEIRA vez que ela apareceu, não o de agora.
    t_confirmou = t0 + timedelta(seconds=6)
    instante = p.observar(b, t_confirmou)
    conferir("duas leituras iguais seguidas confirmam a mudança", instante, t_mudou)

    # Depois de confirmar, o "atual" vira b — uma leitura igual a b não
    # dispara de novo.
    conferir("depois de confirmado, não dispara de novo à toa",
             p.observar(b, t_confirmou + timedelta(seconds=2)), None)

    # Um candidato que aparece e depois RECUA (o gráfico piscou, por
    # exemplo) não pode disparar — e o candidato seguinte começa a contar
    # do zero, não aproveita a leitura antiga.
    p2 = gravador.Placar()
    p2.observar(a, t0)
    p2.observar(b, t0 + timedelta(seconds=2))      # candidato aparece
    conferir("candidato que recua antes de confirmar não dispara",
             p2.observar(a, t0 + timedelta(seconds=4)), None)
    c = _sinal(1, 1)
    t_c_apareceu = t0 + timedelta(seconds=6)
    conferir("depois de recuar, um candidato novo ainda não confirma sozinho",
             p2.observar(c, t_c_apareceu), None)
    conferir("e confirma na segunda leitura igual, com o instante da PRIMEIRA",
             p2.observar(c, t0 + timedelta(seconds=8)), t_c_apareceu)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
