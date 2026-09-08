"""
Onde cada jogador fica no campinho. UM lugar só.

POR QUE ISTO VIROU MÓDULO (08/09/26)
    Existiam duas tabelas de posição, e ninguém sabia.

    A primeira é esta, escolhida no seletor de formação da guia Elencos. A
    segunda vivia dentro de elenco_tm.posicoes_no_campo(), e era a que valia
    quando o app carregava a escalação REAL do último jogo — que é o caminho
    normal, o que acontece sozinho ao abrir o clube. Ela distribuía as casas
    numa grade regular: x em (c+1)/(n+1) e y descendo em passo fixo. Quatro
    zagueiros saíam em 20, 40, 60 e 80, todos na mesma altura, colados.

    Então eu abri as sete formações desta tabela, medi, testei, e o Vini abriu
    a guia e viu a 4-2-3-1 exatamente como antes — porque aquele era o jogo que
    estava carregado, e a 4-2-3-1 vinha da OUTRA tabela. "É a única que nada
    mudou" foi a descrição exata do defeito, e ela apontava para um arquivo que
    eu nem tinha olhado.

    Agora só existe esta. O elenco_tm pergunta aqui.

COMO LER AS COORDENADAS
    x e y em % do campo visto de cima. y=95 é a área do goleiro, y=12 é a linha
    do ataque. A ordem da lista é a da súmula: goleiro, defesa, meio, ataque, e
    dentro de cada linha da esquerda para a direita — é isso que permite casar
    esta tabela com os titulares que o Transfermarkt devolve.

    A letra é o setor (G/D/M/A) e guia o preenchimento automático.

POR QUE OS NÚMEROS SÃO ESTES
    A placa de nome é larga: no pior caso ("ABDULHAMID", "MILINKOVIC") passa de
    230px numa arte de 1080. Onze dessas não cabem numa distribuição regular.

    Duas coisas foram aprendidas apanhando:

    1. Aperto lateral não resolve. A primeira versão fechava o leque em 20%
       para toda placa ficar sobre a grama, e o resultado foi os onze
       espremidos no miolo. Hoje x=0 é a linha lateral e a placa da ponta passa
       POR CIMA dela — só a FOTO precisa cair no gramado.
    2. Os setores precisam de ar entre eles. Goleiro, defesa, meio e ataque
       ficam em faixas separadas de propósito; encostar as faixas fazia a arte
       parecer um amontoado mesmo sem nenhuma placa se sobrepor.

    teste_campo_perspectiva.py mede a sobreposição de verdade, com o nome mais
    comprido possível em cada posição, e a foto contra os pixels da arte.
"""

QUADROS: dict[str, list[tuple[float, float, str]]] = {
    "4-3-3":   [(50,95,"G"),(6,68,"D"),(33,78,"D"),(67,78,"D"),(94,68,"D"),
                (20,48,"M"),(50,58,"M"),(80,48,"M"),
                (2,20,"A"),(50,12,"A"),(98,20,"A")],
    "4-2-3-1": [(50,95,"G"),(6,68,"D"),(33,78,"D"),(67,78,"D"),(94,68,"D"),
                (32,58,"M"),(68,58,"M"),(8,34,"M"),(50,42,"M"),(92,34,"M"),
                (50,12,"A")],
    "4-4-2":   [(50,95,"G"),(6,68,"D"),(33,78,"D"),(67,78,"D"),(94,68,"D"),
                (6,46,"M"),(33,56,"M"),(67,56,"M"),(94,46,"M"),
                (22,14,"A"),(78,14,"A")],
    "4-1-4-1": [(50,95,"G"),(6,68,"D"),(33,78,"D"),(67,78,"D"),(94,68,"D"),
                (50,64,"M"),(6,36,"M"),(28,44,"M"),(72,44,"M"),(94,36,"M"),
                (50,12,"A")],
    "3-5-2":   [(50,95,"G"),(18,76,"D"),(50,82,"D"),(82,76,"D"),
                (5,58,"M"),(28,42,"M"),(50,50,"M"),(72,42,"M"),(95,58,"M"),
                (22,14,"A"),(78,14,"A")],
    "3-4-3":   [(50,95,"G"),(18,76,"D"),(50,82,"D"),(82,76,"D"),
                (6,50,"M"),(33,58,"M"),(67,58,"M"),(94,50,"M"),
                (2,20,"A"),(50,12,"A"),(98,20,"A")],
    "5-3-2":   [(50,95,"G"),(4,62,"D"),(20,78,"D"),(50,84,"D"),(80,78,"D"),(96,62,"D"),
                (22,46,"M"),(50,54,"M"),(78,46,"M"),
                (22,14,"A"),(78,14,"A")],
}

PADRAO = "4-3-3"


def coordenadas(formacao: str | None, quantidade: int = 11) -> list[tuple[float, float]]:
    """As casas de uma formação, na ordem em que a súmula lista os titulares.

    Quando a formação é uma das desenhadas aqui, devolve o desenho — é o
    caminho de 99% dos jogos, e é o que faz a escalação carregada do último
    jogo ter o mesmo espaçamento de quando você escolhe a formação à mão.

    Quando não é (um 4-3-1-2, um time com dez em campo), cai numa grade
    regular. Fica pior, e fica de propósito: inventar um desenho bonito para
    uma formação que ninguém desenhou é chutar posição de jogador."""
    casas = QUADROS.get((formacao or "").strip())
    if casas and len(casas) == quantidade:
        return [(x, y) for x, y, _ in casas]

    linhas = [1]
    if formacao:
        try:
            linhas += [int(p) for p in formacao.split("-")]
        except ValueError:
            linhas = [1]
    if sum(linhas) != quantidade:
        linhas = [1, 4, 3, 3] if quantidade == 11 else [quantidade]

    coords, total = [], len(linhas)
    for li, n in enumerate(linhas):
        y = 95.0 if total <= 1 else 95.0 - li * (83.0 / (total - 1))
        for c in range(n):
            # Espalhado até quase a lateral, e não em (c+1)/(n+1): a versão
            # antiga entregava 20/40/60/80 para quatro zagueiros, com as placas
            # uma em cima da outra.
            x = 50.0 if n == 1 else 4.0 + c * (92.0 / (n - 1))
            coords.append((round(x, 1), round(y, 1)))
    return coords
