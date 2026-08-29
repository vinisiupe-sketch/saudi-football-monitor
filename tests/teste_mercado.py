"""
A negociação extraída da notícia, e de quem é o rosto do card.

O QUE ESTE ARQUIVO VIGIA
    Duas coisas, e as duas são sobre não confiar no que veio de fora.

    1. O modelo pode devolver qualquer coisa. Um status inventado
       ('Quase certo') viraria uma categoria fantasma na guia, com um card só,
       que ninguém entende de onde saiu — e o post e a guia passariam a dizer
       palavras diferentes sobre a mesma negociação. O vocabulário é fechado e
       é o do Vini, copiado do gerador de post.

    2. A busca por nome na API-Football devolve homônimos aos montes. Buscar
       'Martinelli' traz 28 resultados e o Gabriel do Arsenal NÃO está nos
       três primeiros: vêm um suíço e dois italianos antes. Isso não é
       hipótese, é o que a sondagem devolveu. Pegar o primeiro resultado poria
       a cara de um zagueiro suíço no card de um ponta do Arsenal — errado, e
       com toda a aparência de certo.

    O desempate é o clube de origem, que a própria notícia informa. Sem ele,
    card sem rosto: é honesto. Rosto errado não é.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import mercado

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


BOM = {"e_negociacao": True, "jogador": "Gabriel Martinelli",
       "jogador_orig": "Gabriel Martinelli", "clube_origem": "Arsenal",
       "clube_destino": "Al Hilal", "status": "Negociação",
       "valor": "40 milhões de euros", "confianca": "alta"}


def testar():
    falhas.clear()

    # ── 1. o caso bom passa inteiro ────────────────────────────────────────
    r = mercado.conferir(dict(BOM))
    conferir("jogador", (r or {}).get("jogador"), "Gabriel Martinelli")
    conferir("destino", (r or {}).get("clube_destino"), "Al Hilal")
    conferir("status", (r or {}).get("status"), "Negociação")
    conferir("valor", (r or {}).get("valor"), "40 milhões de euros")

    # ── 2. status fora da lista é recusado ─────────────────────────────────
    # O vocabulário é o do gerador de post. Se o modelo inventar um valor, a
    # guia ganha uma categoria que não existe em lugar nenhum do app.
    inventado = dict(BOM, status="Quase certo")
    conferir("status inventado não passa", mercado.conferir(inventado), None)
    # Mas diferença de caixa é ruído de formatação, não invenção.
    conferir("caixa diferente é aceita e normalizada",
             (mercado.conferir(dict(BOM, status="negociação")) or {}).get("status"),
             "Negociação")
    ok(all(s in mercado.STATUS for s in
           ("Sondagem", "Acerto", "Melou", "Oficial", "De Saída")),
       "o vocabulário de status perdeu um valor que o gerador de post usa")

    # ── 3. o que não é negociação não vira card ────────────────────────────
    conferir("não é negociação", mercado.conferir({"e_negociacao": False}), None)
    conferir("resposta vazia", mercado.conferir({}), None)
    conferir("resposta que não é dicionário", mercado.conferir("sei lá"), None)
    conferir("sem jogador", mercado.conferir(dict(BOM, jogador="")), None)
    conferir("sem destino", mercado.conferir(dict(BOM, clube_destino=None)), None)
    conferir("jogador de uma letra", mercado.conferir(dict(BOM, jogador="X")), None)
    # Sinal clássico de campo preenchido para não ficar vazio.
    conferir("jogador igual ao clube",
             mercado.conferir(dict(BOM, jogador="Al Hilal")), None)

    # ── 4. um card por NEGOCIAÇÃO, não por jogador ─────────────────────────
    # Decisão do Vini, e é a certa: se dois clubes disputam o mesmo jogador,
    # são duas histórias. Um 'Melou' de uma não pode sujar a outra.
    a = mercado.chave_da_negociacao("Gabriel Martinelli", "Al Hilal")
    b = mercado.chave_da_negociacao("Gabriel Martinelli", "Al Nassr")
    ok(a != b, "o mesmo jogador para dois clubes virou uma negociação só")
    # E a mesma negociação escrita de outro jeito é a mesma.
    c = mercado.chave_da_negociacao("gabriel martinelli", "Al-Hilal")
    conferir("grafia diferente, mesma negociação", c, a)
    d = mercado.chave_da_negociacao("Gabriel Martinelli", "Al Hilal SFC")
    conferir("apelido do clube, mesma negociação", d, a)

    # ── 4b. a mesma negociação escrita de dois jeitos ──────────────────────
    # Caso real do primeiro relatório: 'Ollie Watkins → Al Hilal' com 21
    # fontes e 'Watkins → Al Hilal' com 6 — a mesma transferência partida em
    # dois cards, porque minha chave usava o nome inteiro. A imprensa alterna
    # nome completo e sobrenome na mesma cobertura; isso é o normal dela.
    ok(mercado.mesma_pessoa("Ollie Watkins", "Watkins"),
       "'Watkins' e 'Ollie Watkins' continuam sendo duas pessoas")
    ok(mercado.mesma_pessoa("Moussa Diaby", "Diaby"), "Diaby não juntou")
    ok(mercado.mesma_pessoa("Franck Kessié", "Frank Kessie"),
       "Franck e Frank Kessié continuam separados — é variação de grafia")
    conferir("a chave junta os dois",
             mercado.chave_da_negociacao("Watkins", "Al Hilal"),
             mercado.chave_da_negociacao("Ollie Watkins", "Al Hilal"))

    # E o conserto NÃO pode colar duas pessoas de verdade. Salem e Mohammed Al
    # Dawsari existem os dois, e o sobrenome é o mesmo.
    ok(not mercado.mesma_pessoa("Salem Al Dawsari", "Mohammed Al Dawsari"),
       "colei dois Al Dawsari — o conserto do Watkins criou um problema pior")
    ok(not mercado.mesma_pessoa("Ali Al Hassan", "Fahad Al Hassan"),
       "colei dois Al Hassan")
    # 'Al' é partícula, não sobrenome — e a imprensa cita 'Al Bulayhi' sozinho.
    conferir("o sobrenome ignora o 'Al'",
             mercado.sobrenome("Ali Al Bulayhi"), "bulayhi")
    ok(mercado.mesma_pessoa("Ali Al Bulayhi", "Al Bulayhi"),
       "o sobrenome com artigo, sozinho, virou outra pessoa")

    # ── 4c. agrupar de verdade ─────────────────────────────────────────────
    def passo(quando, status, fonte="x"):
        return {"quando": quando, "status": status, "fonte": fonte, "titulo": ""}

    extracoes = [
        (dict(BOM, jogador="Watkins", clube_destino="Al Hilal",
              clube_origem="", valor="", status="Encaminhado"),
         passo("2026-08-25", "Encaminhado")),
        (dict(BOM, jogador="Ollie Watkins", clube_destino="Al Hilal",
              clube_origem="Aston Villa", valor="58 milhões", status="Acerto"),
         passo("2026-08-26", "Acerto")),
        (dict(BOM, jogador="Watkins", clube_destino="Al Hilal",
              clube_origem="", valor="", status="Anunciado"),
         passo("2026-08-27", "Anunciado")),
        # Outro clube pelo mesmo jogador: negociação DIFERENTE.
        (dict(BOM, jogador="Ollie Watkins", clube_destino="Al Nassr",
              clube_origem="Aston Villa", status="Sondagem"),
         passo("2026-08-24", "Sondagem")),
    ]
    grupos = mercado.agrupar(extracoes)
    conferir("três notícias do Watkins viraram um card só, e o Al Nassr outro",
             len(grupos), 2)
    hilal = next(g for g in grupos if "Hilal" in g["clube_destino"])
    conferir("o card juntou os três passos", len(hilal["passos"]), 3)
    conferir("ficou com o nome mais completo", hilal["jogador"], "Ollie Watkins")
    conferir("o status é o do passo mais recente", hilal["status"], "Anunciado")
    conferir("os passos ficam em ordem",
             [p["quando"] for p in hilal["passos"]],
             ["2026-08-25", "2026-08-26", "2026-08-27"])
    # A nota curta não diz de onde ele sai; a longa diz. Vazio não apaga.
    conferir("a origem veio da notícia que tinha", hilal["clube_origem"],
             "Aston Villa")
    conferir("o valor também", hilal["valor"], "58 milhões")

    # ── 4d. só o mercado daqui ─────────────────────────────────────────────
    # O coletor traz Julián Álvarez para o Barcelona e Igor Paixão para o
    # Sunderland. É notícia de verdade e não é a guia dele.
    ok(mercado.toca_a_liga("Aston Villa", "Al Hilal"), "chegada não passou")
    ok(mercado.toca_a_liga("Al Qadsiah", "Kalamata"),
       "saída de clube saudita não passou — e é notícia dele")
    ok(not mercado.toca_a_liga("Atletico Madrid", "Barcelona"),
       "Álvarez para o Barcelona entrou na guia do futebol saudita")
    ok(not mercado.toca_a_liga("", ""), "negociação sem clube nenhum passou")

    # ── 4e. qual clube a busca devolveu ────────────────────────────────────
    # Eu exigia UM resultado só, e isso derrubou quase todos os rostos:
    # 'Arsenal' devolve o Arsenal, o feminino e o de Sarandí.
    arsenais = [{"id": 42, "nome": "Arsenal"},
                {"id": 500, "nome": "Arsenal W"},
                {"id": 900, "nome": "Arsenal de Sarandí"}]
    conferir("o exato ganha dos parecidos",
             (mercado.escolher_clube("Arsenal", arsenais) or {}).get("id"), 42)
    conferir("resultado único sem exato ainda serve",
             (mercado.escolher_clube("Aston Villa",
                                     [{"id": 66, "nome": "Aston Villa FC"}])
              or {}).get("id"), 66)
    # Dois exatos: aí eu desisto mesmo. 'Al Ahli' existe em meio mundo árabe.
    dois_ahli = [{"id": 1, "nome": "Al Ahli"}, {"id": 2, "nome": "Al-Ahli"}]
    conferir("dois clubes com o mesmo nome não decidem",
             mercado.escolher_clube("Al Ahli", dois_ahli), None)
    # O caso que mais importa aqui, e que eu quase não testei: a notícia diz
    # só 'Manchester'. Nenhum resultado bate exato e são dois clubes de
    # verdade. Pegar o primeiro escolheria entre United e City no cara ou
    # coroa — e o card sairia com o escudo errado, parecendo certo.
    manchesters = [{"id": 33, "nome": "Manchester United"},
                   {"id": 50, "nome": "Manchester City"}]
    conferir("'Manchester' não decide entre United e City",
             mercado.escolher_clube("Manchester", manchesters), None)
    conferir("busca vazia", mercado.escolher_clube("Arsenal", []), None)
    conferir("sem nome procurado", mercado.escolher_clube("", arsenais), None)

    # ── 5. o rosto: quem está na liga sai de graça ─────────────────────────
    import elos
    gente = [
        {"spl_id": "salem", "nome": "Salem Al Dawsari", "nome_ar": "سالم الدوسري"},
        {"spl_id": "moh", "nome": "Mohammed Al Dawsari", "nome_ar": "محمد الدوسري"},
    ]
    indice, _ = elos.indice_de_jogadores(gente)
    conferir("achou na liga",
             mercado.procurar_na_liga("Salem Al Dawsari", indice), "salem")
    conferir("nome árabe também acha",
             mercado.procurar_na_liga("سالم الدوسري", indice), "salem")
    conferir("sobrenome solto não acha ninguém",
             mercado.procurar_na_liga("Al Dawsari", indice), "")
    conferir("quem não é da liga não é forçado",
             mercado.procurar_na_liga("Gabriel Martinelli", indice), "")
    # Se o nome extraído cair em DUAS pessoas da liga, não escolho nenhuma.
    # Acontece quando a notícia fala dos dois e o modelo devolve os dois nomes
    # juntos — e aí pegar o primeiro é sorteio.
    conferir("nome que cai em dois da liga não escolhe nenhum",
             mercado.procurar_na_liga("Salem Al Dawsari e Mohammed Al Dawsari",
                                      indice), "")

    # ── 6. o rosto de quem vem de fora ─────────────────────────────────────
    # Estes são os 28 'Martinelli' de verdade que a sondagem devolveu, na
    # ordem em que vieram. O Gabriel é o quarto.
    candidatos = [
        {"af_id": 1, "nome": "A. Martinelli", "clube": "Servette", "nascimento": "1993-05-30"},
        {"af_id": 2, "nome": "L. Martinelli", "clube": "Pisa", "nascimento": "1988-12-20"},
        {"af_id": 3, "nome": "R. Martinelli", "clube": "Empoli", "nascimento": "1991-04-30"},
        {"af_id": 4, "nome": "Gabriel Martinelli", "clube": "Arsenal", "nascimento": "2001-06-18"},
    ]
    escolhido = mercado.escolher_de_fora("Gabriel Martinelli", candidatos, "Arsenal")
    conferir("o clube de origem escolhe o certo",
             (escolhido or {}).get("af_id"), 4)
    ok((escolhido or {}).get("af_id") != 1,
       "peguei o primeiro resultado — é exatamente o erro que este teste existe "
       "para impedir: cara de suíço no card do ponta do Arsenal")

    # Sem clube de origem, não escolho. Card sem rosto é honesto.
    #
    # O candidato SEM clube abaixo não é invenção para o teste: o endpoint
    # `players/profiles`, que é o que acha alguém sem eu saber onde ele joga,
    # devolve nome, nascimento e foto e NENHUM clube. Então "sem clube dos
    # dois lados" é o caso comum, não a exceção — e sem a guarda o vazio de um
    # lado casaria com o vazio do outro, e o card sairia com a cara de quem a
    # busca devolveu primeiro.
    sem_clube = candidatos + [{"af_id": 11, "nome": "P. Martinelli",
                               "clube": "", "nascimento": "1996-02-02"}]
    conferir("sem clube de origem, ninguém é escolhido",
             mercado.escolher_de_fora("Gabriel Martinelli", sem_clube, ""), None)
    conferir("vazio não casa com vazio",
             mercado.escolher_de_fora("Gabriel Martinelli", sem_clube, "   "), None)
    # Dois do mesmo clube: também não escolho.
    dois = candidatos + [{"af_id": 9, "nome": "J. Martinelli", "clube": "Arsenal",
                          "nascimento": "1999-01-01"}]
    conferir("dois do mesmo clube não desempatam",
             mercado.escolher_de_fora("Gabriel Martinelli", dois, "Arsenal"), None)
    # Clube bate mas o nome não tem nada a ver: recuso.
    outro = [{"af_id": 7, "nome": "Bukayo Saka", "clube": "Arsenal",
              "nascimento": "2001-09-05"}]
    conferir("clube certo com nome sem relação é recusado",
             mercado.escolher_de_fora("Gabriel Martinelli", outro, "Arsenal"), None)
    # A API abrevia o primeiro nome; uma palavra em comum basta.
    abrev = [{"af_id": 8, "nome": "O. Watkins", "clube": "Aston Villa",
              "nascimento": "1995-12-30"}]
    conferir("nome abreviado pela API ainda casa",
             (mercado.escolher_de_fora("Ollie Watkins", abrev, "Aston Villa") or {}).get("af_id"),
             8)
    conferir("lista vazia não inventa",
             mercado.escolher_de_fora("Ollie Watkins", [], "Aston Villa"), None)

    # ── 7. o vocabulário é o MESMO do gerador de post ──────────────────────
    # Se os dois divergirem, a guia e o post vão descrever a mesma negociação
    # com palavras diferentes, e nenhum dos dois vai parecer errado.
    fonte = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    i = fonte.find("status_mercado: escolha o mais adequado entre")
    ok(i > 0, "não achei a lista de status no gerador de post")
    if i > 0:
        trecho = fonte[i:i + 400]
        for s in mercado.STATUS:
            ok(s in trecho,
               f"'{s}' está no mercado.py mas sumiu do gerador de post")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ mercado: status fechado, um card por negociação, e o rosto certo")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
