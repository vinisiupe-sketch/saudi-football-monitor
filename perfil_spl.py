"""
Nascimento e altura, colhidos da página de jogador do site da liga.

POR QUE ISTO EXISTE
    A escalação da API da liga traz nacionalidade e mais nada. Nem data de
    nascimento, nem altura. Sondei sete endereços possíveis na API — todos
    404. Não existe endpoint de perfil de jogador.

    O site tem. `spl.com.sa/en/players/{slug}/` traz dateOfBirth, height,
    weight, nationalityIsoCode e bibNumber. E traz de TODO o elenco do clube
    daquele jogador, não só dele: uma página rende 29 pessoas.

POR QUE VALE A PENA
    Data de nascimento é a única chave que não sofre transliteração.
    1996-05-04 é igual em árabe, em latim, no Transfermarkt e na
    API-Football. Nome é grafia; data é fato. A partir daqui o nome vira
    confirmação, e não critério.

COMO EU EVITO CASAR A PESSOA ERRADA AO LER
    O HTML é dado de RSC do Next, com as aspas escapadas, e cada objeto de
    jogador vem colado no seguinte. Se eu pegasse "o dateOfBirth mais próximo
    do playerId" sem limite, um objeto sem data herdaria a data do vizinho —
    e ficaria plausível. Então corto o texto no PRÓXIMO playerId: o que
    estiver depois disso não é desta pessoa, e quem não tem data dentro da
    própria fatia simplesmente fica sem data.

SOBRE RASPAR
    O robots.txt do site permite /en/players/. São ~40 páginas, uma vez, sem
    laço automático. Não é um coletor: é uma colheita.
"""
import re
import unicodedata

SITE = "https://www.spl.com.sa"
TEMPO_LIMITE = 30.0
UA = "Mozilla/5.0 (compatible; IARABAO/1.0)"

# Quantas páginas eu me permito puxar numa colheita. Cada uma rende ~29
# pessoas, então 40 cobre a liga inteira com folga — e o teto existe para o
# dia em que a página mudar de formato e nenhuma leitura render nada.
TETO_DE_PAGINAS = 40

_MARCA = re.compile(r'"playerId":"(spl::Football_Player::[0-9a-f]+)"')
_TIME = re.compile(r'"teamSlug":"([^"]*)"[\s\S]{0,400}?"officialName":"([^"]*)"')


def clube_da_pagina(texto: str) -> str:
    """O clube que a página inteira descreve, ou "" se houver mais de um.

    Conferi antes de confiar: a página do Diallo tem 29 jogadores e um só
    teamSlug ('abha'); a do Salem tem 29 e um só ('al-hilal'); e não há uma
    pessoa em comum entre as duas. Ou seja, a lista é o elenco do clube, e o
    clube pode ser atribuído a todo mundo da página.

    Se um dia aparecerem dois clubes na mesma página, essa premissa deixou de
    valer — e aí eu devolvo vazio em vez de escolher um.
    """
    achados = {}
    for slug, nome in _TIME.findall(texto):
        achados[slug] = nome
    if len(achados) != 1:
        return ""
    return next(iter(achados.values()))


def slug_de(nome: str) -> str:
    """'Abdou Diallo' -> 'abdou-diallo'. O mesmo que o site usa nos nomes curtos.

    Para quem tem nome do meio o site põe tudo no slug e este palpite erra —
    e é por isso que quem chama CONFERE o id da página antes de acreditar.
    """
    limpo = unicodedata.normalize("NFKD", nome or "")
    limpo = "".join(c for c in limpo if not unicodedata.combining(c))
    limpo = re.sub(r"[^A-Za-z0-9]+", "-", limpo.lower()).strip("-")
    return limpo


def _campo(trecho: str, nome: str) -> str:
    achado = re.search(f'"{nome}":"([^"]*)"', trecho)
    return achado.group(1) if achado else ""


def desdobrar(html: str, arabe: bool = False) -> dict[str, dict]:
    """Todo mundo que a página descreve, por playerId."""
    texto = (html or "").replace('\\"', '"')
    marcas = list(_MARCA.finditer(texto))
    clube = clube_da_pagina(texto)
    gente: dict[str, dict] = {}
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        fatia = texto[m.start():fim]
        nasc = _campo(fatia, "dateOfBirth")[:10]
        nome = " ".join(x for x in (_campo(fatia, "mediaFirstName"),
                                    _campo(fatia, "mediaLastName")) if x).strip()
        if not nasc and not nome:
            continue
        pessoa = gente.setdefault(m.group(1), {"spl_id": m.group(1)})
        if nasc:
            pessoa["nascimento"] = nasc
        if arabe:
            if nome:
                pessoa["nome_ar"] = nome
        else:
            if nome:
                pessoa["nome"] = nome
            if clube:
                pessoa["clube"] = clube
            # A foto vem como CAMINHO em `imagery.playerImage_home_middle`, e
            # como URL inteira em `playerImage`. Guardo o caminho, igual à
            # varredura de escalação faz: se eles trocarem o servidor de
            # imagem, é uma constante para mudar, não uma coluna para
            # reescrever. Por isso não uso `playerImage` aqui.
            for chave, campo in (("slug", "playerSlug"),
                                 ("foto", "playerImage_home_middle"),
                                 ("altura", "height"),
                                 ("nac_iso", "nationalityIsoCode"),
                                 ("nacionalidade", "nationality"),
                                 ("posicao", "roleLabel"),
                                 ("camisa", "bibNumber")):
                valor = _campo(fatia, campo)
                if valor:
                    pessoa[chave] = valor
    return gente


def _pagina(slug: str, idioma: str, cliente) -> str:
    r = cliente.get(f"{SITE}/{idioma}/players/{slug}/", timeout=TEMPO_LIMITE,
                    follow_redirects=True, headers={"User-Agent": UA})
    if r.status_code != 200:
        return ""
    return r.text


def colher(slug: str, cliente, com_arabe: bool = True) -> dict[str, dict]:
    """Uma página, nas duas escritas, já juntas por id.

    A versão árabe é a MESMA página noutro idioma, com os mesmos playerId. É
    de graça: uma requisição a mais por elenco, e o nome árabe de gente que a
    escalação nunca relacionou.
    """
    gente = desdobrar(_pagina(slug, "en", cliente))
    if not gente:
        return {}
    if com_arabe:
        for pid, arabe in desdobrar(_pagina(slug, "ar", cliente), arabe=True).items():
            if pid in gente and arabe.get("nome_ar"):
                gente[pid]["nome_ar"] = arabe["nome_ar"]
    return gente


def sementes_para(faltam: list[dict], elenco_do_clube) -> tuple[list[dict], list[str]]:
    """De quem PRECISA do dado para quem serve de PORTA.

    As duas listas não são a mesma, e confundi-las custou nove jogadores do Al
    Khaleej. A colheita chutava o slug pelo nome de quem estava incompleto; os
    nomes deles são longos, o chute errava, e o colega de nome curto — que
    abriria a página do clube inteiro de uma vez — já estava completo, logo
    nunca era candidato. A página do clube não era aberta em rodada nenhuma e
    eles ficavam parados para sempre, sem erro nenhum aparecendo.

    Agora basta que o CLUBE tenha alguém incompleto: a semente pode ser
    qualquer pessoa dele. Quem não tem clube continua só com o próprio nome,
    porque aí não há elenco onde procurar uma porta.
    """
    clubes: list[str] = []
    sementes: list[dict] = []
    for p in faltam:
        clube = (p.get("clube") or "").strip()
        if not clube:
            sementes.append(p)
        elif clube not in clubes:
            clubes.append(clube)
    for clube in clubes:
        sementes.extend(elenco_do_clube(clube))
    return sementes, clubes


def colher_a_partir_de(candidatos: list[dict], cliente,
                       teto: int = TETO_DE_PAGINAS) -> tuple[dict[str, dict], dict]:
    """Colhe elencos inteiros partindo de uma lista de gente sem nascimento.

    `candidatos` são linhas com spl_id e nome. Para cada uma eu chuto o slug e
    confiro: se a página não falar do id que eu esperava, o chute errou e eu
    sigo — nunca aceito a página "parecida".

    Como cada página rende o elenco todo, a lista encolhe rápido: em geral uma
    página por clube resolve trinta pessoas.
    """
    colhido: dict[str, dict] = {}
    tentadas = acertos = erros = 0
    for linha in candidatos:
        if tentadas >= teto:
            break
        pid = linha.get("spl_id") or ""
        if not pid or pid in colhido:
            continue
        slug = slug_de(linha.get("nome") or "")
        if not slug:
            continue
        tentadas += 1
        try:
            gente = colher(slug, cliente)
        except Exception:
            erros += 1
            continue
        # A conferência: a página TEM que falar da pessoa que eu procurava.
        # Sem isso, um slug parecido traria o elenco de outro clube e eu
        # gravaria dados certos na pessoa errada.
        if pid not in gente:
            erros += 1
            continue
        acertos += 1
        for k, v in gente.items():
            colhido.setdefault(k, v)
    return colhido, {"paginas_tentadas": tentadas, "paginas_lidas": acertos,
                     "paginas_sem_serventia": erros, "pessoas": len(colhido)}
