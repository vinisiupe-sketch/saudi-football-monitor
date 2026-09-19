"""
O PNG 1080x1350 dos desfalques: quem está fora, por quê, e até quando.

O PEDIDO (18/09/26)
    "Podemos tentar montar nessa base verde na parte do campinho algo como no
     anexo? Pegando o que temos de informações de lesionados e suspensos?"

    O anexo era um cartão escuro com foto redonda, nome, e embaixo o motivo e
    a volta: "Lesão muscular / No fim de setembro 2026". Aqui isso vira arte de
    publicar, na identidade que ele já usa.

POR QUE NÃO REAPROVEITEI O TEMPLATE DO CAMPINHO
    A base verde dele tem o gramado em perspectiva, com as linhas, a área e o
    círculo central desenhados. Uma lista de nomes por cima disso briga com o
    desenho: as linhas do campo cortam as placas na diagonal e não há como
    alinhar oito linhas de texto num trapézio.

    Então o fundo é o MESMO VERDE (#01f468, o do campinho e o do disco), sem o
    gramado. A identidade vem dos elementos, que são os mesmos: disco de foto
    com anel grafite, placa #303030 com texto branco em caixa alta, Work Sans.
    Quem vir as duas artes lado a lado vê a mesma mão.

O QUE ESTE MÓDULO NÃO FAZ
    Não decide quem está fora, não busca foto e não fala com a rede. Nome,
    motivo, retorno e os bytes da foto chegam prontos de quem chamou — mesma
    regra do escalacao_arte, e é o que torna possível montar a arte inteira num
    teste sem tocar no Transfermarkt.

O QUE ELE RECUSA A FAZER
    Arte sem ninguém na lista. "Nenhum desfalque" e "não consegui consultar"
    são coisas diferentes, e uma imagem publicada dizendo que o elenco está
    completo quando na verdade a fonte caiu é pior que imagem nenhuma. Quem
    chama recebe um erro e decide o que dizer.
"""
from __future__ import annotations

import io
import os

# A MESMA RÉGUA DA OUTRA ARTE, e de propósito: os dois PNGs vão para o mesmo
# feed, um atrás do outro. Importo em vez de copiar — duas cópias das mesmas
# medidas é como a tela e o arquivo começam a divergir.
from escalacao_arte import (ALTURA, BRANCO, CQ, FONTES, GRAFITE,  # noqa: F401
                            LARGURA, _circulo, _fonte)

VERDE = (1, 244, 104)          # #01f468 — o mesmo do campo e do disco

# ── as medidas, em px de uma imagem 1080x1350 ───────────────────────────────
MARGEM = 6.5 * CQ              # 70, a respiração lateral
TITULO_CORPO = 4.2 * CQ        # 45
TITULO_BASE = 11.0 * CQ        # 119, a linha de base do título
CLUBE_CORPO = 2.6 * CQ         # 28
CLUBE_BASE = 14.6 * CQ         # 158

# A ALTURA DA LINHA NÃO É FIXA, e isso não é capricho.
#
# Com número fixo, seis desfalques deixavam a metade de baixo da arte vazia e
# dez ficavam espremidos. Como a quantidade muda a cada rodada, a linha se
# estica até o teto e encolhe até o piso. O piso é o disco mais o respiro
# mínimo; abaixo dele as fotos encostam e a leitura vira lista de cadastro.
LINHA_MIN = 9.6 * CQ           # 104 — o aperto máximo, com dez na lista
LINHA_MAX = 15.0 * CQ          # 162 — o espaço máximo, com três ou quatro
LINHA_TOPO = 18.0 * CQ         # 194, onde começa o primeiro
FOTO_LADO = 8.0 * CQ           # 86, o mesmo disco do campinho
NOME_CORPO = 3.0 * CQ          # 32
MOTIVO_CORPO = 2.3 * CQ        # 25
TEXTO_X = MARGEM + FOTO_LADO + 2.2 * CQ

SELO_CORPO = 1.8 * CQ          # 19, o texto do selo SUSPENSO
SELO_ALT = 3.0 * CQ            # 32, a altura do selo
SELO_PAD = 1.0 * CQ            # 11, o respiro interno

RODAPE_CORPO = 2.0 * CQ        # 21
RODAPE_BASE = ALTURA - 5.0 * CQ

# Quantos cabem sem espremer. Acima disso a arte vira parede de nome pequeno, e
# o Vini publica duas em vez de uma ilegível.
CABEM = 10


def _encurtar(d, texto: str, fonte, limite: float) -> str:
    """O texto que cabe na largura, com reticências quando não coube.

    CORTAR É MELHOR QUE VAZAR, e as duas são piores que caber. O nome de lesão
    do Transfermarkt vem por extenso ("Lesão do ligamento cruzado anterior") e
    numa linha de 1080px com foto ao lado ele encosta na borda. Reticências
    avisam que falta pedaço; texto cortado no meio da palavra parece defeito.
    """
    texto = texto or ""
    if d.textlength(texto, font=fonte) <= limite:
        return texto
    while texto and d.textlength(texto + "…", font=fonte) > limite:
        texto = texto[:-1]
    return (texto.rstrip() + "…") if texto else ""


def montar(dados: dict) -> bytes:
    """dados: {"clube": str, "desfalques": [{nome, motivo, retorno, tipo,
    foto: bytes|None}]}. Devolve os bytes do PNG.

    `tipo` é "lesao" ou "suspensao" — ele muda a cor do ponto ao lado do nome,
    que é a única coisa que distingue os dois de relance.
    """
    from PIL import Image, ImageDraw

    lista = [x for x in (dados.get("desfalques") or []) if (x.get("nome") or "")]
    if not lista:
        # Ver o cabeçalho: arte vazia mente, e mente com cara de informação.
        raise ValueError("nenhum desfalque para desenhar")
    lista = lista[:CABEM]

    base = Image.new("RGBA", (LARGURA, ALTURA), VERDE + (255,))
    d = ImageDraw.Draw(base)

    f_titulo = _fonte("WorkSans-Bold-latin.ttf", TITULO_CORPO)
    f_clube = _fonte("WorkSans-SemiBold-latin.ttf", CLUBE_CORPO)
    f_nome = _fonte("WorkSans-SemiBold-latin.ttf", NOME_CORPO)
    f_motivo = _fonte("WorkSans-Regular-latin.ttf", MOTIVO_CORPO)
    f_selo = _fonte("WorkSans-SemiBold-latin.ttf", SELO_CORPO)
    f_rodape = _fonte("WorkSans-Regular-latin.ttf", RODAPE_CORPO)

    d.text((MARGEM, TITULO_BASE), "DESFALQUES", font=f_titulo,
           fill=GRAFITE, anchor="ls")
    clube = (dados.get("clube") or "").upper()
    if clube:
        d.text((MARGEM, CLUBE_BASE), clube, font=f_clube, fill=GRAFITE,
               anchor="ls")

    largura_texto = LARGURA - TEXTO_X - MARGEM

    # O espaço entre o subtítulo e o rodapé, dividido por quem está na lista.
    espaco = (RODAPE_BASE - 3.0 * CQ) - LINHA_TOPO
    linha_alt = max(LINHA_MIN, min(LINHA_MAX, espaco / max(1, len(lista))))

    for i, j in enumerate(lista):
        topo = LINHA_TOPO + i * linha_alt
        meio = topo + FOTO_LADO / 2

        # A FOTO usa o mesmo disco da outra arte, com o mesmo zoom no rosto:
        # num retrato de meio corpo a 86px, sem zoom, o rosto some.
        base.alpha_composite(
            _circulo(j.get("foto"), FOTO_LADO,
                     float(dados.get("zoom") or 1.0), dados.get("ancora")),
            (int(MARGEM), int(topo)))

        # A PLACA DE SUSPENSO, no molde das placas do campinho: grafite com
        # texto branco em caixa alta. Ela vem ANTES do nome no cálculo porque
        # come largura — um nome comprido tem de ser encurtado contando com
        # ela, senão os dois se encavalam.
        #
        # Primeira versão era um ponto ao lado do nome. Ficou colado nele, e um
        # ponto não diz o que significa: quem abre o post não tem legenda.
        suspenso = (j.get("tipo") or "") == "suspensao"
        larg_placa = 0.0
        if suspenso:
            larg_placa = d.textlength("SUSPENSO", font=f_selo) + 2 * SELO_PAD \
                + 1.6 * CQ

        nome = _encurtar(d, (j.get("nome") or "").upper(), f_nome,
                         largura_texto - larg_placa)
        d.text((TEXTO_X, meio - 0.4 * CQ), nome, font=f_nome, fill=GRAFITE,
               anchor="ls")

        if suspenso:
            x0 = TEXTO_X + d.textlength(nome, font=f_nome) + 1.6 * CQ
            larg = d.textlength("SUSPENSO", font=f_selo) + 2 * SELO_PAD
            topo_selo = meio - 0.4 * CQ - SELO_ALT + 0.4 * CQ
            d.rectangle([x0, topo_selo, x0 + larg, topo_selo + SELO_ALT],
                        fill=GRAFITE)
            d.text((x0 + larg / 2, topo_selo + SELO_ALT / 2), "SUSPENSO",
                   font=f_selo, fill=BRANCO, anchor="mm")

        # MOTIVO E RETORNO NA MESMA LINHA, separados por barra — é o formato do
        # exemplo que ele mandou, e é o que cabe.
        motivo = (j.get("motivo") or "").strip()
        retorno = (j.get("retorno") or "").strip()
        linha = " / ".join([x for x in (motivo, retorno) if x])
        if linha:
            d.text((TEXTO_X, meio + 3.4 * CQ),
                   _encurtar(d, linha, f_motivo, largura_texto),
                   font=f_motivo, fill=GRAFITE, anchor="ls")

    quantos = len(dados.get("desfalques") or [])
    sobra = quantos - len(lista)
    rodape = f"{quantos} fora" + (f" · mostrando {len(lista)}" if sobra else "")
    fontes = dados.get("fontes") or ""
    if fontes:
        rodape += " · " + fontes
    d.text((MARGEM, RODAPE_BASE), rodape, font=f_rodape, fill=GRAFITE,
           anchor="ls")

    saida = io.BytesIO()
    base.convert("RGB").save(saida, "PNG")
    return saida.getvalue()
