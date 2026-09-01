"""
Reconhecer o jogo a partir do título da transmissão.

POR QUE ISTO PRECISA DE TESTE
    O card da guia de Clipes passa a mostrar sigla, escudo e placar. Tudo isso
    depende de acertar QUAL jogo é, a partir de um título escrito à mão:

        AL KHALEEJ X AL HILAL | AO VIVO E COM IMAGENS | SAUDI PRO LEAGUE

    Errar aqui não dá erro. Dá um card bonito com o escudo do time errado e o
    placar de outra partida — e ele está com isso na tela enquanto narra.

    Por isso a regra é: reconheceu com certeza, mostra tudo; não reconheceu,
    mostra o título cru e mais nada. Card sem escudo é honesto.

O SEPARADOR
    ' X ' com espaço dos dois lados, e não o caractere solto. 'Al Akhdoud' tem
    um x no meio; sem a exigência de espaço, ele viraria dois times.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import liga_spl

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def _time(nome, sigla, logo="clubLogos/abc.webp"):
    return {"shortName": nome, "acronymName": sigla,
            "imagery": {"teamLogo": logo}}


JOGOS = [
    {"matchId": "m1", "status": "LIVE", "time": "79", "additionalTime": "0",
     "providerHomeScore": 0, "providerAwayScore": 1, "roundName": "Matchweek 3",
     "home": _time("Al Khaleej", "KHL"), "away": _time("Al Hilal", "HIL")},
    {"matchId": "m2", "status": "FIXTURE", "time": "", "additionalTime": "",
     "providerHomeScore": None, "providerAwayScore": None,
     "home": _time("Al Nassr", "NAS"), "away": _time("Al Taawoun", "TAA")},
]


def testar():
    falhas.clear()

    # ── 1. tirar os dois clubes do título ──────────────────────────────────
    conferir("título normal",
             liga_spl.clubes_do_titulo(
                 "AL KHALEEJ X AL HILAL | AO VIVO E COM IMAGENS | SAUDI PRO LEAGUE"),
             ("AL KHALEEJ", "AL HILAL"))
    conferir("x minúsculo",
             liga_spl.clubes_do_titulo("Al Nassr x Al Taawoun | ao vivo"),
             ("Al Nassr", "Al Taawoun"))
    conferir("vs também vale",
             liga_spl.clubes_do_titulo("AL AHLI VS AL ITTIHAD | LIVE"),
             ("AL AHLI", "AL ITTIHAD"))
    conferir("sem barra nenhuma",
             liga_spl.clubes_do_titulo("AL HILAL X AL NASSR"),
             ("AL HILAL", "AL NASSR"))
    conferir("espaço sobrando não atrapalha",
             liga_spl.clubes_do_titulo("  AL  HILAL   X   AL NASSR  | x"),
             ("AL HILAL", "AL NASSR"))

    # ── 2. o que NÃO dá para reconhecer ────────────────────────────────────
    # Aqui o certo é devolver vazio. Quem chama mostra o título cru.
    for titulo in ("", "TRANSMISSÃO ESPECIAL", "AL HILAL", None,
                   "A X B X C | tres times?"):
        conferir(f"não reconhece {titulo!r}",
                 liga_spl.clubes_do_titulo(titulo), ("", ""))

    # O 'x' dentro de nome de clube não é separador. 'Al Akhdoud' é o caso
    # real: sem exigir espaço dos dois lados, ele viraria 'Al Akhdoud' partido
    # ao meio e o jogo nunca casaria.
    a, b = liga_spl.clubes_do_titulo("AL AKHDOUD X AL FATEH | AO VIVO")
    conferir("nome com x no meio fica inteiro", (a, b), ("AL AKHDOUD", "AL FATEH"))

    # ── 3. achar o jogo ────────────────────────────────────────────────────
    j = liga_spl.achar_jogo("AL KHALEEJ X AL HILAL | AO VIVO | SPL", JOGOS)
    conferir("achou o jogo certo", j.get("matchId"), "m1")
    # A ordem não importa: uma fonte chama de mandante quem a outra chama de
    # visitante, e o jogo continua sendo o mesmo.
    j2 = liga_spl.achar_jogo("AL HILAL X AL KHALEEJ | AO VIVO", JOGOS)
    conferir("invertido é o mesmo jogo", j2.get("matchId"), "m1")
    # Grafia diferente passa pelo glossário.
    j3 = liga_spl.achar_jogo("AL-KHALEEJ X AL HILAL SFC | AO VIVO", JOGOS)
    conferir("grafia diferente ainda acha", j3.get("matchId"), "m1")

    conferir("jogo que não está na liga não é forçado",
             liga_spl.achar_jogo("GOTHAM FC X PORTLAND THORNS | NWSL", JOGOS), {})
    conferir("título irreconhecível não acha nada",
             liga_spl.achar_jogo("LIVE ESPECIAL", JOGOS), {})
    conferir("sem jogos, sem par",
             liga_spl.achar_jogo("AL KHALEEJ X AL HILAL", []), {})

    # ── 4. o que a tela desenha ────────────────────────────────────────────
    p = liga_spl.placar_do_jogo(JOGOS[0])
    conferir("sigla da casa", p["casa"]["sigla"], "KHL")
    conferir("sigla do visitante", p["fora"]["sigla"], "HIL")
    conferir("placar", (p["gols_casa"], p["gols_fora"]), (0, 1))
    conferir("minuto", p["minuto"], "79")
    ok(p["casa"]["escudo"].startswith("https://"),
       "o escudo saiu como caminho relativo — a tela não monta URL, e não deve")

    # Acréscimos aparecem como 90+7, e não como 90.
    com_extra = dict(JOGOS[0], time="90", additionalTime="7")
    conferir("acréscimos", liga_spl.placar_do_jogo(com_extra)["minuto"], "90+7")
    # Zero de acréscimo não vira '90+0'.
    conferir("sem acréscimo",
             liga_spl.placar_do_jogo(dict(JOGOS[0], time="45",
                                          additionalTime="0"))["minuto"], "45")

    # ── 5. jogo de fora da liga não ganha enfeite inventado ────────────────
    # Copa do Rei e AFC não estão nesta API. O card deles fica sem sigla, sem
    # escudo e sem placar — de propósito.
    conferir("jogo vazio não vira card", liga_spl.placar_do_jogo({}), {})
    conferir("None também", liga_spl.placar_do_jogo(None), {})
    sem_escudo = liga_spl.placar_do_jogo(
        {"home": {"shortName": "X"}, "away": {"shortName": "Y"}})
    conferir("sem imagery, sem escudo", sem_escudo["casa"]["escudo"], "")

    # ── 6. o que a guia faz com tudo isso ─────────────────────────────────
    import ast
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

    def _corpo(nome):
        for n in ast.walk(ast.parse(fonte)):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome:
                return "\n".join(fonte.split("\n")[n.lineno - 1:n.end_lineno])
        return ""

    # O enfeite é montado no SERVIDOR. Se a tela passar a montar a URL do
    # escudo ou a achar o jogo por conta própria, no dia em que a liga trocar
    # de servidor de mídia serão dois lugares para corrigir — e um deles é
    # JavaScript dentro de uma string.
    ok("_enfeitar(listar_lives()" in _corpo("api_clipes"),
       "a lista de jogos gravando parou de receber sigla, escudo e placar")
    ok("_enfeitar(lives_disponiveis()" in _corpo("api_clipes"),
       "a lista do canal parou de receber o cartão de placar")

    # O que não é da liga saudita fica escondido — mas nunca sem porta de
    # saída. Uma regra de título não prevê como um jogo importante vai ser
    # rotulado, e esconder sem retorno é como se perde uma final.
    for fn in ("api_clipes", "api_clipe_lives"):
        c = _corpo(fn)
        ok('d.get("da_liga")' in c,
           f"{fn}: o filtro da liga saudita sumiu")
        ok("todas" in c and "escondidas" in c,
           f"{fn}: o filtro esconde sem deixar como ver o que foi escondido")

    # A sub-aba por jogo é filtragem do que já veio, e não uma ida à rede.
    ok("_jogoEscolhido" in fonte and "escolherJogo" in fonte,
       "sumiu a seleção de jogo — os clipes voltam a cair todos na mesma lista")
    ok("c.live_id === _jogoEscolhido" in fonte,
       "a lista de clipes parou de filtrar pelo jogo escolhido")
    ok("var _ultimosClipes" in fonte,
       "trocar de jogo voltou a depender de nova consulta ao servidor")

    # Jogo não reconhecido mostra o título cru, e não um cartão pela metade.
    ok("if (!j.da_liga || !p.casa)" in fonte,
       "o cartão de placar parou de tratar o jogo que a liga não reconhece — "
       "Copa do Rei e AFC sairiam com sigla e escudo em branco")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ clipes: o jogo é reconhecido pelo título, ou não é reconhecido")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
