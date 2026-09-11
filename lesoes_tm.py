"""
A lista de lesionados da Saudi Pro League no Transfermarkt.

POR QUE ESTA FONTE
    O monitor de lesões do app lê NOTÍCIA: só sabe de quem a imprensa
    noticiou, e escreve o nome como a IA transliterou do texto. Isso produz
    dois problemas de uma vez — falta gente, e o nome de quem está lá sai
    diferente do resto do app.

    A alternativa óbvia seria o endpoint `injuries` da API-Football. Não
    serve: conferi com a chave do Vini e a liga saudita tem
    `coverage.injuries = false` — a API responde com SUCESSO e lista VAZIA.
    Foi por isso que a sub-aba "Conferir na API" não trazia nada.

    O Transfermarkt tem a página, com 87 lesionados quando eu conferi
    (11/09/26), e traz o que interessa: jogador, clube, tipo de lesão e data
    prevista de retorno.

O MOTIVO REAL DE ELA SER BOA: O ID
    A tabela `jogador` deste app já guarda `tm_id` — o identificador do
    Transfermarkt — porque os elencos vêm de lá. Então o casamento entre a
    lesão e o jogador não passa por nome nenhum: é o mesmo número dos dois
    lados.

    Isso é diferente de tudo que já tentei aqui. O casamento por nome árabe
    x latino da SAFF eu tive que evitar; o do monitor de lesões depende da
    transliteração da IA. Este é exato, e é exato de graça.
"""
import re

# O endereço e os cabeçalhos do TM vêm do janela_scraper, mas NÃO são
# importados aqui em cima: aquele módulo importa httpx no topo, e importá-lo
# faria a leitura do HTML depender de biblioteca de rede. É o mesmo princípio
# do arbitragem.py — o que ERRA é a leitura do texto, e ela tem que ser
# testável em qualquer lugar, com o recorte real da página e sem internet.

# `/plus/1` é a VISÃO DETALHADA da mesma página, e foi o Vini quem apontou.
#
# A visão simples traz Jogador, Clube, Lesão, "until" e Valor. A detalhada
# acrescenta Idade, Nacionalidade e — o que importa aqui — o **since**: a data
# em que a lesão começou.
#
# Sem ela eu só sabia quando o jogador deve voltar, e a entrada do
# Transfermarkt no histórico do card tinha que ser carimbada com a data de
# HOJE, dizendo "é o estado atual da fonte". Com o `since`, ela entra na linha
# do tempo no lugar certo, junto das notícias daquele dia.
CAMINHO = "/saudi-pro-league/verletztespieler/wettbewerb/SA1/plus/1"
TEMPO_LIMITE = 25.0

_RE_ID_JOGADOR = re.compile(r"/profil/spieler/(\d+)")
_RE_ID_CLUBE = re.compile(r"/startseite/verein/(\d+)")
_RE_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _limpo(texto: str) -> str:
    return " ".join((texto or "").split())


def _data_iso(texto: str) -> str:
    """"31/03/2027" vira "2027-03-31". Sem data reconhecível, "".

    A página está em inglês e mesmo assim usa dia/mês/ano. Não confio nisso
    para sempre: se um dia vier mês/dia/ano, esta função é o único lugar a
    mexer, e o teste que a cobre acusa na hora — hoje ela recusa "13" como
    mês, então uma inversão apareceria como data faltando, e não como data
    errada.
    """
    m = _RE_DATA.search(texto or "")
    if not m:
        return ""
    dia, mes, ano = m.group(1), m.group(2), m.group(3)
    if not ("01" <= mes <= "12"):
        return ""
    return f"{ano}-{mes}-{dia}"


def ler_lesionados(html: str) -> dict:
    """Do HTML da página do TM para a lista de lesionados.

    Devolve {"lesoes": [...], "erros": [...]}.
    """
    saida = {"lesoes": [], "erros": []}
    try:
        from bs4 import BeautifulSoup
        sopa = BeautifulSoup(html or "", "lxml")
    except Exception as e:
        saida["erros"].append(f"não consegui abrir o HTML: {type(e).__name__}: {e}")
        return saida

    tabela = sopa.select_one("table.items")
    if not tabela:
        # Sem a tabela, o mais provável é bloqueio do TM (ele responde 403 sem
        # User-Agent e Referer) ou mudança de layout. Digo isso em vez de
        # devolver lista vazia, que passaria por "ninguém machucado".
        saida["erros"].append(
            "não achei a tabela de lesionados — ou o Transfermarkt bloqueou "
            "o acesso, ou a página mudou de forma")
        return saida

    # AS COLUNAS SÃO ACHADAS PELO CABEÇALHO, e não pela posição.
    #
    # O TM serve duas versões da mesma página: a simples tem 5 colunas e a
    # detalhada (/plus/1) tem 8, com Idade e Nacionalidade no meio. Contar a
    # partir do fim funcionava numa e lia a nacionalidade como lesão na
    # outra — e sem erro nenhum, porque texto é texto.
    #
    # Pelo nome da coluna, a leitura sobrevive às duas versões e a mais uma
    # coluna que o TM resolva acrescentar amanhã.
    def _indice_das_colunas() -> dict:
        cabecalho = tabela.find("thead")
        nomes = [_limpo(th.get_text(" ")).lower()
                 for th in (cabecalho.find_all("th") if cabecalho else [])]
        mapa = {}
        for i, n in enumerate(nomes):
            if "injur" in n:
                mapa.setdefault("lesao", i)
            elif n == "since" or "since" in n:
                mapa.setdefault("desde", i)
            elif n == "until" or "until" in n:
                mapa.setdefault("ate", i)
            elif "market value" in n:
                mapa.setdefault("valor", i)
        return mapa

    col = _indice_das_colunas()

    def _celula(celulas, chave, padrao_do_fim):
        i = col.get(chave)
        if i is not None and i < len(celulas):
            return _limpo(celulas[i].get_text(" "))
        # Sem cabeçalho legível, caio para a contagem a partir do fim — que é
        # o que eu fazia antes. Pior, mas melhor que devolver vazio.
        return (_limpo(celulas[padrao_do_fim].get_text(" "))
                if abs(padrao_do_fim) <= len(celulas) else "")

    corpo = tabela.find("tbody") or tabela
    for linha in corpo.find_all("tr", recursive=False):
        celulas = linha.find_all("td", recursive=False)
        if len(celulas) < 4:
            continue
        link = linha.select_one("a[href*='/profil/spieler/']")
        if not link:
            continue
        m = _RE_ID_JOGADOR.search(link.get("href", "") or "")
        tm_id = m.group(1) if m else ""

        clube_a = linha.select_one("a[href*='/startseite/verein/']")
        clube = ""
        clube_id = ""
        if clube_a:
            clube = _limpo(clube_a.get("title") or clube_a.get_text(" "))
            mc = _RE_ID_CLUBE.search(clube_a.get("href", "") or "")
            clube_id = mc.group(1) if mc else ""
        escudo = ""
        img = linha.select_one("img[src*='/wappen/']")
        if img:
            escudo = img.get("src") or ""

        # A célula do jogador é uma tabela aninhada: nome na primeira linha,
        # posição na segunda. Pego a última linha de texto que não seja o
        # nome — é assim que o TM monta desde sempre.
        pedacos = [p for p in _limpo(celulas[0].get_text("\n")).split("\n") if p]
        texto_cel = celulas[0].get_text("\n")
        linhas_cel = [_limpo(x) for x in texto_cel.split("\n") if _limpo(x)]
        nome = _limpo(link.get_text(" "))
        posicao = ""
        for x in reversed(linhas_cel):
            if x and x != nome:
                posicao = x
                break

        saida["lesoes"].append({
            "tm_id": tm_id,
            "nome": nome,
            "posicao": posicao,
            "clube": clube,
            "clube_tm_id": clube_id,
            "escudo": escudo,
            "lesao": _celula(celulas, "lesao", -3),
            "desde": _data_iso(_celula(celulas, "desde", 0)),
            "desde_texto": _celula(celulas, "desde", 0),
            "ate": _data_iso(_celula(celulas, "ate", -2)),
            "ate_texto": _celula(celulas, "ate", -2),
            "valor": _celula(celulas, "valor", -1),
        })
    if not saida["lesoes"]:
        saida["erros"].append("a tabela existe mas não devolveu nenhuma linha "
                              "que eu saiba ler — o layout deve ter mudado")
    return saida


def buscar() -> dict:
    """Baixa e lê a página. httpx só aqui, como no resto do projeto."""
    import httpx
    from janela_scraper import TM_BASE, TM_HEADERS
    url = TM_BASE.rstrip("/") + CAMINHO
    try:
        with httpx.Client(headers=TM_HEADERS, timeout=TEMPO_LIMITE,
                          follow_redirects=True) as cli:
            r = cli.get(url)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        return {"lesoes": [], "erros": [f"{type(e).__name__}: {e}"]}
    saida = ler_lesionados(html)
    saida["url"] = url
    return saida


def casar_com_elenco(lesoes: list[dict], jogadores: list[dict]) -> int:
    """Liga cada lesão ao jogador do elenco PELO ID do Transfermarkt.

    Sem nome no meio, e é isso que faz esta fonte valer mais que as outras: o
    `tm_id` é o mesmo número dos dois lados, então não há transliteração para
    errar. O nome que vai para a tela passa a ser o do elenco — o mesmo que
    aparece na escalação, no campinho e nos pendurados.

    Quem não casar continua na lista com o nome do TM. Some seria pior:
    jogador recém-contratado ainda não está no elenco congelado, e é
    justamente dele que ninguém sabe se está machucado.
    """
    por_tm = {str(j.get("tm_id")): j for j in (jogadores or []) if j.get("tm_id")}
    casadas = 0
    for l in lesoes:
        j = por_tm.get(str(l.get("tm_id") or ""))
        l["no_elenco"] = bool(j)
        if not j:
            continue
        casadas += 1
        l["spl_id"] = j.get("spl_id")
        l["nome_elenco"] = j.get("nome") or l["nome"]
        l["nome_curto"] = j.get("nome_curto") or ""
        l["foto"] = j.get("foto") or ""
        l["clube_elenco"] = j.get("clube") or l.get("clube")
    return casadas
