"""
As decisões da Comissão de Disciplina e Ética da SAFF.

POR QUE ESTE ARQUIVO EXISTE
    A API-Football conta que houve expulsão. Ela NÃO conta quantos jogos de
    gancho vieram depois — o endpoint que traria isso não cobre a liga
    saudita. E a diferença importa: em 07/09/26 o Óscar Rodríguez, do Diriyah,
    levou DOIS jogos, não um. Um app que supõe sempre um jogo devolve o
    jogador ao campo uma rodada antes da hora.

    Quem tem esse número é a SAFF, que publica cada decisão em
    about.php?id=3&menu=4&type=13, por data. É uma página velha, servida pelo
    servidor, em windows-1256, com tabela de verdade. Dá para ler.

O QUE MORA AQUI, E O QUE NÃO MORA
    Só a leitura: baixar, achar a tabela, e extrair de cada decisão os campos
    que interessam. Guardar no banco, casar com o jogador da API-Football e
    desenhar tela é assunto de outro lugar.

    O httpx só é importado dentro de quem vai à rede — mesmo padrão do
    arbitragem.py. Assim a parte que ERRA (a leitura do texto) pode ser
    testada com o HTML de verdade, sem rede nenhuma.

A ARMADILHA CENTRAL: "بما في ذلك" QUER DIZER "INCLUINDO"
    As decisões vêm em duas formas, e confundi-las inverte o resultado.

    Com gancho extra:
        إيقاف ... (2) مباراتين بما في ذلك الإيقاف التلقائي
        "suspenso por (2) duas partidas, INCLUINDO a suspensão automática"
        → total 2, sendo 1 automática e 1 a mais.

    Sem gancho extra:
        بالإضافة إلى مباراة الإيقاف التلقائي ... إلزام ... بدفع غرامة
        "ALÉM da partida de suspensão automática, [ele] deve pagar multa"
        → total 1, nenhuma a mais, só multa.

    Ler o (2) da primeira como "dois jogos ALÉM do automático" daria três, e
    o jogador ficaria fora de uma rodada em que podia jogar. Por isso o
    número extraído é sempre o TOTAL, e o campo se chama `jogos_total` — o
    nome não deixa a confusão passar despercebida.
"""
import re
import unicodedata

BASE = "https://www.saff.com.sa/"
# type=13 é a Comissão de Disciplina e Ética; type=14, a de Apelação.
URL_DISCIPLINA = BASE + "about.php?id=3&menu=4&type=13"
URL_APELACAO = BASE + "about.php?id=3&menu=4&type=14"
URL_DO_DIA = URL_DISCIPLINA + "&mdate={dia}"
TEMPO_LIMITE = 25.0

# As competições que este app cobre, exatamente como a SAFF as escreve.
# Mesmo critério da guia de Arbitragem: o que ficar de fora é CONTADO e
# devolvido, nunca descartado em silêncio — a diferença entre "a SAFF não
# publicou nada" e "publicou, mas era tudo do sub-21" muda o que fazer.
COMPETICOES = {
    "دوري روشن السعودي": "Roshn Saudi League",
    "كأس خادم الحرمين الشريفين": "Copa do Rei",
    "كأس السوبر السعودي": "Supercopa da Arábia Saudita",
}

# ── Os pedaços de texto que a decisão sempre usa ────────────────────────────
# Estão aqui em cima, nomeados, em vez de espalhados pelas expressões
# regulares: quando a SAFF mudar a redação, o conserto é uma linha e não uma
# caça ao texto árabe no meio do código.
_SUSPENDEU = "إيقاف"                     # "suspensão de"
_INCLUI_AUTOMATICA = "بما في ذلك"        # "incluindo"
_ALEM_DA_AUTOMATICA = "بالإضافة إلى"     # "além de"
_AUTOMATICA = "الإيقاف التلقائي"         # "a suspensão automática"
_SEM_RECURSO = "غير قابل للاستئناف"      # "não cabe recurso"
_CABE_RECURSO = "قابل للاستئناف"         # "cabe recurso"
_MULTA = "غرامة"                          # "multa"
_CARTAO_VERMELHO = "البطاقة الحمراء"     # "cartão vermelho"

# (2) مباراتين · (4) أربع مباريات · (1) مباراة — o número em algarismos vem
# entre parênteses, e a palavra "partida(s)" vem logo depois, às vezes com o
# número por extenso no meio. Ancorar na palavra é o que separa o número de
# JOGOS do número da MULTA, que também vem entre parênteses.
_RE_JOGOS = re.compile(r"\((\d+)\)\s*(?:[^\s()]+\s+)?(?:مباراتين|مباريات|مباراة)")
# غرامة مالية قدرها (20,000)
_RE_MULTA = re.compile(r"قدرها\s*\(([\d,\.]+)\)")
# للمادة (48-1-2) — ancorado em "مادة" (artigo) e não em "المادة", porque o
# texto escreve "لـلمادة" ("para o artigo"), com o prefixo grudado. Procurar
# "المادة" com o alif não acha nada, e a primeira versão daqui devolvia lista
# vazia em TODAS as decisões — calada, porque lista vazia é uma resposta
# plausível para "quais artigos foram citados".
_RE_ARTIGO = re.compile(r"مادة\s*\(([\d٠-٩\-/]+)\)")


def _limpo(texto: str) -> str:
    """Espaço normalizado e caracteres invisíveis fora.

    Páginas árabes vêm cheias de marcas de direção de texto (RLM, LRM) e de
    espaços não separáveis. Elas não aparecem na tela e quebram comparação de
    string — é o tipo de diferença que faz um teste passar e a produção
    falhar.
    """
    t = unicodedata.normalize("NFKC", texto or "")
    t = t.replace("‏", "").replace("‎", "").replace(" ", " ")
    t = t.replace("‪", "").replace("‫", "").replace("‬", "")
    return " ".join(t.split())


def jogos_de_suspensao(decisao: str) -> int | None:
    """Quantas partidas o jogador fica fora, NO TOTAL. None se não disser.

    TOTAL, incluindo a suspensão automática do vermelho — é assim que a SAFF
    escreve, e mudar a unidade no meio do caminho é o jeito mais fácil de
    errar por um jogo. Ver o cabeçalho do arquivo.
    """
    t = _limpo(decisao)
    if not t:
        return None
    if _SUSPENDEU in t:
        m = _RE_JOGOS.search(t)
        if m:
            return int(m.group(1))
    # "Além da partida de suspensão automática..." — não há gancho extra, e a
    # pena é a partida automática mais a multa. Total: uma.
    if _ALEM_DA_AUTOMATICA in t and _AUTOMATICA in t:
        return 1
    return None


def jogos_extras(decisao: str) -> int | None:
    """Quantas partidas ALÉM da automática do vermelho. None se não disser.

    É este o número que interessa à guia de suspensos, porque ela já conta a
    automática por conta própria. Deriva do total em vez de ser extraído em
    separado: com duas extrações independentes, uma podia mudar e a outra
    não, e ninguém veria.
    """
    total = jogos_de_suspensao(decisao)
    return None if total is None else max(0, total - 1)


def multa_em_riais(decisao: str) -> int | None:
    m = _RE_MULTA.search(_limpo(decisao))
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", "").replace(".", ""))
    except ValueError:
        return None


def artigos(decisao: str) -> list[str]:
    """Os artigos citados, na ordem em que aparecem.

    O PRIMEIRO é o da infração; o último costuma ser o 144, que é o que trata
    de recurso. Devolvo todos, em ordem, e deixo quem exibe decidir — jogar
    fora o 144 aqui seria esconder de onde saiu a informação de que não cabe
    recurso.
    """
    vistos, saida = set(), []
    for m in _RE_ARTIGO.finditer(_limpo(decisao)):
        a = m.group(1)
        if a not in vistos:
            vistos.add(a)
            saida.append(a)
    return saida


def cabe_recurso(decisao: str) -> bool | None:
    """True, False, ou None quando a decisão não diz.

    A ordem dos testes é a regra: "غير قابل للاستئناف" (não cabe) CONTÉM
    "قابل للاستئناف" (cabe). Procurar o segundo primeiro devolveria "cabe
    recurso" em toda decisão que diz o contrário — a mesma armadilha do
    "Yellow-Red Card", que continha "Red Card".
    """
    t = _limpo(decisao)
    if _SEM_RECURSO in t:
        return False
    if _CABE_RECURSO in t:
        return True
    return None


def alvo_da_decisao(texto: str) -> dict:
    """Contra quem é a decisão: jogador, clube ou dirigente.

    A SAFF escreve de duas formas:
        "لاعب نادي الدرعية/ أوسكار رودريغيز"  → cargo + clube / NOME
        "نادي الطائي"                          → o clube, sem barra

    A barra é o que separa. Sem ela, é o clube que está sendo punido; com
    ela, é uma pessoa, e o que vem antes diz o que ela faz — jogador, técnico,
    e às vezes coisas que ninguém espera: em 07/09 quem pegou quatro jogos foi
    o TRADUTOR do Al-Ahli. Por isso "dirigente" é o balde de quem não é
    jogador, e o cargo original vai junto em vez de ser descartado.
    """
    t = _limpo(texto)
    if not t:
        return {"tipo": "", "cargo": "", "clube": "", "nome": ""}
    if "/" not in t:
        return {"tipo": "clube", "cargo": "", "clube": t, "nome": ""}
    antes, _, nome = t.partition("/")
    antes, nome = _limpo(antes), _limpo(nome)
    tipo = "jogador" if antes.startswith("لاعب") else "dirigente"
    # O clube é o que vem depois de "نادي" (clube) dentro do cargo.
    clube = ""
    for marca in ("نادي ", "النادي "):
        if marca in antes:
            clube = _limpo(antes.split(marca, 1)[1])
            break
    return {"tipo": tipo, "cargo": antes, "clube": clube or antes, "nome": nome}


def por_vermelho(infracao: str, decisao: str) -> bool:
    """A decisão trata de um cartão vermelho?

    Serve para separar o que pode virar gancho de jogo do que é multa por
    outra coisa — atraso no início do jogo, sinalizadores na torcida, número
    de cartões da equipe. Só o primeiro grupo interessa à guia de suspensos.
    """
    junto = _limpo(infracao) + " " + _limpo(decisao)
    return _CARTAO_VERMELHO in junto or _AUTOMATICA in junto


def ler_decisoes(html: str) -> dict:
    """Do HTML da página para a lista de decisões.

    Devolve {"decisoes": [...], "ignoradas": [...], "erros": [...]}.

    "ignoradas" traz as decisões de competições que não cobrimos, com o nome
    da competição. Elas voltam de propósito, pelo mesmo motivo do
    arbitragem.py: num dia vazio, saber que havia seis decisões e todas eram
    do sub-21 é uma informação completamente diferente de "não saiu nada".
    """
    saida = {"decisoes": [], "ignoradas": [], "erros": []}
    try:
        from bs4 import BeautifulSoup
        sopa = BeautifulSoup(html or "", "lxml")
    except Exception as e:
        saida["erros"].append(f"não consegui abrir o HTML: {type(e).__name__}: {e}")
        return saida

    # A primeira tabela é o resumo, com uma linha por decisão. As tabelas
    # seguintes repetem cada decisão em formato de ficha — mesma informação,
    # de outro jeito. Leio só a primeira para não gravar tudo em dobro.
    tabela = sopa.find("table")
    if not tabela:
        saida["erros"].append("não achei a tabela de decisões nesta página")
        return saida

    CABECALHO = "رقم وتاريخ القرار"
    for linha in tabela.find_all("tr"):
        celulas = [_limpo(c.get_text(" ", strip=True))
                   for c in linha.find_all(["td", "th"])]
        if len(celulas) < 6 or CABECALHO in celulas[0]:
            continue
        numero_e_data, competicao, jogo, contra, infracao, decisao = celulas[:6]

        # "16/ ل ض / 2026 2026-09-10" — o número da decisão e a data saem
        # colados na mesma célula. A data ISO é o que dá para achar sem
        # ambiguidade; o resto, limpo, é o número.
        m = re.search(r"(\d{4}-\d{2}-\d{2})", numero_e_data)
        data = m.group(1) if m else ""
        numero = _limpo(numero_e_data.replace(data, ""))

        # O jogo vem como "الأنوار - الطائي (2026-09-08)".
        m = re.search(r"(\d{4}-\d{2}-\d{2})", jogo)
        jogo_em = m.group(1) if m else ""
        confronto = _limpo(re.sub(r"\(?\d{4}-\d{2}-\d{2}\)?", "", jogo))

        registro = {
            "numero": numero, "data": data,
            "competicao": competicao,
            "competicao_pt": COMPETICOES.get(competicao, ""),
            "confronto": confronto, "jogo_em": jogo_em,
            "contra": contra, **alvo_da_decisao(contra),
            "infracao": infracao, "decisao": decisao,
            "jogos_total": jogos_de_suspensao(decisao),
            "jogos_extras": jogos_extras(decisao),
            "multa": multa_em_riais(decisao),
            "artigos": artigos(decisao),
            "cabe_recurso": cabe_recurso(decisao),
            "por_vermelho": por_vermelho(infracao, decisao),
        }
        if competicao in COMPETICOES:
            saida["decisoes"].append(registro)
        else:
            saida["ignoradas"].append({"competicao": competicao,
                                       "numero": numero, "data": data})
    return saida


def _baixar(url: str, cliente) -> str:
    """Mesmo download do arbitragem.py, pelo mesmo motivo.

    A página se declara windows-1256. Quando o servidor não manda charset, o
    httpx chuta latin-1 e o árabe vira lixo — e lixo que não levanta erro,
    porque latin-1 decodifica qualquer byte.
    """
    r = cliente.get(url, timeout=TEMPO_LIMITE, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; IARABAO/1.0)"})
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() in ("ascii", "iso-8859-1"):
        r.encoding = "windows-1256"
    return r.text


def buscar_do_dia(dia: str) -> dict:
    """As decisões publicadas nesta data (AAAA-MM-DD)."""
    import httpx
    with httpx.Client() as cliente:
        try:
            html = _baixar(URL_DO_DIA.format(dia=dia), cliente)
        except Exception as e:
            return {"decisoes": [], "ignoradas": [],
                    "erros": [f"{dia}: {type(e).__name__}: {e}"]}
    r = ler_decisoes(html)
    r["dia"] = dia
    return r


def datas_publicadas(html: str) -> list[str]:
    """As datas que a página inicial lista como tendo decisão.

    A SAFF não publica todo dia, e não publica no dia do jogo: a decisão do
    jogo de 08/09 saiu em 10/09. Varrer data por data seria chutar; a própria
    página diz quais existem, nos links "&mdate=".
    """
    achadas = re.findall(r"mdate=(\d{4}-\d{2}-\d{2})", html or "")
    vistas, saida = set(), []
    for d in achadas:
        if d not in vistas:
            vistas.add(d)
            saida.append(d)
    return saida


def buscar_recentes(quantas: int = 8) -> dict:
    """As últimas datas com publicação, da mais nova para a mais velha."""
    import httpx
    saida = {"decisoes": [], "ignoradas": [], "erros": [], "dias": []}
    with httpx.Client() as cliente:
        try:
            indice = _baixar(URL_DISCIPLINA, cliente)
        except Exception as e:
            saida["erros"].append(f"índice: {type(e).__name__}: {e}")
            return saida
        dias = datas_publicadas(indice)[:max(1, quantas)]
        saida["dias"] = dias
        for dia in dias:
            try:
                html = _baixar(URL_DO_DIA.format(dia=dia), cliente)
            except Exception as e:
                saida["erros"].append(f"{dia}: {type(e).__name__}: {e}")
                continue
            r = ler_decisoes(html)
            for d in r["decisoes"]:
                d["publicado_em"] = dia
            saida["decisoes"] += r["decisoes"]
            saida["ignoradas"] += r["ignoradas"]
            saida["erros"] += r["erros"]
    return saida
