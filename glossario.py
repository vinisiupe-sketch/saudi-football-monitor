"""
O glossário oficial de jogadores. A AUTORIDADE, e não mais um palpite.

O QUE MUDOU AQUI (14/09/26)
    Durante meses este app respondeu "quem é este nome?" com dedução: índice
    de nomes, semelhança de texto, busca escopada ao clube. Cada uma dessas
    regras nasceu de um erro concreto — Rajkovic e Bergwijn separados, três
    Roger Fernandes, dois Kalidou Koulibaly, o Hamdallah que a canetinha não
    consertava — e cada conserto foi uma camada a mais de adivinhação em cima
    da anterior.

    O Vini montou o glossário: 601 jogadores ancorados na SPL, com 595
    cruzados na API-Football, 595 no Transfermarkt e 460 nomes de PDF, além
    das grafias em árabe e em latim. Ele audita, revisa e corrige à mão.

    Então a pergunta deixa de ser deduzida e passa a ser CONSULTADA. É uma
    inversão, não um acréscimo: onde o glossário responde, nenhuma heurística
    roda — nem como desempate, nem como confirmação.

O LIMITE, QUE É DELE E NÃO MEU
    O glossário cobre a Saudi Pro League. Uma notícia de transferência fala de
    jogador do Liverpool, e esse não está aqui nem deveria estar. Para quem
    NÃO é da liga, o caminho antigo continua — foi a decisão do Vini quando
    perguntei. Dentro da liga, o glossário manda sozinho.

POR QUE ESTE MÓDULO EXISTE, EM VEZ DE CONSULTAS ESPALHADAS
    Porque já aconteceu o contrário e custou caro. A regra de identidade
    estava copiada em três telas, as cópias divergiram, e o Vini viu dois
    Koulibaly com o nome escrito IGUAL — um reconhecido e o outro não. Aqui há
    uma porta só. Se duas telas discordarem, é porque alguém abriu uma
    segunda, e isso se vê no `grep`.

SOBRE O CACHE
    São ~600 jogadores e alguns milhares de grafias: cabe folgado na memória e
    não vale uma consulta ao banco por nome resolvido, que numa página de
    lesões seriam centenas. O prazo é curto e `recarregar()` derruba na hora —
    é chamado por toda escrita do laboratório, para uma correção do Vini valer
    no próximo clique e não no próximo minuto.
"""
import re
import threading
import time

PRAZO_SEG = 120

_TRAVA = threading.Lock()
_CACHE = {"quando": 0.0, "dados": None}

# Ordem de preferência quando o ajuste está em "melhor disponível".
# A SPL vem primeiro porque é ela que ancora o glossário: é a base em que o
# jogador existe com certeza, e da qual o Vini partiu para cruzar as outras.
ORDEM_PADRAO = ("spl", "api_football", "transfermarkt")


def _e_arabe(texto: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", texto or ""))


def _chave(nome: str) -> str:
    """A forma de comparação, igual à que o laboratório grava.

    Chamo o mesmo normalizador do glossary.py de propósito. Escrever outro
    aqui faria a busca comparar uma coisa contra outra parecida — e o erro
    apareceria só em nomes com acento ou com o artigo "Al", que são metade
    desta liga.
    """
    import glossary
    if _e_arabe(nome):
        return glossary.chave_arabe(nome or "")
    return glossary.chave_latina(nome or "")


def _montar(linhas_jogador, linhas_nome) -> dict:
    por_id, por_spl, por_af, por_tm = {}, {}, {}, {}
    for j in linhas_jogador:
        d = dict(j)
        d["grafias"] = []
        por_id[d["id"]] = d
        if d.get("spl_id"):
            por_spl[str(d["spl_id"])] = d
        if d.get("af_id"):
            por_af[int(d["af_id"])] = d
        if d.get("tm_id"):
            por_tm[str(d["tm_id"])] = d

    # UMA CHAVE PODE CAIR EM MAIS DE UMA PESSOA, e por isso o índice guarda
    # lista. Homônimo existe (dois "Mohammed Al Otaibi" na mesma liga), e
    # tratar a chave como única faria o segundo sobrescrever o primeiro em
    # silêncio — o pior desfecho possível, porque o app ficaria confiante.
    por_chave: dict = {}
    for n in linhas_nome:
        dono = por_id.get(n["jogador_id"])
        if not dono:
            continue
        dono["grafias"].append(dict(n))
        chave = (n.get("nome_normalizado") or "").strip() or _chave(n.get("nome"))
        if not chave:
            continue
        por_chave.setdefault(chave, [])
        if dono["id"] not in [x["id"] for x in por_chave[chave]]:
            por_chave[chave].append(dono)

    # O nome principal e o árabe da própria ficha também valem como grafia:
    # eles vêm da SPL e são o que a tela mostra.
    for d in por_id.values():
        for campo in ("nome_principal", "nome_curto", "nome_ar"):
            chave = _chave(d.get(campo) or "")
            if not chave:
                continue
            por_chave.setdefault(chave, [])
            if d["id"] not in [x["id"] for x in por_chave[chave]]:
                por_chave[chave].append(d)

    return {"por_id": por_id, "por_spl": por_spl, "por_af": por_af,
            "por_tm": por_tm, "por_chave": por_chave}


def _vazio() -> dict:
    return {"por_id": {}, "por_spl": {}, "por_af": {}, "por_tm": {},
            "por_chave": {}}


def carregar(forcar: bool = False) -> dict:
    agora = time.time()
    with _TRAVA:
        fresco = (_CACHE["dados"] is not None
                  and (agora - _CACHE["quando"]) < PRAZO_SEG)
        if fresco and not forcar:
            return _CACHE["dados"]
    try:
        import database
        jogadores, nomes = database.glossario_completo()
        dados = _montar(jogadores, nomes)
    except Exception as e:
        # SEM GLOSSÁRIO EU NÃO INVENTO UM. Devolver vazio faz cada tela cair
        # no caminho de quem não é da liga, que é o comportamento antigo —
        # pior, e conhecido. Fingir um glossário meio carregado seria pior
        # ainda: ele responderia errado com ar de autoridade.
        print(f"⚠️ glossário: {type(e).__name__}: {e}", flush=True)
        return _vazio()
    with _TRAVA:
        _CACHE["dados"] = dados
        _CACHE["quando"] = agora
    return dados


def recarregar() -> None:
    """Derruba o cache. Toda escrita no laboratório chama isto."""
    with _TRAVA:
        _CACHE["dados"] = None
        _CACHE["quando"] = 0.0


def esta_carregado() -> bool:
    return bool((carregar().get("por_id") or {}))


def quantos() -> int:
    return len(carregar().get("por_id") or {})


# ── A PERGUNTA CENTRAL ──────────────────────────────────────────────────────

def identidade(nome: str, clube: str = "") -> dict:
    """Quem é este nome, segundo o glossário. {} quando ele não sabe.

    NÃO TENTA NADA ALÉM DA CONSULTA. Sem semelhança de texto, sem prefixo, sem
    "quase igual". Um glossário que adivinha é uma heurística com nome melhor,
    e foi de heurística que a gente saiu.

    O clube só entra para DESEMPATAR homônimo — e desempatar é diferente de
    procurar: se a chave cai em duas pessoas e nenhuma é do clube informado, a
    resposta continua sendo "não sei", e não "vou de uma das duas".
    """
    chave = _chave(nome)
    if not chave:
        return {}
    achados = (carregar().get("por_chave") or {}).get(chave) or []
    if len(achados) == 1:
        return achados[0]
    if not achados or not clube:
        return {}
    import glossary
    alvo = (glossary.padronizar_clube(clube) or clube or "").lower()
    do_clube = [j for j in achados
                if (glossary.padronizar_clube(j.get("clube") or "")
                    or j.get("clube") or "").lower() == alvo]
    return do_clube[0] if len(do_clube) == 1 else {}


def por_af_id(af_id) -> dict:
    try:
        return (carregar().get("por_af") or {}).get(int(af_id)) or {}
    except (TypeError, ValueError):
        return {}


def por_tm_id(tm_id) -> dict:
    return (carregar().get("por_tm") or {}).get(str(tm_id or "")) or {}


def por_spl_id(spl_id) -> dict:
    return (carregar().get("por_spl") or {}).get(str(spl_id or "")) or {}


def jogadores_no_texto(*textos) -> list[dict]:
    """Quais jogadores do glossário são citados nestes textos.

    Varre por GRAFIA CONHECIDA, com fronteira de palavra, e é isso que separa
    esta busca do índice antigo: ela não exige duas palavras nem tenta montar
    nome nenhum — ou a grafia está no glossário, escrita daquele jeito, ou não
    está. "Hamdallah" sozinho encontra, porque o Vini cadastrou "Hamdallah"; e
    encontra a pessoa certa, porque foi ele quem disse de quem é.

    Chave ambígua (homônimo) fica de fora: aqui não há clube para desempatar,
    e citar o jogador errado num post é pior do que não citar nenhum.
    """
    dados = carregar()
    por_chave = dados.get("por_chave") or {}
    if not por_chave:
        return []

    achados, vistos = [], set()
    for texto in textos:
        if not texto:
            continue
        import glossary
        # Duas varreduras porque as chaves são de dois alfabetos e cada uma
        # tem o seu normalizador. Comparar árabe com a chave latina não acha
        # nada — e não acharia com erro, acharia com silêncio.
        for normalizar in (glossary.chave_latina, glossary.chave_arabe):
            try:
                alvo = " " + normalizar(texto) + " "
            except Exception:
                continue
            for chave, donos in por_chave.items():
                if len(donos) != 1 or len(chave) < 3:
                    continue
                if donos[0]["id"] in vistos:
                    continue
                if f" {chave} " in alvo:
                    vistos.add(donos[0]["id"])
                    achados.append(donos[0])
    return achados


# ── O GLOSSÁRIO COMO PROFESSOR DA IA ────────────────────────────────────────

def licao_para_a_ia(*textos, teto: int = 40) -> str:
    """O de-para dos jogadores citados NESTE texto, para entrar no prompt.

    POR QUE ANTES DA TRADUÇÃO, E NÃO DEPOIS
        Hoje a IA translitera o árabe e o app tenta reconhecer o resultado.
        É a ordem errada, e o Vini apontou: o glossário é anterior à
        transliteração. Se eu já sei que هاني Hamdallah é "Abderrazak
        Hamdallah", pedir à IA que adivinhe e depois consertar é criar um erro
        para corrigir em seguida — e as correções nunca pegam todas.

        Aqui o texto árabe BRUTO é varrido antes de a IA ver qualquer coisa.
        Os jogadores encontrados entram no prompt já resolvidos, com a ordem
        de usar exatamente aquela grafia.

    POR QUE SÓ OS CITADOS, E NÃO OS 601
        Mandar o glossário inteiro em toda chamada custaria caro e afogaria a
        instrução no meio de seiscentas linhas que não têm a ver com o texto.
        O que vai são os que aparecem — em geral um ou dois.
    """
    citados = jogadores_no_texto(*textos)[:teto]
    if not citados:
        return ""
    linhas = []
    for j in citados:
        arabes = [g["nome"] for g in (j.get("grafias") or [])
                  if g.get("idioma") == "ar" and g.get("nome")]
        if j.get("nome_ar"):
            arabes.insert(0, j["nome_ar"])
        vistos, limpos = set(), []
        for a in arabes:
            if a not in vistos:
                vistos.add(a)
                limpos.append(a)
        de = " / ".join(limpos[:3])
        linhas.append(f"- {de} = {j['nome_principal']}" if de
                      else f"- {j['nome_principal']}")
    return (
        "\nJOGADORES JÁ IDENTIFICADOS NESTE TEXTO — use EXATAMENTE estas "
        "grafias em português e NÃO translitere estes nomes por conta "
        "própria:\n" + "\n".join(linhas) + "\n"
    )


# ── A FICHA, COM A FONTE QUE O VINI ESCOLHEU ────────────────────────────────

def _fonte_escolhida(campo: str) -> str:
    try:
        import database
        return database.valor_de_ajuste(f"glossario_fonte_{campo}") or "melhor disponível"
    except Exception:
        return "melhor disponível"


# De onde sai cada campo em cada fonte. O mapa é explícito porque as três
# bases não guardam as mesmas coisas: a API-Football que a gente tem cadastrada
# não traz posição, e o Transfermarkt escreve nacionalidade no plural (um
# jogador pode ter duas). Onde não há dado, o valor é None e a busca segue.
_DE_ONDE = {
    "foto":          {"spl": "foto", "api_football": "af_foto",
                      "transfermarkt": "tm_foto"},
    "posicao":       {"spl": "posicao", "api_football": None,
                      "transfermarkt": "tm_posicao"},
    "nacionalidade": {"spl": "nacionalidade", "api_football": "af_nacionalidade",
                      "transfermarkt": "tm_nacionalidade"},
}


def _endereco_de_foto(valor: str) -> str:
    """O endereço COMPLETO da foto, venha ela de qual fonte vier.

    POR QUE ISTO PRECISOU EXISTIR (14/09/26)
        O Vini escolheu a foto da SPL nas configurações e a guia de Elencos
        continuou mostrando a do Transfermarkt. Eu já tinha ligado a guia ao
        glossário e conferido que ela obedecia — e obedecia mesmo: a foto da
        SPL estava sendo escolhida e entregue.

        Só que a SPL guarda CAMINHO ("players/123.png"), não endereço. O
        navegador procurava esse caminho no servidor do app, não achava, e
        caía na foto reserva do Transfermarkt — que eu mesmo pus ali para o
        card não ficar com um buraco. A rede de segurança escondeu o defeito
        e produziu exatamente o sintoma de "não obedeceu".

        Outras telas já faziam esta conversão cada uma por conta. Agora ela
        mora aqui, que é a porta única: quem pede foto ao glossário recebe
        algo que o navegador consegue abrir, e ninguém mais precisa saber que
        a liga entrega caminho e o Transfermarkt entrega URL.
    """
    v = (valor or "").strip()
    if not v or v.startswith(("http://", "https://", "data:", "/")):
        return v
    try:
        import liga_spl
        return liga_spl.MEDIA + v
    except Exception:
        return v


def _do_campo(j: dict, campo: str, fonte: str):
    """O valor deste campo nesta fonte, ou "" se ela não guarda esse dado."""
    coluna = (_DE_ONDE.get(campo) or {}).get(fonte)
    if not coluna:
        return ""
    valor = j.get(coluna) or ""
    return _endereco_de_foto(valor) if campo == "foto" else valor


def foto_da_fonte(j: dict, fonte: str) -> str:
    """A foto de UMA fonte específica, ignorando a configuração de Ajustes.

    POR QUE ISTO EXISTE, se já existe `ficha()`
        A configuração de fonte é para a TELA, onde o Vini compara as três
        bases e escolhe qual prefere ver. A arte que ele baixa para publicar
        tem outra exigência: a foto da SPL é a única com fundo recortado e
        enquadramento igual para todo mundo, e é isso que faz uma medida fixa
        de foto servir para as 601 fichas. Se a arte obedecesse a configuração,
        trocar a preferência na tela quebraria o enquadramento do arquivo.

        Continua sendo a mesma porta: quem pede recebe um endereço que o
        navegador abre, e ninguém de fora precisa saber que a liga guarda
        caminho e o Transfermarkt guarda URL.
    """
    return _do_campo(j or {}, "foto", fonte) or ""


def ficha(j: dict) -> dict:
    """A ficha do jogador com foto, posição e nacionalidade já resolvidas.

    A escolha de qual tabela manda em cada campo é do Vini, na guia de
    Ajustes, e vale para as 601 de uma vez. "melhor disponível" tenta na
    ordem SPL → API-Football → Transfermarkt; as outras opções são estritas, e
    campo vazio fica vazio. Vazio é honesto: dado de outra tabela aparecendo
    no lugar seria mentira calada, e é justamente o tipo de mentira que a
    gente passou semanas caçando.
    """
    if not j:
        return {}
    saida = dict(j)
    for campo in ("foto", "posicao", "nacionalidade"):
        escolha = _fonte_escolhida(campo)
        if escolha == "melhor disponível":
            valor = ""
            for fonte in ORDEM_PADRAO:
                valor = _do_campo(j, campo, fonte) or ""
                if valor:
                    break
        else:
            valor = _do_campo(j, campo, escolha) or ""
        saida[campo] = valor
        saida[f"{campo}_fonte"] = escolha
    return saida
