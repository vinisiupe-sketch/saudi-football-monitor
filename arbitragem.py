"""
A arbitragem do dia, direto do calendário da federação saudita.

POR QUE ISTO EXISTE, E POR QUE GUARDA
    O SAFF publica a escala de arbitragem no dia do jogo — nunca antes. E não
    guarda: em 16/05/2026 não há ícone de apito em jogo nenhum, nem nos da
    Roshn, enquanto em 26/08 há. A informação some depois de alguns dias.

    Então "raspar quando precisar" não é uma opção. O que não for capturado no
    dia está perdido. Este módulo lê, e o banco guarda.

COMO O SITE ENTREGA
    calendar.php?calendar_date=AAAA-MM-DD  lista os jogos do dia. Onde a
    arbitragem já saiu, a linha traz

        <span class="open-popup" data-url="matchestodayreferee.php?mid=..&mcode=..">

    O mcode é um código por jogo que eu não sei calcular — e não preciso: ele
    vem escrito na própria página. Basta seguir.

    A página do apito devolve uma tabela de duas colunas: papel e
    "Nome (País)". Seis linhas: árbitro, dois assistentes, quarto árbitro,
    VAR e AVAR.

SOBRE OS NOMES
    O SAFF escreve "Sami Aljurays"; o Vini escreve "Sami Al Jaris". Não é
    separação de prefixo, é outra transliteração — nenhuma regra tira uma da
    outra. Pior: a base do SAFF é suja de verdade. "RAYAN ALARYANI" em caixa
    alta, "Fahad ZahraniA" com letra sobrando, "Abddulaziz" com d a mais,
    espaço duplo no meio do nome.

    Por isso o nome final vem de um glossário que o Vini preenche. Enquanto
    um nome não estiver traduzido, ele sai como o SAFF escreveu e entra na
    lista de pendências. Sair errado e avisar é honesto; sair errado calado,
    não. Como os árbitros se repetem muito, a lista se fecha em poucas rodadas.
"""
import re
import unicodedata

# O httpx é importado só dentro de quem vai à rede. Assim a leitura do HTML
# pode ser testada em qualquer lugar, sem depender de biblioteca de rede —
# e é a leitura que erra, não o download.

BASE = "https://www.saff.com.sa/en/"
URL_CALENDARIO = BASE + "calendar.php?calendar_date={dia}"

# A página é declarada em windows-1256 (árabe). Na versão em inglês o conteúdo
# que interessa é latino, mas o cabeçalho e o rodapé têm árabe — decodificar
# como utf-8 estouraria. Deixo o httpx respeitar o charset declarado.
TEMPO_LIMITE = 25.0

# ── Competições ─────────────────────────────────────────────────────────────
# Os nomes exatos como o SAFF escreve em championships.php. Copa do Rei é
# "King Cup", sem apóstrofo e sem s.
COMPETICOES_EXATAS = {
    "Roshn Saudi League",
    "King Cup",
    "Saudi Super Cup",
}
# Estas mudam de nome todo ano ("ACL Two 2025- 2026", "FIFA Intercontinental
# Cup 2026"), então casam por pedaço. Sem isto, a temporada virar em julho
# faria a competição sumir da guia sem ninguém entender por quê.
COMPETICOES_POR_PEDACO = ("acl ", "afc champions", "intercontinental")


def competicao_coberta(nome: str) -> bool:
    n = " ".join((nome or "").split())
    if n in COMPETICOES_EXATAS:
        return True
    baixo = n.lower()
    return any(p in baixo for p in COMPETICOES_POR_PEDACO)


# ── Papéis ──────────────────────────────────────────────────────────────────
# A ordem aqui é a ordem no post. O SAFF já devolve nesta sequência, mas
# depender da ordem do site é depender de coisa que não prometeram manter.
PAPEIS = [
    ("Referee",             "👤"),
    ("Assistant Referee 1", "🚩"),
    ("Assistant Referee 2", "🚩"),
    ("Fourth Official",     "4️⃣"),
    ("VAR",                 "📟"),
    ("AVAR",                "📟"),
]
ORDEM_PAPEL = {p: i for i, (p, _) in enumerate(PAPEIS)}
EMOJI_PAPEL = dict(PAPEIS)

# ── Bandeiras ───────────────────────────────────────────────────────────────
# Monto a bandeira a partir do código de duas letras, em vez de guardar 200
# emojis à mão. País que eu não conhecer sai sem bandeira E entra na lista de
# pendências — chutar 🇸🇦 porque "quase sempre é saudita" seria pôr um árbitro
# estrangeiro com a bandeira errada num post publicado.
PAISES = {
    "saudi arabia": "SA", "ksa": "SA",
    "kuwait": "KW", "qatar": "QA", "bahrain": "BH", "oman": "OM",
    "united arab emirates": "AE", "uae": "AE",
    "iraq": "IQ", "jordan": "JO", "lebanon": "LB", "syria": "SY",
    "yemen": "YE", "egypt": "EG", "morocco": "MA", "tunisia": "TN",
    "algeria": "DZ", "libya": "LY", "sudan": "SD", "palestine": "PS",
    "iran": "IR", "uzbekistan": "UZ", "tajikistan": "TJ",
    "kyrgyzstan": "KG", "turkmenistan": "TM", "kazakhstan": "KZ",
    "japan": "JP", "south korea": "KR", "korea republic": "KR",
    "china": "CN", "china pr": "CN", "hong kong": "HK",
    "australia": "AU", "new zealand": "NZ",
    "thailand": "TH", "vietnam": "VN", "malaysia": "MY",
    "singapore": "SG", "indonesia": "ID", "india": "IN",
    "greece": "GR", "portugal": "PT", "spain": "ES", "italy": "IT",
    "france": "FR", "germany": "DE", "england": "GB", "netherlands": "NL",
    "romania": "RO", "poland": "PL", "serbia": "RS", "croatia": "HR",
    "türkiye": "TR", "turkey": "TR", "russia": "RU", "ukraine": "UA",
    "brazil": "BR", "argentina": "AR", "uruguay": "UY", "chile": "CL",
    "colombia": "CO", "mexico": "MX", "united states": "US", "usa": "US",
    "senegal": "SN", "mali": "ML", "gambia": "GM", "algeria ": "DZ",
    "south africa": "ZA", "zambia": "ZM", "kenya": "KE", "nigeria": "NG",
    "ivory coast": "CI", "côte d'ivoire": "CI", "cote d'ivoire": "CI",
    "cameroon": "CM", "armenia": "AM", "belgium": "BE", "switzerland": "CH",
    "ghana": "GH", "guinea": "GN", "georgia": "GE", "montenegro": "ME",
    # Faltavam, e apareceram no elenco de verdade (03/09/26):
    "cabo verde": "CV", "cape verde": "CV", "ecuador": "EC",
    "new caledonia": "NC", "niger": "NE", "slovakia": "SK", "venezuela": "VE",

    # ── OS MESMOS PAÍSES, EM ÁRABE ────────────────────────────────────────
    # Isto é o conserto de um defeito que ficou dias em pé sem ninguém ver o
    # motivo: a escalação saía sem bandeirinha nenhuma. A tabela `jogador`
    # vem da API da própria liga, e ela escreve a nacionalidade EM ÁRABE —
    # "السعودية" para 255 dos 573 jogadores. Aqui só havia grafia latina,
    # então `bandeira()` devolvia "" para quase todo mundo e o post saía
    # limpo, sem erro em lugar nenhum.
    #
    # As latinas continuam: parte da tabela tem país em latim (veio de outra
    # fonte), e as duas grafias convivem no mesmo elenco.
    "السعودية": "SA", "الأردن": "JO", "مصر": "EG", "المغرب": "MA",
    "الجزائر": "DZ", "تونس": "TN",
    "البرازيل": "BR", "أوروغواي": "UY", "كولومبيا": "CO", "المكسيك": "MX",
    "الإكوادور": "EC", "فنزويلا": "VE", "بنما": "PA", "كندا": "CA",
    "سورينام": "SR", "كوراساو": "CW", "غيانا الفرنسية": "GF",
    "إسبانيا": "ES", "البرتغال": "PT", "فرنسا": "FR", "إيطاليا": "IT",
    "ألمانيا": "DE", "هولندا": "NL", "بلجيكا": "BE", "إنجلترا": "GB",
    "إسكتلندا": "GB", "السويد": "SE", "النرويج": "NO", "الدنمارك": "DK",
    "بولندا": "PL", "رومانيا": "RO", "بلغاريا": "BG", "صربيا": "RS",
    "كرواتيا": "HR", "البوسنة والهرسك": "BA", "ألبانيا": "AL",
    "كوسوفو": "XK", "سلوفاكيا": "SK", "ليتوانيا": "LT", "لوكسمبورغ": "LU",
    "اليونان": "GR", "تركيا": "TR", "أرمينيا": "AM", "الجبل الأسود": "ME",
    "السنغال": "SN", "غانا": "GH", "غينيا": "GN", "غينيا بيساو": "GW",
    "غينيا الاستوائية": "GQ", "غامبيا": "GM", "مالي": "ML",
    "ساحل العاج": "CI", "الكاميرون": "CM", "الغابون": "GA", "توغو": "TG",
    "الكونغو": "CG", "الكونغو الديمقراطية": "CD", "رواندا": "RW",
    "زامبيا": "ZM", "ليبيريا": "LR", "نيجيريا": "NG", "جزر القمر": "KM",
    "الرأس الأخضر": "CV", "النيجر": "NE", "كاليدونيا الجديدة": "NC",
}


# ── A TABELA COMPLETA, EM INGLÊS ────────────────────────────────────────────
# Por que existe uma SEGUNDA tabela, em vez de eu ir engordando a de cima.
#
# A de cima é escrita à mão e cresceu por remendo: toda vez que aparecia um
# jogador de um país novo, alguém acrescentava a linha. Isso deu no que tinha
# de dar — em 09/09/26 a escalação do dia acusou sete países sem bandeira
# ("Lithuania", "Suriname", "Curaçao", "French Guiana", "Comoros", "Togo",
# "Albania", "Bosnia and Herzegovina", "Congo DR") e o engraçado é que TODOS
# já estavam lá... em árabe. Só faltava a grafia latina. O remendo seguinte
# seria acrescentar essas sete e esperar a próxima rodada trazer a oitava.
#
# Esta tabela é o mapa inteiro da ISO 3166-1, escrito de uma vez. A de cima
# continua e continua tendo prioridade: ela guarda o que a ISO não tem —
# as grafias em árabe, os apelidos que as fontes usam ("KSA", "UAE", "China
# PR") e as decisões já tomadas (Inglaterra e Escócia saem com a bandeira do
# Reino Unido, porque as bandeiras de subdivisão não desenham em boa parte
# dos aparelhos).
PAISES_ISO = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ",
    "american samoa": "AS", "andorra": "AD", "angola": "AO",
    "anguilla": "AI", "antigua and barbuda": "AG", "argentina": "AR",
    "armenia": "AM", "aruba": "AW", "australia": "AU", "austria": "AT",
    "azerbaijan": "AZ", "bahamas": "BS", "bahrain": "BH",
    "bangladesh": "BD", "barbados": "BB", "belarus": "BY", "belgium": "BE",
    "belize": "BZ", "benin": "BJ", "bermuda": "BM", "bhutan": "BT",
    "bolivia": "BO", "bosnia and herzegovina": "BA", "botswana": "BW",
    "brazil": "BR", "brunei": "BN", "bulgaria": "BG", "burkina faso": "BF",
    "burundi": "BI", "cambodia": "KH", "cameroon": "CM", "canada": "CA",
    "cape verde": "CV", "cayman islands": "KY",
    "central african republic": "CF", "chad": "TD", "chile": "CL",
    "china": "CN", "colombia": "CO", "comoros": "KM", "congo": "CG",
    "congo dr": "CD", "costa rica": "CR", "croatia": "HR", "cuba": "CU",
    "curacao": "CW", "cyprus": "CY", "czechia": "CZ",
    "czech republic": "CZ", "denmark": "DK", "djibouti": "DJ",
    "dominica": "DM", "dominican republic": "DO", "ecuador": "EC",
    "egypt": "EG", "el salvador": "SV", "equatorial guinea": "GQ",
    "eritrea": "ER", "estonia": "EE", "eswatini": "SZ", "ethiopia": "ET",
    "faroe islands": "FO", "fiji": "FJ", "finland": "FI", "france": "FR",
    "french guiana": "GF", "french polynesia": "PF", "gabon": "GA",
    "gambia": "GM", "georgia": "GE", "germany": "DE", "ghana": "GH",
    "gibraltar": "GI", "greece": "GR", "greenland": "GL", "grenada": "GD",
    "guadeloupe": "GP", "guam": "GU", "guatemala": "GT", "guinea": "GN",
    "guinea-bissau": "GW", "guinea bissau": "GW", "guyana": "GY",
    "haiti": "HT", "honduras": "HN", "hong kong": "HK", "hungary": "HU",
    "iceland": "IS", "india": "IN", "indonesia": "ID", "iran": "IR",
    "iraq": "IQ", "ireland": "IE", "israel": "IL", "italy": "IT",
    "jamaica": "JM", "japan": "JP", "jordan": "JO", "kazakhstan": "KZ",
    "kenya": "KE", "kiribati": "KI", "kosovo": "XK", "kuwait": "KW",
    "kyrgyzstan": "KG", "laos": "LA", "latvia": "LV", "lebanon": "LB",
    "lesotho": "LS", "liberia": "LR", "libya": "LY",
    "liechtenstein": "LI", "lithuania": "LT", "luxembourg": "LU",
    "macau": "MO", "madagascar": "MG", "malawi": "MW", "malaysia": "MY",
    "maldives": "MV", "mali": "ML", "malta": "MT", "martinique": "MQ",
    "mauritania": "MR", "mauritius": "MU", "mexico": "MX",
    "moldova": "MD", "monaco": "MC", "mongolia": "MN", "montenegro": "ME",
    "montserrat": "MS", "morocco": "MA", "mozambique": "MZ",
    "myanmar": "MM", "namibia": "NA", "nepal": "NP", "netherlands": "NL",
    "new caledonia": "NC", "new zealand": "NZ", "nicaragua": "NI",
    "niger": "NE", "nigeria": "NG", "north korea": "KP",
    "north macedonia": "MK", "norway": "NO", "oman": "OM",
    "pakistan": "PK", "palestine": "PS", "panama": "PA",
    "papua new guinea": "PG", "paraguay": "PY", "peru": "PE",
    "philippines": "PH", "poland": "PL", "portugal": "PT",
    "puerto rico": "PR", "qatar": "QA", "reunion": "RE", "romania": "RO",
    "russia": "RU", "rwanda": "RW", "saint kitts and nevis": "KN",
    "saint lucia": "LC", "saint vincent and the grenadines": "VC",
    "samoa": "WS", "san marino": "SM", "sao tome and principe": "ST",
    "saudi arabia": "SA", "senegal": "SN", "serbia": "RS",
    "seychelles": "SC", "sierra leone": "SL", "singapore": "SG",
    "slovakia": "SK", "slovenia": "SI", "solomon islands": "SB",
    "somalia": "SO", "south africa": "ZA", "south korea": "KR",
    "south sudan": "SS", "spain": "ES", "sri lanka": "LK", "sudan": "SD",
    "suriname": "SR", "sweden": "SE", "switzerland": "CH", "syria": "SY",
    "taiwan": "TW", "tajikistan": "TJ", "tanzania": "TZ",
    "thailand": "TH", "timor-leste": "TL", "togo": "TG", "tonga": "TO",
    "trinidad and tobago": "TT", "tunisia": "TN", "turkey": "TR",
    "turkmenistan": "TM", "uganda": "UG", "ukraine": "UA",
    "united arab emirates": "AE", "united kingdom": "GB",
    "united states": "US", "uruguay": "UY", "uzbekistan": "UZ",
    "vanuatu": "VU", "venezuela": "VE", "vietnam": "VN", "yemen": "YE",
    "zambia": "ZM", "zimbabwe": "ZW",

    # Grafias que só o futebol usa. Ficam aqui, e não na tabela de cima,
    # porque são regra geral e não remendo de um elenco específico.
    "congo dr.": "CD", "dr congo": "CD",
    "democratic republic of the congo": "CD", "congo-brazzaville": "CG",
    "korea republic": "KR", "korea dpr": "KP", "ir iran": "IR",
    "chinese taipei": "TW", "china pr": "CN", "cabo verde": "CV",
    "ivory coast": "CI", "cote d'ivoire": "CI", "côte d'ivoire": "CI",
    "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "great britain": "GB",
}


def _sem_acento(texto: str) -> str:
    """A mesma palavra sem os acentos — só para COMPARAR, nunca para exibir.

    Não uso o truque de encode("ascii", "ignore") que aparece em
    chave_do_arbitro: aqui passa árabe, e aquilo apagaria a palavra inteira.
    """
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


# Um índice sem acento das duas tabelas, montado uma vez. É o que faz
# "Curaçao" e "Curacao" caírem no mesmo lugar — as fontes escrevem dos dois
# jeitos, e às vezes a mesma fonte escreve dos dois jeitos no mesmo dia.
_SEM_ACENTO = {}


def _montar_indice():
    """Refaz o índice sem acento a partir das duas tabelas.

    É função, e não um laço solto no corpo do módulo, por um motivo só: a
    ordem aqui É a regra de prioridade (PAISES por último, então ele
    sobrescreve), e regra que só existe dentro de um laço de import não dá
    para exercitar em teste. Assim o teste injeta uma divergência entre as
    duas tabelas, chama isto, e confere quem ganhou.
    """
    _SEM_ACENTO.clear()
    for tabela in (PAISES_ISO, PAISES):   # PAISES por último: palavra final
        for nome, sigla in tabela.items():
            _SEM_ACENTO[_sem_acento(nome)] = sigla


_montar_indice()


def bandeira(pais: str) -> str:
    """A bandeira do país, ou "" se eu não souber qual é.

    Três tentativas, da mais específica para a mais geral: a tabela escrita à
    mão (que tem o árabe e os apelidos), a tabela da ISO, e por fim as duas
    ignorando acento.
    """
    chave = " ".join((pais or "").strip().lower().split())
    if not chave:
        return ""
    sigla = PAISES.get(chave) or PAISES_ISO.get(chave) \
        or _SEM_ACENTO.get(_sem_acento(chave))
    if not sigla:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in sigla)


# ── Normalização de nome ────────────────────────────────────────────────────
def chave_do_arbitro(nome: str) -> str:
    """A forma de comparação de um nome vindo do SAFF.

    Caixa, acento, espaço duplo e pontuação não são diferença de pessoa. Sem
    isto, "KHALID ALJOHANI" e "Khalid Aljohani" viravam dois árbitros
    distintos no glossário, e você traduziria o mesmo sujeito duas vezes.
    """
    t = unicodedata.normalize("NFKD", (nome or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z ]+", " ", t)
    return " ".join(t.lower().split())


# ── Leitura do calendário ───────────────────────────────────────────────────
def _texto(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def jogos_do_calendario(html: str) -> list[dict]:
    """Os jogos do dia que já têm arbitragem publicada.

    Devolve TODOS, inclusive de competições que não cobrimos. Filtrar aqui
    dentro esconderia da tela o fato de que existia jogo com apito que eu
    decidi ignorar — e essa decisão precisa ser visível.
    """
    from bs4 import BeautifulSoup
    sopa = BeautifulSoup(html or "", "lxml")

    # A página repete a mesma grade duas vezes (desktop e celular). Pego só a
    # primeira tabela que tenha uma data no cabeçalho; a segunda é a mesma
    # coisa sem a coluna de horário.
    tabela = None
    for t in sopa.find_all("table"):
        if re.search(r"\d{2}-\d{2}-\d{4}", t.get_text(" ")):
            tabela = t
            break
    if tabela is None:
        return []

    jogos, competicao = [], ""
    for tr in tabela.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) <= 1:
            competicao = _texto(tr)
            continue
        apito = tr.find("span", class_="open-popup")
        if not apito:
            continue
        url = (apito.get("data-url") or "").strip()
        if not url:
            continue
        m = re.search(r"mid=(\d+)", url)
        colunas = [_texto(td) for td in tds]
        hora = colunas[0] if re.match(r"^\d{1,2}:\d{2}$", colunas[0]) else ""
        jogos.append({
            "mid": int(m.group(1)) if m else None,
            "url": BASE + url.replace("&amp;", "&"),
            "competicao": competicao,
            "hora": hora,
            "linha": " ".join(colunas),
        })
    return jogos


TIMES_NO_CABECALHO = re.compile(r"\s+[Xx]\s+")


def escala_da_pagina(html: str) -> dict:
    """Lê a tabela do apito: quem são os times e quem apita.

    O cabeçalho vem como "Al Faisaly X Al Fateh<br>Roshn Saudi League". Separo
    pelo <br>, e não pelo texto corrido, porque sem a quebra "Al FatehRoshn"
    fica grudado e o nome do clube vira outro clube.
    """
    from bs4 import BeautifulSoup
    sopa = BeautifulSoup(html or "", "lxml")
    linhas = sopa.find_all("tr")
    if not linhas:
        return {"casa": "", "fora": "", "competicao": "", "papeis": []}

    topo = linhas[0]
    for br in topo.find_all("br"):
        br.replace_with("\n")
    partes = [p.strip() for p in topo.get_text().split("\n") if p.strip()]
    confronto = partes[0] if partes else ""
    competicao = " ".join(partes[1].split()) if len(partes) > 1 else ""
    lados = TIMES_NO_CABECALHO.split(confronto, 1)
    casa = " ".join(lados[0].split()) if lados else ""
    fora = " ".join(lados[1].split()) if len(lados) > 1 else ""

    papeis = []
    for tr in linhas[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        papel = _texto(tds[0])
        bruto = _texto(tds[1])
        m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", bruto)
        nome = " ".join((m.group(1) if m else bruto).split())
        pais = " ".join((m.group(2) if m else "").split())
        if not nome:
            continue
        papeis.append({"papel": papel, "nome_saff": nome, "pais": pais})
    papeis.sort(key=lambda p: ORDEM_PAPEL.get(p["papel"], 99))
    return {"casa": casa, "fora": fora, "competicao": competicao,
            "papeis": papeis}


# ── Rede ────────────────────────────────────────────────────────────────────
# ── A liga oficial ──────────────────────────────────────────────────────────
#
# O SAFF diz QUAIS jogos já têm arbitragem — inclusive Copa do Rei e Supercopa,
# que a liga não cobre. A liga diz COMO se escreve o nome. Cada uma no que é
# boa.
#
# Sobre a grafia: nenhuma das fontes é coerente, nem consigo mesma. No mesmo
# jogo a liga escreveu "Al-Salam" com hífen, "Al Ghamdi" com espaço e
# "Alahmari" grudado. O campo `shortName` da API é o mais limpo dos quatro —
# é o nome curto que eles usam em tela, sem a corrente de patronímicos que
# aparece no site ("Abdullah bin Nasser bin Mohammed Al Ojaym").
#
# Uniformizo só o hífen. Não é capricho: sem isso o mesmo post sai com duas
# convenções, e a incoerência que é DELES vira aparentemente sua.
# Como a liga chama cada papel, traduzido para os nomes que o SAFF usa —
# que são os que o resto do módulo já fala.
PAPEL_DA_LIGA = {
    "Referee": "Referee",
    "Assistant Referee 1": "Assistant Referee 1",
    "Assistant Referee 2": "Assistant Referee 2",
    "Fourth Official": "Fourth Official",
    "VAR": "VAR",
    "Assistant VAR Official": "AVAR",
    "AVAR": "AVAR",
}


def uniformizar_al(nome: str) -> str:
    """'Al-Salam' e 'Alahmari' viram 'Al Salam' e 'Al Ahmari'.

    Só mexe no separador. NÃO troca vogal: 'Khald' continua 'Khald' e
    'Jurays' continua 'Jurays'. Consertar a grafia seria eu escolhendo como
    se escreve o nome de uma pessoa, e essa não é uma escolha minha.
    """
    saida = []
    for p in " ".join((nome or "").replace("Al-", "Al ").split()).split():
        if p[:2] in ("Al", "AL", "al") and len(p) > 4 and p[2:3].isalpha():
            saida.append("Al " + p[2:].capitalize())
        else:
            saida.append(p)
    return " ".join(saida)


def _confronto(casa: str, fora: str) -> frozenset:
    """Mesma identidade de jogo que a prévia usa — de propósito, uma só."""
    import liga_spl
    return liga_spl.confronto(casa, fora)


def escala_da_liga(dia: str, cliente) -> dict:
    """Mapa {confronto: [papéis]} com os nomes como a liga escreve."""
    import liga_spl
    sid = liga_spl.temporada(dia, cliente)
    if not sid:
        return {}
    saida = {}
    for j in liga_spl.jogos_do_dia(sid, dia, cliente):
        mid = j.get("matchId")
        if not mid:
            continue
        try:
            fatos = liga_spl.arbitros_do_jogo(sid, mid, cliente)
        except Exception:
            continue
        papeis = []
        for a in (fatos.get("referees") or []):
            papel = PAPEL_DA_LIGA.get((a.get("role") or "").strip())
            nome = uniformizar_al(a.get("shortName") or "")
            if not papel or not nome:
                continue
            papeis.append({"papel": papel, "nome": nome,
                           "pais": (a.get("nationality") or "").strip()})
        if papeis:
            saida[liga_spl.confronto((j.get("home") or {}).get("shortName") or "",
                                     (j.get("away") or {}).get("shortName") or "")] = papeis
    return saida


def _baixar(url: str, cliente) -> str:
    r = cliente.get(url, timeout=TEMPO_LIMITE, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; IARABAO/1.0)"})
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() in ("ascii", "iso-8859-1"):
        r.encoding = "windows-1256"
    return r.text


def buscar_do_dia(dia: str) -> dict:
    """A arbitragem publicada para esta data (AAAA-MM-DD).

    Devolve {"jogos": [...], "ignorados": [...], "erros": [...]}.

    "ignorados" são os jogos com apito de competição que não cobrimos. Eles
    voltam de propósito: quando um dia vier vazio, a diferença entre "o SAFF
    ainda não publicou" e "publicou, mas só de sub-16" muda completamente o
    que fazer a seguir, e essa diferença precisa chegar até a tela.
    """
    import httpx
    saida = {"jogos": [], "ignorados": [], "erros": []}
    with httpx.Client() as cliente:
        try:
            html = _baixar(URL_CALENDARIO.format(dia=dia), cliente)
        except Exception as e:
            saida["erros"].append(f"calendário de {dia}: {type(e).__name__}: {e}")
            return saida

        # A liga só cobre a Roshn. Se ela falhar, seguimos com o SAFF: ter o
        # nome escrito de um jeito pior é muito melhor que não ter o nome.
        try:
            da_liga = escala_da_liga(dia, cliente)
        except Exception as e:
            da_liga = {}
            saida["erros"].append(f"site da liga: {type(e).__name__}: {e}")

        for jogo in jogos_do_calendario(html):
            if not competicao_coberta(jogo["competicao"]):
                saida["ignorados"].append({"competicao": jogo["competicao"],
                                           "linha": jogo["linha"]})
                continue
            try:
                escala = escala_da_pagina(_baixar(jogo["url"], cliente))
            except Exception as e:
                saida["erros"].append(
                    f"apito do jogo {jogo['mid']}: {type(e).__name__}: {e}")
                continue
            if not escala["papeis"]:
                saida["erros"].append(
                    f"jogo {jogo['mid']}: página do apito veio sem nenhum nome")
                continue
            papeis = _juntar_fontes(
                escala["papeis"],
                da_liga.get(_confronto(escala["casa"], escala["fora"])) or [])
            saida["jogos"].append({
                "mid": jogo["mid"], "dia": dia, "hora": jogo["hora"],
                "competicao": escala["competicao"] or jogo["competicao"],
                "casa": escala["casa"], "fora": escala["fora"],
                "papeis": papeis,
            })

        # Jogo que a liga tem e o SAFF não. Hoje não deve acontecer — as duas
        # publicam no dia —, mas se acontecer eu quero saber, e não descobrir
        # meses depois que faltava jogo na guia.
        vistos = {_confronto(j["casa"], j["fora"]) for j in saida["jogos"]}
        for conf in da_liga:
            if conf not in vistos:
                saida["erros"].append(
                    f"a liga publicou a escala de {' x '.join(sorted(conf))} "
                    f"e o SAFF não — este jogo ficou de fora")
    return saida


def _juntar_fontes(do_saff: list[dict], da_liga: list[dict]) -> list[dict]:
    """Um registro por papel, guardando o nome das DUAS fontes.

    Guardo os dois em vez de escolher aqui porque a escolha pode mudar — e se
    eu jogasse fora o nome do SAFF, mudar de ideia exigiria buscar de novo num
    site que já apagou a página.
    """
    por_papel = {p["papel"]: p for p in da_liga}
    juntos = []
    for p in do_saff:
        liga = por_papel.get(p["papel"]) or {}
        juntos.append({
            "papel": p["papel"],
            "nome_saff": p.get("nome_saff") or "",
            "nome_liga": liga.get("nome") or "",
            "pais": p.get("pais") or liga.get("pais") or "",
        })
    return juntos


def nome_publicado(p: dict, traduzir=None) -> str:
    """O nome que vai para o post, na ordem de precedência combinada.

    1. o seu glossário, se você tiver definido
    2. a liga oficial
    3. o SAFF

    A ordem não é arbitrária: a única grafia que você controla vem primeiro, e
    a última é a que sempre existe.
    """
    traduzir = traduzir or (lambda n: "")
    bruto = " ".join((p.get("nome_saff") or "").split())
    return (traduzir(bruto) or (p.get("nome_liga") or "").strip()
            or bruto)


# ── Texto do post ───────────────────────────────────────────────────────────
CABECALHO_PADRAO = "👨‍⚖️ 𝐀𝐑𝐁𝐈𝐓𝐑𝐀𝐆𝐄𝐌 𝐃𝐎 𝐃𝐈𝐀"


def nome_do_clube(bruto: str) -> str:
    """O clube na grafia da tabela do canal.

    Time estrangeiro vem como "Gamba Osaka - JPN" e não está no glossário —
    tiro o sufixo do país e uso como veio. É o que o Vini escreve à mão.
    """
    import glossary
    limpo = re.sub(r"\s*-\s*[A-Z]{3}$", "", " ".join((bruto or "").split()))
    return glossary.padronizar_clube(limpo) or limpo


def montar_texto(jogos: list[dict], traduzir=None,
                 cabecalho: str = CABECALHO_PADRAO) -> str:
    """O bloco pronto para copiar, no formato do canal.

    `traduzir` recebe o nome como o SAFF escreveu e devolve a grafia do canal,
    ou "" se ainda não houver tradução — caso em que o nome do SAFF é usado.
    """
    traduzir = traduzir or (lambda n: "")
    blocos = []
    for j in jogos:
        linhas = [f"{nome_do_clube(j.get('casa'))} x {nome_do_clube(j.get('fora'))}"]
        for p in j.get("papeis") or []:
            emoji = EMOJI_PAPEL.get(p.get("papel"), "•")
            nome = nome_publicado(p, traduzir)
            flag = bandeira(p.get("pais"))
            linhas.append(f"{emoji} {flag} {nome}".replace("  ", " ").strip())
        blocos.append("\n".join(linhas))
    return (cabecalho + "\n\n" + "\n\n".join(blocos)).strip()


def elenco_do_dia(jogos: list[dict], traduzir=None) -> list[dict]:
    """Todo mundo que apita hoje, com as duas grafias e a que vai sair.

    A tela mostra esta lista inteira, e não só o que está faltando. O motivo:
    a liga também erra — ela escreveu "Khald Alahmari" —, e um nome errado que
    NÃO está numa lista de pendências é um nome errado que ninguém revisa.
    """
    traduzir = traduzir or (lambda n: "")
    vistos, saida = set(), []
    for j in jogos:
        for p in j.get("papeis") or []:
            bruto = " ".join((p.get("nome_saff") or "").split())
            chave = chave_do_arbitro(bruto)
            if not chave or chave in vistos:
                continue
            vistos.add(chave)
            seu = traduzir(bruto)
            liga = (p.get("nome_liga") or "").strip()
            saida.append({
                "chave": chave, "saff": bruto, "liga": liga,
                "seu": seu, "pais": p.get("pais") or "",
                "publicado": nome_publicado(p, traduzir),
                "fonte": "seu" if seu else ("liga" if liga else "saff"),
            })
    return saida


def nomes_sem_traducao(jogos: list[dict], traduzir=None) -> list[dict]:
    """Só quem vai sair com a grafia do SAFF — a pior das três.

    Aqui a liga não tinha o nome e você não definiu. É o único caso em que o
    post publica "Alkhurbush" grudado, e por isso é o único que vira aviso.
    """
    return [n for n in elenco_do_dia(jogos, traduzir) if n["fonte"] == "saff"]


def paises_desconhecidos(jogos: list[dict]) -> list[str]:
    """Países sem bandeira no meu mapa. Sai sem bandeira, mas não em silêncio."""
    faltando = []
    for j in jogos:
        for p in j.get("papeis") or []:
            pais = " ".join((p.get("pais") or "").split())
            if pais and not bandeira(pais) and pais not in faltando:
                faltando.append(pais)
    return faltando
