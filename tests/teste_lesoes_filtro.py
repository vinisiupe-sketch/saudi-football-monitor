"""
Filtro por clube na guia Lesões, e a sub-aba que confere na API.

POR QUE A SUB-ABA EXISTE
    O monitor de lesões lê NOTÍCIA. Ele é bom no que a imprensa cobre — o
    titular do Al-Hilal que rompeu o ligamento sai em todo lugar — e cego no
    que ela não cobre: o reserva do Al-Fayha que ninguém noticiou não existe
    para ele. A API-Football vê a lista oficial de ausentes, sem passar pelo
    interesse editorial de ninguém.

    Nenhuma das duas manda na outra, então a tela mostra as duas e marca a
    diferença. Fonte que discorda da outra é informação, não defeito.

A ARMADILHA QUE ESTE ARQUIVO VIGIA DE PERTO
    A API-Football só devolve ausências onde `coverage.injuries` é verdadeiro.
    Se a liga saudita não estiver coberta, a chamada volta com sucesso e lista
    VAZIA. Na tela, "a API não cobre isto" e "ninguém está machucado" seriam a
    mesma tela em branco — e a segunda leitura é a que o Vini faria, porque é
    a que faz sentido numa guia de lesões. Publicar uma escalação confiando
    nisso é o estrago.

    Por isso a rota devolve `cobertura` e a tela diz qual dos dois casos é.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _corpo(nome_da_funcao: str) -> str:
    """O código-fonte de uma função só, para não varrer o main.py inteiro."""
    mod = ast.parse(FONTE)
    for n in ast.walk(mod):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name == nome_da_funcao:
            return ast.get_source_segment(FONTE, n) or ""
    return ""


def testar():
    falhas.clear()
    tela = _corpo("_page_lesoes_impl")
    rota = _corpo("api_ausencias_af")

    ok(tela, "sumiu a função que monta a guia Lesões")
    ok(rota, "sumiu a rota que consulta as ausências na API-Football")

    # ── 1. o filtro por clube ────────────────────────────────────────────
    ok('data-clube="' in tela,
       "o card de lesão perdeu o data-clube — é por ele que o filtro esconde "
       "e mostra")
    ok("_html.escape(club" in tela,
       "o nome do clube entra no atributo sem escapar. Ele vem de notícia "
       "raspada: um nome com aspas fecha o atributo cedo e quebra o card")
    ok('id="filtroClube"' in tela and "filtrarPorClube()" in tela,
       "sumiu o seletor de clube da guia Lesões")
    ok("opcoes_clube" in tela,
       "as opções do filtro deixaram de ser montadas no servidor")
    # A lista sai das lesões que ESTÃO na tela. Clube sem ninguém machucado
    # como opção é uma opção que só devolve tela vazia.
    ok("for i in injuries" in tela and 'i.get("club")' in tela,
       "a lista de clubes do filtro não vem mais das lesões carregadas")
    ok("contaAtivas" in tela and "conta.textContent" in tela,
       "a contagem ao lado do título não acompanha mais o filtro — a tela "
       "mostraria três cards com o título dizendo 'Ativas (37)'")
    # Os DOIS lados: criar o recado e reencontrá-lo na volta seguinte. Sem o
    # querySelector, cada troca de clube empilharia um recado novo; sem a
    # criação, não há recado nenhum. A primeira versão deste teste só
    # procurava o nome da classe, e passava com o querySelector arrancado —
    # porque o nome continuava escrito na linha que cria o elemento.
    ok("querySelector('.lsn-filtro-vazio')" in tela,
       "o filtro parou de reencontrar o recado de seção vazia — cada troca "
       "de clube passa a empilhar um recado novo embaixo do anterior")
    ok("'empty-state lsn-filtro-vazio'" in tela,
       "sumiu a criação do recado de seção vazia: filtrar por um clube sem "
       "ninguém machucado devolveria um branco com cara de tela quebrada")

    # ── 2. UMA LISTA SÓ, sem sub-aba ─────────────────────────────────────
    # O Transfermarkt chegou como sub-aba e o Vini cortou: "Transfermarkt é
    # mais uma fonte, então tome o TM como uma fonte que apareceria no
    # histórico". Ele tem razão. Sub-aba diz "isto é outra coisa"; o TM não é
    # outra coisa, é a mesma coisa sabida por outro caminho — e separá-lo
    # obrigava a olhar duas telas para responder uma pergunta só.
    # Procuro o USO (a classe emitida no HTML e a função que troca de painel),
    # e não a palavra: o comentário que explica por que as sub-abas saíram
    # cita o nome delas, e a primeira versão deste teste falhava na própria
    # documentação. Já aconteceu quatro vezes neste projeto.
    ok('class="lsn-abas"' not in tela and "mostrarLesoes(" not in tela,
       "voltaram as sub-abas na guia Lesões. O Transfermarkt é mais uma "
       "fonte da MESMA lista, não uma tela paralela")
    # A CHAMADA, e não a menção. Comentar a linha deixa o nome no arquivo, e
    # a primeira versão deste teste passava com a junção desligada.
    ok("\njuntarTransfermarkt();" in tela,
       "sumiu a CHAMADA que junta o Transfermarkt à lista principal — o "
       "nome da função pode estar aí e ela nunca rodar")
    ok("linha.className = 'lsn-fonte-tm';" in tela,
       "sumiu a linha que marca o que veio do Transfermarkt dentro do card — "
       "sem ela, não dá para saber qual fonte disse o quê")
    ok("lsnSoTM" in tela,
       "sumiu a seção de quem SÓ o Transfermarkt conhece. É o reserva que "
       "ninguém noticiou, e é metade do valor de ter a segunda fonte")

    # ── 3. a fonte é o TM, não a API ─────────────────────────────────────
    # A API-Football NÃO cobre ausências nesta liga (coverage.injuries =
    # false, conferido com a chave do Vini). Ela respondia com SUCESSO e lista
    # VAZIA, para sempre — foi isso que ele relatou como "não tá trazendo
    # nada". Uma fonte que só sabe dizer "nada" não confere coisa nenhuma.
    ok("/api/lesoes/transfermarkt" in tela,
       "a guia voltou a consultar a API-Football, que não cobre ausências "
       "nesta liga e sempre devolve lista vazia")
    # A rota da API continua existindo — ela volta a servir no dia em que a
    # cobertura aparecer, e apagá-la agora seria jogar fora a conferência do
    # coverage junto.
    ok("coverage" in rota,
       "a rota antiga perdeu a conferência do coverage.injuries, que é o que "
       "distingue 'a API não sabe' de 'ninguém está fora'")
    ok("NÃO quer dizer" in tela,
       "sumiu o aviso de que lista vazia pode ser falha de leitura, e não "
       "ausência de lesionados")

    # ── 3b. o escudo vem da LIGA, não da tabela de transferências ────────
    # O Al-Nassr de Riade apareceu com o escudo do Al Nasr de Dubai: os dois
    # normalizam para a mesma chave em escudos_por_clube(), que lê a tabela de
    # transferências — com clube do mundo inteiro — e deixa ganhar quem entrou
    # primeiro. O erro é silencioso e convincente: um escudo bonito no lugar
    # errado.
    ok("escudos_da_liga" in tela,
       "a guia voltou a tirar escudo só da tabela de transferências. Lá há "
       "clube do mundo inteiro, e homônimo do Golfo colide na mesma chave — "
       "foi assim que o Al-Nassr saiu com o escudo do Al Nasr de Dubai")
    i_geral = tela.find("escudos_por_clube()")
    i_liga = tela.find("escudos_da_liga(")
    ok(-1 < i_geral < i_liga,
       "a ordem inverteu: o mapa geral precisa entrar PRIMEIRO e o da liga "
       "por cima, senão o homônimo volta a ganhar")

    # E a função da liga tem que sair mesmo do CALENDÁRIO da competição —
    # é de lá que vem a garantia de só haver os 18 clubes da Roshn. Checar só
    # o nome dela na tela deixaria passar uma função que devolve nada.
    banco = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    corpo_liga = banco[banco.find("def escudos_da_liga"):]
    corpo_liga = corpo_liga[:corpo_liga.find("\ndef ", 10)]
    ok("FROM partida_liga" in corpo_liga,
       "escudos_da_liga parou de ler o calendário da competição. É ele que "
       "garante que só existem ali os clubes da liga, sem homônimo")
    ok("media.api-sports.io" in corpo_liga,
       "o escudo da liga deixou de usar o endereço padrão da API-Football, "
       "que é o mesmo das guias Pendurados e Elencos")

    # ── 4. suspensão vem junto, e o tipo cru não se perde ────────────────
    ok("suspend" in rota and "Suspensão" in rota,
       "a rota parou de reconhecer suspensão. O mesmo endpoint da API "
       "devolve lesão E suspensão, e a suspensão é metade do valor dele")
    ok('"tipo_bruto"' in rota,
       "sumiu o tipo_bruto. A API também escreve 'Missing Fixture' e "
       "'Questionable'; traduzir só o que eu previ apaga o resto")

    # ── 5. cruzar com o nosso monitor sem inventar ───────────────────────
    # A marca de "só uma fonte viu" é o motivo de ter a segunda fonte. Na
    # rota ela continua vindo calculada; na tela, quem separa é a junção —
    # o jogador que o TM conhece e a imprensa não vira card próprio.
    ok("no_nosso_monitor" in rota,
       "a rota parou de marcar quem o nosso monitor já conhece")
    ok("Só no Transfermarkt" in tela,
       "sumiu a separação de quem só a segunda fonte viu — é o reserva que "
       "ninguém noticiou, e é metade do valor de ter duas fontes")
    # A normalização de nome, exercitada de verdade — e não procurada no
    # texto. Rodo só ESTA função, num espaço com re e unicodedata, porque ela
    # é pura e o main.py inteiro não sobe sem banco.
    chave_src = _corpo("_chave_de_nome")
    ok(chave_src, "sumiu a normalização de nome usada para cruzar as fontes")
    if chave_src:
        import re as _re
        import unicodedata as _ud
        ns = {"re": _re, "unicodedata": _ud}
        exec(compile(ast.Module(body=[ast.parse(chave_src).body[0]],
                                type_ignores=[]), "<chave>", "exec"), ns)
        chave = ns["_chave_de_nome"]

        ok(chave("Cristiano  RONALDO ") == chave("cristiano ronaldo"),
           "caixa e espaço sobrando voltaram a ser diferença de pessoa")
        ok(chave("Ângelo") == chave("Angelo"),
           "acento voltou a ser diferença: a API escreve 'Angelo' e o "
           "matchsheet escreve 'Ângelo'")
        ok(chave("A. Boulbina") == chave("A Boulbina"),
           "a pontuação do nome abreviado voltou a contar")
        # E o limite: casar por pedaço do nome poria o jogador errado na tela.
        ok(chave("N. Fekir") != chave("Nabil Fekir"),
           "a comparação passou a casar nome abreviado com nome completo. "
           "'N. Fekir' e 'Nabil Fekir' são provavelmente a mesma pessoa — mas "
           "'N. Silva' e 'Neymar Silva' também seriam, e aí a tela marca como "
           "conferido um jogador que ninguém conferiu")
        ok(chave("") == "" and chave(None) == "",
           "nome vazio deixou de virar chave vazia e pode casar com qualquer "
           "outro nome vazio")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ Lesões: filtro por clube com contagem viva, e a conferência "
          "no Transfermarkt casando por id")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
