"""
Lê o matchsheet oficial da SPL (o PDF do mediahub) e devolve a escalação.

POR QUE ISTO É CÓDIGO, E NÃO IA
    O PDF sai de um sistema da própria liga — tem camada de texto de
    verdade, não é foto escaneada. Separar titular de reserva, achar o
    capitão e o goleiro é geometria (que lado da página, que ordem de cima
    pra baixo) e duas letras coladas no fim do nome ("GK", "C", "CGK") — não
    exige entender língua nenhuma. Custa zero token de IA.

A FRONTEIRA TITULAR/RESERVA
    O PDF não escreve "titular" nem "reserva" em lugar nenhum que sobreviva
    à extração — o rótulo lateral do template vem girado 90° e a extração
    devolve as letras dele espalhadas, uma por linha, misturadas com as dos
    jogadores (`P`, `U`, `E`, `N`, `IL`...). Filtro essas linhas fora: uma
    linha de jogador SEMPRE tem um número de camisa, a do rótulo nunca tem.

    A fronteira real também não depende desse rótulo: cada time tem UM
    goleiro titular e UM reserva, e o reserva é sempre a primeira entrada do
    segundo bloco. O SEGUNDO "GK" que aparece numa coluna é onde o banco
    começa — sem isso, teria que confiar em contar sempre onze titulares, o
    que quebraria no dia de um cartão vermelho pré-jogo ou uma lista com
    menos de onze por algum motivo.

A GEOMETRIA DAS DUAS COLUNAS
    Casa fica na metade esquerda da página, fora na direita — é assim que a
    SPL desenha o PDF, e é assim que se separa um time do outro: pela
    posição x da palavra, não por tentar casar padrão de texto numa mistura
    dos dois times na mesma linha.
"""
import re
import statistics
from collections import defaultdict


# "C" (capitão), "GK" (goleiro), ou as duas coladas sem espaço quando o
# capitão também é o goleiro — caso real: Edouard Mendy no Al Ahli.
_MARCA = re.compile(r"^(CGK|GKC|GK|C)$")


def _sem_ruido_lateral(palavras):
    """Tira o rótulo "STARTING"/"SUBSTITUTE" girado 90° — a extração devolve
    ele como letras soltas (P, U, E, N, IL...) numa faixa estreita de x0,
    sempre à esquerda da coluna de número de camisa. Sem eixo fixo (o rótulo
    da coluna casa fica perto da borda da página, o da coluna fora fica perto
    do meio) então acho o limite pela própria coluna de número: nada de
    verdade fica mais de ~15px à esquerda dela.

    Uso a MEDIANA dos x0 dos tokens com dígito, não o mínimo — abaixo da
    lista de reservas tem um diagrama de formação tática com a mesma camisa
    numerada de novo, solta no meio da página, com x0 bem menor que o da
    coluna de verdade. Um único número desses no mínimo puxaria o corte
    inteiro para a esquerda e deixaria passar o rótulo; a mediana ignora
    esses poucos pontos fora da curva."""
    x0_numeros = [w["x0"] for w in palavras if any(c.isdigit() for c in w["text"])]
    if not x0_numeros:
        return palavras
    limite = statistics.median(x0_numeros) - 15
    return [w for w in palavras if w["x0"] >= limite]


def _linhas_por_coluna(words, meio_x, y_min, y_max, esquerda):
    """Agrupa palavras da metade esquerda/direita da página em linhas, na
    ordem de leitura: de cima pra baixo, e da esquerda pra direita dentro de
    cada linha."""
    alvo = [w for w in words
            if y_min < w["top"] < y_max and (w["x0"] < meio_x) == esquerda]
    alvo = _sem_ruido_lateral(alvo)
    alvo = sorted(alvo, key=lambda w: w["top"])
    # Nome e número do MESMO jogador podem sair com "top" até ~1px de
    # diferença (fontes diferentes têm linha de base diferente) — dá pra
    # cruzar uma fronteira de arredondamento e virar duas linhas incompletas.
    # Agrupo por proximidade em vez de arredondar: só começa linha nova
    # quando o salto for grande de verdade (linhas do template ficam a mais
    # de 10px uma da outra; dentro da mesma linha o salto é menor que 3px).
    grupos = []
    for w in alvo:
        if grupos and w["top"] - grupos[-1][-1]["top"] <= 3:
            grupos[-1].append(w)
        else:
            grupos.append([w])
    linhas = []
    for grupo in grupos:
        ws = sorted(grupo, key=lambda w: w["x0"])
        linhas.append([w["text"] for w in ws])
    return linhas


def _jogadores_da_coluna(linhas):
    """De uma lista de linhas (cada uma uma lista de tokens), separa jogador
    de lixo do rótulo lateral girado, na ordem em que aparecem no PDF."""
    jogadores = []
    for tokens in list(linhas):
        # A linha do rótulo vira 1 a 3 letras soltas, sem dígito nenhum —
        # nenhuma linha de jogador de verdade passa sem um número de camisa.
        if not any(t.isdigit() for t in tokens):
            continue
        tokens = list(tokens)
        marca = ""
        if tokens and _MARCA.match(tokens[-1]):
            marca = tokens.pop()
        numero = next((t for t in tokens if t.isdigit()), None)
        if numero is None:
            continue
        nome = " ".join(t for t in tokens if t != numero and not t.isdigit()).strip()
        if not nome:
            continue
        jogadores.append({
            "numero": numero,
            "nome": nome,
            "goleiro": "GK" in marca,
            "capitao": "C" in marca,
        })
    return jogadores


def _titulares_e_reservas(jogadores: list[dict]) -> tuple[list[dict], list[dict]]:
    """Corta pela SEGUNDA marca de goleiro — ver docstring do módulo."""
    indices_gk = [i for i, j in enumerate(jogadores) if j["goleiro"]]
    if len(indices_gk) >= 2:
        corte = indices_gk[1]
    else:
        # Sem os dois goleiros pra guiar o corte (PDF incompleto, ou time
        # com um só GK relacionado): onze é a regra do jogo, não um chute.
        corte = min(11, len(jogadores))
    return jogadores[:corte], jogadores[corte:]


def _nome_do_tecnico(words, meio_x, esquerda) -> str:
    """Acha 'Head Coach NOME' na página das comissões técnicas (pág. 2) e
    devolve só o nome, do lado certo da página."""
    por_y = defaultdict(list)
    for w in words:
        por_y[round(w["top"])].append(w)
    for y in sorted(por_y):
        ws = sorted(por_y[y], key=lambda w: w["x0"])
        textos = [w["text"] for w in ws]
        if "Head" in textos and "Coach" in textos:
            # Pega as palavras desse LADO da página que vêm depois de
            # "Coach" — o resto da linha (Assistant Coach etc, do OUTRO
            # time) não entra porque está do outro lado do meio_x.
            depois_de_coach = False
            nome = []
            for w in ws:
                if w["text"] == "Coach" and (w["x0"] < meio_x) == esquerda:
                    depois_de_coach = True
                    continue
                if depois_de_coach and (w["x0"] < meio_x) == esquerda:
                    nome.append(w["text"])
                elif depois_de_coach and (w["x0"] < meio_x) != esquerda:
                    break
            if nome:
                return " ".join(nome)
    return ""


def extrair(caminho: str) -> dict:
    """A escalação das duas equipes, direto do PDF oficial da SPL.

    Devolve nomes e números EXATAMENTE como o PDF escreve — sem acento em
    "THEO HERNANDEZ", por exemplo, porque é assim que a SPL imprime. Quem
    quiser o nome com grafia completa, nacionalidade ou foto cruza pelo
    número da camisa contra o elenco que o app já tem (`cruzar_com_elenco`,
    abaixo)."""
    import pdfplumber

    with pdfplumber.open(caminho) as pdf:
        pagina0 = pdf.pages[0]
        texto0 = pagina0.extract_text() or ""
        words0 = pagina0.extract_words(use_text_flow=False, keep_blank_chars=False)
        meio_x = pagina0.width / 2

        m = re.search(
            r"Season\s+(\S+)\s+Round\s+(\S+)\s+(.+?)\s+"
            r"(\d{1,2}\s+\w+\s+\d{4})\s+(\d{1,2}:\d{2})",
            texto0)
        cabecalho = {
            "temporada": m.group(1) if m else "",
            "rodada": m.group(2) if m else "",
            "estadio": m.group(3) if m else "",
            "data": m.group(4) if m else "",
            "hora": m.group(5) if m else "",
        }

        # Nome dos times: mesma geometria das colunas, na linha logo abaixo
        # de "HOME TEAM"/"AWAY TEAM" — não dá pra usar regex no texto plano
        # porque clube tem número de palavras variável dos dois lados
        # ("NEOM" vs "AL QADSIAH"), e não existe separador confiável no meio.
        ys_time = sorted({round(w["top"]) for w in words0 if w["text"] == "TEAM"})
        y_nomes = ys_time[0] + 11 if ys_time else 0
        linha_nomes = [w for w in words0 if abs(w["top"] - y_nomes) <= 3]
        nome_casa = " ".join(w["text"] for w in
                             sorted([w for w in linha_nomes if w["x0"] < meio_x],
                                    key=lambda w: w["x0"]))
        nome_fora = " ".join(w["text"] for w in
                             sorted([w for w in linha_nomes if w["x0"] >= meio_x],
                                    key=lambda w: w["x0"]))

        # A tabela de titulares/reservas fica entre o cabeçalho "NUMBER
        # PLAYER" e a seção "COACH" (que tem o diagrama de formação, e não
        # mais jogador nenhum).
        ys_marco = {w["text"]: w["top"] for w in words0
                    if w["text"] in ("NUMBER", "COACH")}
        y_topo = ys_marco.get("NUMBER", 0) + 5
        y_fundo = ys_marco.get("COACH", pagina0.height)

        linhas_casa = _linhas_por_coluna(words0, meio_x, y_topo, y_fundo, True)
        linhas_fora = _linhas_por_coluna(words0, meio_x, y_topo, y_fundo, False)
        titulares_casa, reservas_casa = _titulares_e_reservas(_jogadores_da_coluna(linhas_casa))
        titulares_fora, reservas_fora = _titulares_e_reservas(_jogadores_da_coluna(linhas_fora))

        tecnico_casa = tecnico_fora = ""
        if len(pdf.pages) > 1:
            pagina1 = pdf.pages[1]
            words1 = pagina1.extract_words(use_text_flow=False, keep_blank_chars=False)
            meio_x1 = pagina1.width / 2
            tecnico_casa = _nome_do_tecnico(words1, meio_x1, True)
            tecnico_fora = _nome_do_tecnico(words1, meio_x1, False)

    return {
        **cabecalho,
        "casa": {"time": nome_casa, "titulares": titulares_casa,
                 "reservas": reservas_casa, "tecnico": tecnico_casa},
        "fora": {"time": nome_fora, "titulares": titulares_fora,
                 "reservas": reservas_fora, "tecnico": tecnico_fora},
    }


def cruzar_com_elenco(jogadores: list[dict], elenco: list[dict]) -> list[dict]:
    """Cruza a escalação extraída do PDF com o elenco que o app já tem
    (`database.listar_jogadores(clube=...)`), pelo número da camisa.

    Casa por camisa, não por nome: o PDF escreve sem acento ("THEO
    HERNANDEZ", "IBAÑEZ" sem til em alguns casos) e o app já guarda a grafia
    correta vinda da própria SPL. Camisa é o único dado que não muda de fonte
    pra fonte.

    Devolve nome_curto (o mesmo "BONO" que a SPL usa no placar — não "Yassine
    Bono"), nacionalidade e foto quando o cruzamento acha o jogador. Sem
    achado (elenco desatualizado, contratação de última hora), mantém só o
    que o PDF trouxe — melhor um card incompleto do que inventar dado."""
    por_camisa = {}
    for j in elenco:
        camisa = str(j.get("camisa") or "").strip()
        if camisa:
            por_camisa[camisa] = j
    cruzados = []
    for jog in jogadores:
        cruzado = dict(jog)
        achado = por_camisa.get(str(jog["numero"]).strip())
        cruzado["nome_curto"] = (achado.get("nome_curto") or "") if achado else ""
        cruzado["nacionalidade"] = (achado.get("nacionalidade") or "") if achado else ""
        cruzado["foto"] = (achado.get("foto") or "") if achado else ""
        if achado and achado.get("nome"):
            cruzado["nome"] = achado["nome"]
        cruzados.append(cruzado)
    return cruzados


def texto_titulares(nome_time: str, titulares: list[dict]) -> str:
    """A lista pronta pra colar na arte do post: bandeira, número, sobrenome
    — um jogador por linha, na ordem em que o PDF lista o time titular.

    Número de UM dígito sai com zero à esquerda ("02", não "2") — é assim
    que a arte do post mostra, e é assim que a SPL numera nas costas da
    camisa. Dois dígitos ou mais fica como está; não existe camisa "0X" de
    verdade nesse caso, então não há o que preencher.

    Sobrenome vem do nome_curto do banco quando `cruzar_com_elenco` achou o
    jogador; sem cruzamento, cai pro nome do PDF (que às vezes já vem só o
    sobrenome). Sem nacionalidade cruzada, a linha sai sem bandeira — nunca
    com uma bandeira chutada."""
    import arbitragem
    linhas = [nome_time.upper()]
    for j in titulares:
        emoji = arbitragem.bandeira(j.get("nacionalidade", ""))
        nome = j.get("nome_curto") or j["nome"]
        numero = str(j["numero"]).strip()
        if numero.isdigit() and len(numero) == 1:
            numero = numero.zfill(2)
        prefixo = f"{emoji} " if emoji else ""
        linhas.append(f"{prefixo}{numero} {nome}")
    return "\n".join(linhas)
