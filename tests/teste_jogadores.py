"""
A varredura que monta a tabela de jogadores.

NOTA SOBRE ESTE ARQUIVO
    Existiam duas implementações deste passo no projeto ao mesmo tempo — a
    minha e a de outra sessão trabalhando na mesma pasta. Ficamos com a outra,
    que já traz a normalização do árabe. Este teste foi reescrito para valer
    contra ela, e não contra a minha.

O QUE MAIS ME PREOCUPA AQUI
    A varredura lê o MESMO jogo duas vezes, em dois idiomas. Se o cache não
    separar por idioma, o segundo pedido devolve a resposta do primeiro, e o
    nome árabe é preenchido com o latino. Não dá erro. A coluna fica cheia,
    com o conteúdo errado, e a ponte árabe→latim — que é a razão inteira
    desta tabela — deixa de existir sem nenhum sintoma.

    E a passada em árabe não traz nome latino, nem a inversa. Se uma
    sobrescrevesse a outra com vazio, cada varredura apagaria metade do que a
    anterior tinha ganhado.
"""
import ast
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


def _jogador(pid, primeiro, ultimo, curto, camisa="10"):
    return {"playerId": pid, "bibNumber": camisa, "roleLabel": "Midfielder",
            "mediaFirstName": primeiro, "mediaLastName": ultimo,
            "shortName": curto, "nationality": "Saudi Arabia",
            "imagery": {"playerImage_home_middle": f"playerImages/{pid}.webp"}}


class ClienteFalso:
    """Responde diferente por idioma, e conta os pedidos."""

    def __init__(self):
        self.pedidos = []

    def get(self, url, **k):
        self.pedidos.append(url)
        arabe = "locale=ar-SA" in url
        if arabe:
            casa = [_jogador("p1", "محمد", "الدوسري", "الدوسري")]
            fora = [_jogador("p2", "عبدو", "ديالو", "ديالو", "5")]
        else:
            casa = [_jogador("p1", "Mohammed", "Al Dawsari", "M. Al Dawsari")]
            fora = [_jogador("p2", "Abdou", "Diallo", "A. Diallo", "5")]
        corpo = {"home": {"teamId": "t1", "shortName": "Al-Hilal SFC",
                          "fielded": casa, "benched": []},
                 "away": {"teamId": "t2", "shortName": "Al-Nassr FC",
                          "fielded": [], "benched": fora}}

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return corpo
        return R()


def testar():
    falhas.clear()
    liga_spl._CACHE.clear()
    cli = ClienteFalso()

    conferir("lê os dois idiomas", tuple(liga_spl.IDIOMAS), ("en-GB", "ar-SA"))

    jogos = [{"matchId": "m1", "matchDateLocal": "2026-08-26T19:00:00"},
             {"matchId": "m2", "matchDateLocal": "2026-08-20T19:00:00"}]
    pessoas = liga_spl.jogadores_dos_jogos("s1", jogos, cli)
    por_id = {p["spl_id"]: p for p in pessoas}

    # ── as duas escritas, na mesma linha ────────────────────────────────
    conferir("duas pessoas", sorted(por_id), ["p1", "p2"])
    conferir("nome latino", por_id["p1"].get("nome"), "Mohammed Al Dawsari")
    conferir("nome árabe", por_id["p1"].get("nome_ar"), "محمد الدوسري")
    conferir("visitante também tem as duas",
             (por_id["p2"].get("nome"), por_id["p2"].get("nome_ar")),
             ("Abdou Diallo", "عبدو ديالو"))
    # Este é o defeito silencioso: se o cache ignorasse o idioma, as duas
    # colunas viriam iguais e ninguém perceberia.
    ok(por_id["p1"]["nome"] != por_id["p1"]["nome_ar"],
       "latim e árabe vieram iguais — o cache não separou por idioma")

    # ── e nenhuma passada apaga a outra ─────────────────────────────────
    for pid in ("p1", "p2"):
        ok(por_id[pid].get("nome") and por_id[pid].get("nome_ar"),
           f"{pid} perdeu uma das escritas ao juntar as passadas")

    # ── quem entra e quem não entra ─────────────────────────────────────
    conferir("o banco também conta",
             por_id["p2"].get("camisa"), "5")
    conferir("posição veio", por_id["p1"].get("posicao"), "Midfielder")
    conferir("foto é o caminho, não a URL montada",
             por_id["p1"].get("foto"), "playerImages/p1.webp")
    # Sem playerId a pessoa não existe para esta tabela.
    sem_id = liga_spl.jogadores_dos_jogos(
        "s1", [], cli)
    conferir("sem jogo, sem gente", sem_id, [])

    # ── a data mais recente é a que manda o clube ───────────────────────
    # Alguém que trocou de time no meio da temporada tem que ficar com o
    # clube do jogo mais novo, não com o do primeiro que a varredura leu.
    conferir("visto_em é a data mais recente",
             por_id["p1"].get("visto_em"), "2026-08-26")

    # ── o cache poupa a rede ────────────────────────────────────────────
    antes = len(cli.pedidos)
    liga_spl.jogadores_dos_jogos("s1", jogos, cli)
    conferir("segunda varredura não vai à rede", len(cli.pedidos), antes)
    conferir("um pedido por jogo e por idioma", antes, 4)

    # ── a gravação não pode apagar o árabe ──────────────────────────────
    fonte = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    arvore = ast.parse(fonte)
    fn = next((n for n in ast.walk(arvore)
               if isinstance(n, ast.FunctionDef) and n.name == "salvar_jogadores"), None)
    ok(fn is not None, "não achei salvar_jogadores")
    if fn:
        corpo = ast.unparse(fn)
        for campo in ("nome", "nome_ar", "foto", "clube"):
            ok(f"COALESCE(NULLIF(EXCLUDED.{campo}" in corpo,
               f"o UPDATE deixa {campo} ser apagado por um valor vazio")

    # Uma tabela `jogador` só. Já houve duas ao mesmo tempo, com colunas
    # diferentes: o Postgres obedece o primeiro CREATE e o Python a última
    # função, então o INSERT ia procurar coluna que não existia.
    conferir("uma tabela jogador",
             fonte.count("CREATE TABLE IF NOT EXISTS jogador"), 1)
    for nome in ("salvar_jogadores", "listar_jogadores", "contar_jogadores"):
        quantas = sum(1 for n in arvore.body
                      if isinstance(n, ast.FunctionDef) and n.name == nome)
        conferir(f"{nome} definida uma vez", quantas, 1)

    # ── a varredura ─────────────────────────────────────────────────────
    fonte_main = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    v = next((n for n in ast.walk(ast.parse(fonte_main))
              if isinstance(n, ast.FunctionDef) and n.name == "varrer_jogadores"), None)
    ok(v is not None, "não achei varrer_jogadores")
    if v:
        corpo = ast.unparse(v)
        ok("jogadores_dos_jogos" in corpo,
           "a varredura não usa a leitura do liga_spl — voltou a ter duas cópias")
        ok("limite_de_jogos" in corpo,
           "não dá para rodar uma varredura curta antes de soltar a temporada")

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    print("  ✓ jogadores: duas escritas na mesma linha, cache por idioma, "
          "uma tabela só")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
