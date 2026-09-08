"""
Onde cada jogador fica no campinho. UM lugar só, e para QUALQUER formação.

POR QUE ISTO VIROU MÓDULO (08/09/26)
    Existiam duas tabelas de posição, e ninguém sabia.

    A primeira era a do seletor de formação da guia Elencos. A segunda vivia
    dentro de elenco_tm.posicoes_no_campo(), e era a que valia quando o app
    carregava a escalação REAL do último jogo — o caminho normal, o que
    acontece sozinho ao abrir o clube. Ela distribuía as casas numa grade
    regular: x em (c+1)/(n+1), y descendo em passo fixo. Quatro zagueiros
    saíam em 20, 40, 60 e 80, todos na mesma altura, colados.

    Resultado: eu abri as sete formações da primeira tabela, e o Vini viu a
    4-2-3-1 exatamente como antes — porque a dele vinha da segunda.

E POR QUE ELE APRENDEU A DESENHAR SOZINHO (mesmo dia)
    Juntar as duas resolveu as sete formações que eu tinha desenhado à mão. Aí
    o Al Qadsiah entrou num 3-1-4-2, que não estava entre elas, e a linha de
    quatro saiu com as placas uma por cima da outra.

    Desenhar à mão não escala: existem dezenas de arranjos, e o que quebra é
    sempre o que ninguém previu. Então as casas passaram a ser CALCULADAS, com
    as mesmas regras que eu vinha aplicando no olho — e o desenho à mão ficou
    só para as sete formações comuns, onde o ajuste fino vale a pena.

COMO LER AS COORDENADAS
    x e y em % do campo visto de cima. y=95 é a área do goleiro, y=8 é a linha
    de frente. A ordem da lista é a da súmula: goleiro, defesa, meio, ataque, e
    dentro de cada linha da esquerda para a direita — é isso que permite casar
    esta tabela com os titulares que o Transfermarkt devolve.

    A letra é o setor (G/D/M/A) e guia o preenchimento automático.

AS TRÊS REGRAS QUE OS NÚMEROS OBEDECEM
    1. A lateral é liberada. x=0 é a linha lateral, e a placa da ponta passa
       POR CIMA dela. A primeira versão fechava o leque em 20% para toda placa
       ficar sobre a grama, e o resultado foram os onze espremidos no miolo.
       Só a FOTO precisa cair no gramado.
    2. Os setores ficam em faixas separadas, com ar entre elas. Encostar as
       faixas fazia a arte parecer um amontoado mesmo sem nenhuma placa se
       sobrepor.
    3. Quando uma linha tem gente demais para a largura do campo naquela
       altura — e lá no fundo, em perspectiva, o campo é metade da largura —,
       os jogadores saem escalonados em y, alternando. É o mesmo recurso que a
       arte de TV usa.

    teste_campo_perspectiva.py mede tudo isso de verdade: a sobreposição com o
    nome mais comprido possível em cada posição, e a foto contra os pixels da
    arte.
"""

# ── a perspectiva da arte ────────────────────────────────────────────────────
# Medidas tiradas a régua de public/masks/campo-perspectiva.png, em % da imagem
# inteira. Moram aqui porque o cálculo das casas precisa saber a largura do
# campo em cada altura — sem isso não dá para dizer se uma linha de quatro cabe.
# O escalacao_arte importa daqui; a página tem a mesma conta em JavaScript, e o
# teste compara as duas.
PROJ = dict(cx=49.95, y_longe=29.19, y_meio=42.15, y_perto=70.59,
            w_longe=34.54, w_perto=75.78)
APERTO = 1.00

_PB = PROJ["y_longe"]
_PC = (2 * PROJ["y_meio"] - _PB - PROJ["y_perto"]) / (PROJ["y_perto"] - PROJ["y_meio"])
_PA = PROJ["y_meio"] * _PC + 2 * PROJ["y_meio"] - 2 * _PB


def largura_do_campo(y: float) -> float:
    """Largura do gramado naquela altura, em % da arte."""
    v = max(0.0, min(1.0, y / 100))
    py = (_PA * v + _PB) / (_PC * v + 1)
    return (PROJ["w_longe"] + (py - PROJ["y_longe"])
            * (PROJ["w_perto"] - PROJ["w_longe"])
            / (PROJ["y_perto"] - PROJ["y_longe"]))


def projetar(x: float, y: float) -> tuple[float, float, float]:
    """(x,y) do campo visto de cima -> (x%, y%, escala) sobre a arte."""
    u = 0.5 + (x / 100 - 0.5) * APERTO
    v = max(0.0, min(1.0, y / 100))
    py = (_PA * v + _PB) / (_PC * v + 1)
    larg = largura_do_campo(y)
    esc = 0.88 + 0.12 * (larg - PROJ["w_longe"]) / (PROJ["w_perto"] - PROJ["w_longe"])
    return PROJ["cx"] + (u - 0.5) * larg, py, esc


# ── as faixas ────────────────────────────────────────────────────────────────
Y_GOL = 99.0          # o goleiro, dentro da pequena área
Y_DEFESA = 88.0       # a linha de trás, colada no goleiro de propósito: é o
                      # que sobra de espaço para o meio-campo respirar
Y_ATAQUE = 8.0        # o ataque na borda da frente do campinho

# Até onde a linha se abre, POR QUANTIDADE de jogadores nela. Não é uma
# constante só: espalhar uma dupla de centroavantes de ponta a ponta, como a
# primeira versão fazia, põe dois homens de área em cima das laterais. Quem
# precisa da linha lateral é a linha de quatro ou cinco.
ABERTURA = {1: 0.0, 2: 26.0, 3: 12.0, 4: 4.0}
ABERTURA_LARGA = 2.0

# Largura de uma placa no pior caso ("ABDULHAMID" com bandeira), em % da arte.
# Medida, não estimada: 230px numa imagem de 1080.
LARGURA_PLACA = 21.5
FOLGA = 1.5
# Altura da placa em % da ALTURA da arte (35px de 1350), mais um respiro. É a
# separação de TELA que dois jogadores escalonados precisam ter.
ALTURA_PLACA = 35.0 / 1350 * 100
RESPIRO = 0.8

# Separação MÍNIMA entre os centros de duas linhas vizinhas, em % da altura da
# arte. São dois raios de foto (43px cada), mais o quanto a placa desce abaixo
# do centro (35 de altura menos 12 que ela monta sobre a foto), mais folga:
# ~112px numa imagem de 1350. É esta conta que decide até onde o ataque avança.
ENTRE_LINHAS = (43 + 43 + 35 - 12 + 6) / 1350 * 100


def _escalonamento(y: float) -> float:
    """Quantas unidades de y separam duas placas na tela, naquela altura.

    Não é constante, e essa foi a armadilha: perto do goleiro 9 unidades de y
    valem 40px de tela; lá na frente, em perspectiva, valem 8. Escalonar por um
    número fixo resolvia a linha de quatro do meio-campo e não resolvia a do
    ataque — foi assim que o 4-2-4 continuou com as placas empilhadas depois de
    eu "consertar" o escalonamento."""
    # O alvo não é a altura da placa: é a placa de um encostando na FOTO do
    # outro. Escalonar só o suficiente para as placas não se cruzarem deixava a
    # placa do ala pousada na cabeça do volante — 46px onde eram precisos 72.
    alvo = (43 + ALTURA_PLACA * 13.5 - 12 + 6) / 1350 * 100
    base = _altura_na_tela(y)
    d = 0.5
    while d < 45.0:
        if abs(_altura_na_tela(min(96.0, y + d)) - base) >= alvo:
            return d
        d += 0.5
    return 45.0


def _altura_na_tela(y: float) -> float:
    v = max(0.0, min(1.0, y / 100))
    return (_PA * v + _PB) / (_PC * v + 1)


def _y_da_altura(py: float) -> float:
    """O caminho de volta: dada uma altura na tela, qual y do campo cai ali.

    Existe porque as linhas precisam ficar igualmente espaçadas NA TELA, e não
    em unidades de campo. Espaçar em y é o que fazia a defesa e o meio terem um
    vão enorme enquanto o ataque se amontoava: lá no fundo, em perspectiva, 20
    unidades de y valem um punhado de pixels."""
    v = (py - _PB) / (_PA - _PC * py)
    return max(0.0, min(100.0, v * 100))


_ALT_DEFESA = _altura_na_tela(Y_DEFESA)
_ALT_ATAQUE = _altura_na_tela(Y_ATAQUE)


def _setor(indice: int, total: int) -> str:
    if indice == 0:
        return "G"
    if indice == 1:
        return "D"
    return "A" if indice == total - 1 else "M"


def _linhas(formacao: str | None, quantidade: int) -> list[int]:
    """'4-2-3-1' -> [1, 4, 2, 3, 1]. O 1 da frente é o goleiro."""
    linhas = [1]
    if formacao:
        try:
            linhas += [int(p) for p in str(formacao).split("-")]
        except ValueError:
            linhas = [1]
    if sum(linhas) != quantidade or any(n <= 0 for n in linhas):
        linhas = [1, 4, 3, 3] if quantidade == 11 else [quantidade]
    return linhas


def _aperta(n: int, y: float) -> bool:
    """A linha cabe lado a lado nessa altura, ou vai ter que escalonar?

    O passo entre dois vizinhos é em % do CAMPO; a placa é em % da ARTE. A
    conversão é a largura do campo naquela altura — e é justamente ela que
    encolhe lá no fundo, que foi onde a linha de quatro do 3-1-4-2 se
    atropelou."""
    if n <= 1:
        return False
    borda = ABERTURA.get(n, ABERTURA_LARGA)
    passo = (100 - 2 * borda) / (n - 1) / 100 * largura_do_campo(y)
    return passo < LARGURA_PLACA + FOLGA


def _vao_entre_linhas(linhas: list[int]) -> float:
    """Quanto sobra, em % da altura da arte, entre duas linhas vizinhas.

    Serve só para documentar o limite: entre a defesa e o ataque cabem 373px de
    tela, e duas linhas vizinhas precisam de ~115px (dois raios de foto, mais o
    que a placa desce abaixo do centro, mais folga). Ou seja: quatro linhas de
    campo cabem, cinco não cabem — e com cinco a placa de um vai encostar na
    foto do outro, faça o que fizer. Preferi que isso ficasse escrito a fingir
    que uma conta esperta resolve.

    Tentei antes recuar o ataque para "abrir espaço" e o efeito é o contrário:
    recuar o ataque APROXIMA as linhas, porque o vão é medido da defesa até
    ele."""
    de_campo = len(linhas) - 1
    return ((_ALT_DEFESA - _ALT_ATAQUE) / (de_campo - 1)) if de_campo > 1 else 99.0


def desenhar(formacao: str | None, quantidade: int = 11) -> list[tuple[float, float, str]]:
    """Calcula as casas de qualquer formação, seguindo as regras do topo."""
    linhas = _linhas(formacao, quantidade)
    de_campo = len(linhas) - 1        # linhas fora o goleiro
    casas: list[tuple[float, float, str]] = []

    for i, n in enumerate(linhas):
        if i == 0:
            casas.append((50.0, Y_GOL, "G"))
            continue

        # Igualmente espaçadas NA TELA, e não em unidades de campo — ver
        # _y_da_altura(). Espaçar em y deixava um vão enorme entre a defesa e o
        # meio e amontoava o ataque, porque a perspectiva comprime o fundo.
        if de_campo <= 1:
            y = Y_DEFESA
        else:
            y = _y_da_altura(_ALT_DEFESA - (i - 1)
                             * (_ALT_DEFESA - _ALT_ATAQUE) / (de_campo - 1))
        borda = ABERTURA.get(n, ABERTURA_LARGA)
        xs = ([50.0] if n == 1
              else [borda + c * (100 - 2 * borda) / (n - 1) for c in range(n)])

        # Escalona alternado e centrado na faixa: metade sobe, metade desce.
        # Empurrar todo mundo para o mesmo lado comeria o respiro da linha
        # seguinte. O tamanho do passo vem da perspectiva, não de um número
        # fixo — ver _escalonamento().
        passo_y = _escalonamento(y) if _aperta(n, y) else 0.0
        setor = _setor(i, len(linhas))
        for c, x in enumerate(xs):
            desloca = (passo_y / 2 if c % 2 else -passo_y / 2)
            casas.append((round(x, 1), round(max(4.0, min(96.0, y + desloca)), 1),
                          setor))
    return casas


# ── as sete comuns, desenhadas à mão ────────────────────────────────────────
# O cálculo acima resolve qualquer formação. Estas sete são 99% dos jogos, e
# aqui o ajuste fino vale o trabalho: dá para abrir um meia, recuar um volante,
# coisas que uma regra geral não sabe fazer.
# ── as formações prontas ────────────────────────────────────────────────────
# Vinte e quatro arranjos, incluindo todos os que aparecem na liga saudita. Não
# foram escolhidos no olho: parti do cálculo acima e ajustei SÓ duas coisas por
# linha — a altura dela e se ela escalona — até o medidor de sobreposição zerar
# com o nome mais comprido possível em todas as posições.
#
# Ajustar só isso é o que mantém a arte arrumada. Tentei antes deixar um
# recozimento mexer em cada jogador livremente: ele zerava a sobreposição e
# devolvia uma zaga em 85, 90, 84 e 92, torta, que ninguém publicaria.
#
# O que não estiver aqui cai no desenhar(), que segue as mesmas regras.
QUADROS: dict[str, list[tuple[float, float, str]]] = {
    "4-3-3":    [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(12,57.8,"M"),(50,57.8,"M"),(88,57.8,"M"),
                 (12,4,"A"),(50,20.4,"A"),(88,4,"A")],
    "4-2-3-1":  [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(26,70.9,"M"),(74,70.9,"M"),(12,43.8,"M"),
                 (50,43.8,"M"),(88,43.8,"M"),(50,8,"A")],
    "4-4-2":    [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(4,53.8,"M"),(34.7,65.8,"M"),(65.3,53.8,"M"),
                 (96,65.8,"M"),(26,11.8,"A"),(74,11.8,"A")],
    "4-1-4-1":  [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(50,70.9,"M"),(4,39,"M"),(34.7,53.5,"M"),
                 (65.3,39,"M"),(96,53.5,"M"),(50,8,"A")],
    "3-5-2":    [(50,99,"G"),(12,88,"D"),(50,88,"D"),(88,88,"D"),(2,49.6,"M"),
                 (26,67.6,"M"),(50,49.6,"M"),(74,67.6,"M"),(98,49.6,"M"),
                 (26,11.8,"A"),(74,11.8,"A")],
    "3-4-3":    [(50,99,"G"),(12,88,"D"),(50,88,"D"),(88,88,"D"),(4,53.8,"M"),
                 (34.7,65.8,"M"),(65.3,53.8,"M"),(96,65.8,"M"),(12,4,"A"),
                 (50,20.4,"A"),(88,4,"A")],
    "5-3-2":    [(50,99,"G"),(2,83.5,"D"),(26,91,"D"),(50,83.5,"D"),
                 (74,91,"D"),(98,83.5,"D"),(12,57.8,"M"),(50,57.8,"M"),
                 (88,57.8,"M"),(26,11.8,"A"),(74,11.8,"A")],
    "3-1-4-2":  [(50,99,"G"),(12,88,"D"),(50,88,"D"),(88,88,"D"),(50,70.9,"M"),
                 (4,39,"M"),(34.7,53.5,"M"),(65.3,39,"M"),(96,53.5,"M"),
                 (26,7.8,"A"),(74,7.8,"A")],
    "4-3-1-2":  [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(12,69.2,"M"),(50,69.2,"M"),(88,69.2,"M"),
                 (50,46.3,"M"),(26,11.8,"A"),(74,11.8,"A")],
    "4-4-1-1":  [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(4,70.9,"M"),(34.7,70.9,"M"),(65.3,70.9,"M"),
                 (96,70.9,"M"),(50,46.3,"M"),(50,8,"A")],
    "4-1-3-2":  [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(50,70.9,"M"),(12,43.8,"M"),(50,43.8,"M"),
                 (88,43.8,"M"),(26,11.8,"A"),(74,11.8,"A")],
    "4-3-2-1":  [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(12,69.2,"M"),(50,69.2,"M"),(88,69.2,"M"),
                 (26,46.2,"M"),(74,46.2,"M"),(50,8,"A")],
    "4-5-1":    [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(2,49.6,"M"),(26,67.6,"M"),(50,49.6,"M"),
                 (74,67.6,"M"),(98,49.6,"M"),(50,8,"A")],
    "5-4-1":    [(50,99,"G"),(2,83.5,"D"),(26,91,"D"),(50,83.5,"D"),
                 (74,91,"D"),(98,83.5,"D"),(4,53.8,"M"),(34.7,65.8,"M"),
                 (65.3,53.8,"M"),(96,65.8,"M"),(50,8,"A")],
    "3-4-2-1":  [(50,99,"G"),(12,88,"D"),(50,88,"D"),(88,88,"D"),(4,70.9,"M"),
                 (34.7,70.9,"M"),(65.3,70.9,"M"),(96,70.9,"M"),(26,46.2,"M"),
                 (74,46.2,"M"),(50,8,"A")],
    "3-4-1-2":  [(50,99,"G"),(12,88,"D"),(50,88,"D"),(88,88,"D"),(4,70.9,"M"),
                 (34.7,70.9,"M"),(65.3,70.9,"M"),(96,70.9,"M"),(50,46.3,"M"),
                 (26,11.8,"A"),(74,11.8,"A")],
    "4-2-2-2":  [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(26,70.9,"M"),(74,70.9,"M"),(26,46.2,"M"),
                 (74,46.2,"M"),(26,11.8,"A"),(74,11.8,"A")],
    "4-1-2-1-2":[(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(50,75.7,"M"),(26,59.8,"M"),(74,59.8,"M"),
                 (50,38.4,"M"),(26,6,"A"),(74,6,"A")],
    "5-2-3":    [(50,99,"G"),(2,83.5,"D"),(26,91,"D"),(50,83.5,"D"),
                 (74,91,"D"),(98,83.5,"D"),(26,59.8,"M"),(74,59.8,"M"),
                 (12,4,"A"),(50,20.4,"A"),(88,4,"A")],
    "5-2-2-1":  [(50,99,"G"),(2,83.5,"D"),(26,91,"D"),(50,83.5,"D"),
                 (74,91,"D"),(98,83.5,"D"),(26,70.9,"M"),(74,70.9,"M"),
                 (26,46.2,"M"),(74,46.2,"M"),(50,8,"A")],
    "4-2-4":    [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(26,59.8,"M"),(74,59.8,"M"),(4,4,"A"),
                 (34.7,32.3,"A"),(65.3,4,"A"),(96,32.3,"A")],
    "3-3-4":    [(50,99,"G"),(12,88,"D"),(50,88,"D"),(88,88,"D"),(12,57.8,"M"),
                 (50,57.8,"M"),(88,57.8,"M"),(4,4,"A"),(34.7,32.3,"A"),
                 (65.3,4,"A"),(96,32.3,"A")],
    "4-6-0":    [(50,99,"G"),(4,88,"D"),(34.7,88,"D"),(65.3,88,"D"),
                 (96,88,"D"),(12,57.8,"M"),(50,57.8,"M"),(88,57.8,"M"),
                 (12,4,"A"),(50,20.4,"A"),(88,4,"A")],
    "3-5-1-1":  [(50,99,"G"),(12,88,"D"),(50,88,"D"),(88,88,"D"),(2,58.4,"M"),
                 (26,73.4,"M"),(50,58.4,"M"),(74,73.4,"M"),(98,58.4,"M"),
                 (50,35.4,"M"),(50,4,"A")],
}

PADRAO = "4-3-3"


def coordenadas(formacao: str | None, quantidade: int = 11) -> list[tuple[float, float]]:
    """As casas de uma formação, na ordem em que a súmula lista os titulares.

    Desenho à mão quando existe; cálculo quando não. Os dois caminhos passam
    pelas mesmas checagens do teste, com a diferença de que o desenho à mão
    fica um pouco mais bonito."""
    casas = QUADROS.get((formacao or "").strip())
    if not (casas and len(casas) == quantidade):
        casas = desenhar(formacao, quantidade)
    return [(x, y) for x, y, _ in casas]


def casas(formacao: str | None, quantidade: int = 11) -> list[tuple[float, float, str]]:
    """Como coordenadas(), mas trazendo junto o setor de cada casa."""
    achado = QUADROS.get((formacao or "").strip())
    if achado and len(achado) == quantidade:
        return list(achado)
    return desenhar(formacao, quantidade)
