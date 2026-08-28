"""
A varredura que monta a tabela de jogadores.

NOTA SOBRE ESTE ARQUIVO
    Existiram duas implementações deste passo ao mesmo tempo. A explicação é
    banal: uma sessão anterior bateu no limite de uso e deixou trabalho no
    diretório sem commit; a sessão seguinte não viu e escreveu a sua. O
    resultado foi duas tabelas `jogador` com colunas diferentes e duas
    `salvar_jogadores` — e o Postgres obedece o primeiro CREATE enquanto o
    Python obedece a última função.

    Ficou a versão com normalização de árabe. Os testes de "definida uma vez"
    e "uma tabela jogador" mais abaixo existem para isso não voltar em
    silêncio.

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

    # ── o cruzamento com a API-Football ─────────────────────────────────
    # Mesmo cuidado do Transfermarkt, mais um sinal que lá não existia: a
    # linha de estatística traz o CLUBE. Quando ele discorda, recuso mesmo com
    # o nome batendo — nome igual em clubes diferentes é o caso clássico de
    # duas pessoas, e o erro aqui não aparece na tela, aparece na estatística.
    fn = next((n for n in ast.walk(arvore)
               if isinstance(n, ast.FunctionDef) and n.name == "cruzar_api_football"),
              None)
    ok(fn is not None, "não achei cruzar_api_football")
    if fn:
        corpo = ast.unparse(fn)
        ok("chave_latina" in corpo, "não normaliza o nome antes de comparar")
        ok("len(ids) != 1 or len(candidatos) != 1" in corpo,
           "casa mesmo com mais de um candidato")
        ok("clube_liga != time_af" in corpo,
           "não usa o clube para desempatar — o sinal está lá e não é usado")
        ok("MAX(season)" in corpo,
           "olha temporadas antigas: jogador de 2023 casando com elenco de hoje")
        ok("WHERE af_id = %s AND spl_id <> %s" in corpo,
           "o mesmo id da API-Football pode ir para duas pessoas")
        for chutar in ("SequenceMatcher", "ratio(", "difflib"):
            ok(chutar not in corpo, f"usa {chutar} — semelhança aqui vira gente trocada")

    # ── a abreviação da API-Football ────────────────────────────────────
    # "A. Al Hussain" e "Ali Al Hussain" são a mesma pessoa, e a diferença é
    # formato, não grafia. Resolver por regra é seguro; resolver por
    # semelhança seria adivinhar qual "A." é qual.
    import glossary as _g2
    pares = [("A. Al Hussain", "Ali Al Hussain"),
             ("S. Milinkovic-Savic", "Sergej Milinkovic-Savic"),
             ("T. Hernandez", "Théo Hernández"),
             ("L. Maximiano", "Luís Maximiano"),
             ("J. Brownhill", "Josh Brownhill")]
    for abreviado, inteiro in pares:
        conferir(f"{abreviado} casa com {inteiro}",
                 _g2.partir_por_inicial(abreviado), _g2.inicial_e_resto(inteiro))
    # Nome inteiro NÃO entra pelo caminho da abreviação — senão as duas formas
    # do mesmo nome seriam comparadas como se fossem coisas diferentes.
    conferir("nome completo não é abreviação",
             _g2.partir_por_inicial("Ali Al Hussain"), ("", ""))
    conferir("uma palavra só não tem resto",
             _g2.inicial_e_resto("Ronaldinho"), ("", ""))
    # E a inicial tem que ser respeitada: "A." não pode virar "Saad".
    ok(_g2.partir_por_inicial("A. Al Sharfa") != _g2.inicial_e_resto("Saad Al Sharfa"),
       "a inicial não está sendo conferida — qualquer primeiro nome casaria")

    if fn:
        corpo = ast.unparse(fn)
        ok("por_inicial" in corpo,
           "o cruzamento não usa o índice de inicial — 142 quase-acertos ficam na mesa")
        ok("len(iguais) == 1" in corpo,
           "com dois candidatos de mesma inicial, não exige que o clube desempate")

    # A coluna precisa existir, senão o UPDATE falha calado dentro do except.
    ok("ADD COLUMN IF NOT EXISTS af_id" in fonte,
       "a coluna af_id não é criada na migração")
    ok("com_api_football" in fonte,
       "o resumo não conta quantos já têm id da API-Football")

    # ── a normalização do árabe ─────────────────────────────────────────
    # É o coração de tudo: é ela que vai fazer o nome que a imprensa saudita
    # escreve casar com o que a liga registrou. Cada caso aqui é uma variação
    # que muda a grafia sem mudar a pessoa.
    import glossary
    mesma = [
        ("محمد الدوسري", "como a liga escreve"),
        ("محمد الدَّوسري", "com harakat"),
        ("محمد الدوســري", "com tatweel"),
        ("محمد ٱلدوسري", "com alif wasla"),
        ("محمد الدوسري.", "com pontuação"),
    ]
    chaves = {glossary.chave_arabe(n) for n, _ in mesma}
    conferir(f"{len(mesma)} grafias de Al Dawsari viram uma chave",
             len(chaves), 1)
    ok("ال" not in next(iter(chaves)), "o artigo ال não foi removido")

    # Pessoas DIFERENTES não podem colidir. Normalizar demais é tão ruim
    # quanto normalizar de menos — só que o erro aparece bem mais tarde.
    diferentes = ["محمد الدوسري", "محمد الشهري", "سالم الدوسري", "عبدالله الحمدان"]
    conferir("nomes diferentes continuam diferentes",
             len({glossary.chave_arabe(n) for n in diferentes}), len(diferentes))

    # 'عبدالله' junto e 'عبد الله' separado é a divergência mais comum, e
    # nenhuma regra de letra resolve — a diferença é só onde alguém apertou
    # espaço. Por isso existe a segunda chave, colada.
    junto = glossary.chave_arabe("عبدالله السالم")
    separado = glossary.chave_arabe("عبد الله السالم")
    ok(junto != separado,
       "junto e separado colidiram na chave com espaço — a chave colada "
       "perderia a razão de existir")
    conferir("mas colam na chave sem espaço",
             glossary.chave_colada(junto), glossary.chave_colada(separado))

    conferir("árabe vazio vira vazio", glossary.chave_arabe(""), "")
    conferir("árabe None vira vazio", glossary.chave_arabe(None), "")

    # ── e a chave latina ────────────────────────────────────────────────
    conferir("hífen, espaço e colado viram o mesmo",
             len({glossary.chave_latina(n)
                  for n in ["Al-Hilal", "Al Hilal", "AlHilal", "AL HILAL"]}), 1)
    conferir("acento não separa pessoa",
             glossary.chave_latina("Donovan Léon"),
             glossary.chave_latina("Donovan Leon"))
    conferir("latino vazio vira vazio", glossary.chave_latina(None), "")
    # E aqui também: nomes diferentes não podem colidir.
    ok(glossary.chave_latina("Al Ahmari") != glossary.chave_latina("Al Ghamdi"),
       "dois sobrenomes diferentes viraram a mesma chave latina")

    # ── o cruzamento com o Transfermarkt ────────────────────────────────
    # Aqui um erro não aparece na tela: aparece meses depois, numa estatística
    # que ninguém sabe explicar. Por isso o casamento é exato e único, e as
    # regras estão escritas no código — este bloco cobra que continuem lá.
    fn = next((n for n in ast.walk(arvore)
               if isinstance(n, ast.FunctionDef) and n.name == "cruzar_transfermarkt"),
              None)
    ok(fn is not None, "não achei cruzar_transfermarkt")
    if fn:
        corpo = ast.unparse(fn)
        ok("chave_latina" in corpo,
           "o cruzamento não normaliza o nome antes de comparar")
        ok("len(ids) != 1 or len(candidatos) != 1" in corpo,
           "o cruzamento casa mesmo quando há mais de um candidato")
        ok("WHERE tm_id = %s AND spl_id <> %s" in corpo,
           "o mesmo id do Transfermarkt pode ser dado a duas pessoas")
        for chutar in ("SequenceMatcher", "ratio(", "difflib", "levenshtein"):
            ok(chutar not in corpo,
               f"o cruzamento usa {chutar} — semelhança aqui vira gente trocada")

    # E a normalização tem que servir para casar as duas fontes de verdade:
    # a liga escreve 'Mohammed Al Dawsari', o Transfermarkt 'Mohammed Al-Dawsari'.
    import glossary as _g
    conferir("liga e Transfermarkt casam pela chave",
             _g.chave_latina("Mohammed Al Dawsari"),
             _g.chave_latina("Mohammed Al-Dawsari"))
    # Mas dois jogadores diferentes do mesmo clã, não.
    ok(_g.chave_latina("Hamed Al Ahmari") != _g.chave_latina("Khaled Al Ahmari"),
       "dois Al Ahmari viraram a mesma chave")

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    print("  ✓ jogadores: duas escritas na mesma linha, cache por idioma, "
          "uma tabela só")
    print("  ✓ normalização: árabe e latim colapsam variação sem colar "
          "pessoas diferentes")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
