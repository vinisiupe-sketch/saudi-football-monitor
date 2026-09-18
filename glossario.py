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


def _chaves(nome: str) -> list:
    """TODAS as formas pelas quais este nome pode ser encontrado.

    A primeira é a de sempre. A segunda só existe em nome árabe composto, e só
    aparece quando ela difere da primeira.

    POR QUE DUAS CHAVES, E NÃO UMA MELHOR (18/09/26)
        O Vini mandou uma notícia sobre o Hayder Abdulkareem, do Al Nassr, que
        saiu no app como "Haidar Abd al-Karim" mesmo com o jogador mapeado. O
        glossário tem a grafia da SPL (حيدر عبدالكريم, junto) e o tweet escreve
        حيدر عبد الكريم, separado. A varredura compara palavra por palavra, não
        achou, e a IA transliterou por conta própria.

        A tentação era "melhorar" a `chave_arabe`. Não dá: ela é a chave de
        comparação do app inteiro, inclusive dos CLUBES, onde o artigo é
        justamente o que separa النصر (o time) de نصر (a palavra "vitória").
        Mexer nela para consertar nome de pessoa quebraria o reconhecimento de
        clube — e do jeito mais caro, achando clube em toda frase que fala em
        vitória.

        Então a chave nova entra COMO ÍNDICE A MAIS. A antiga continua
        respondendo tudo que respondia; a nova só acrescenta portas para a
        mesma pessoa.

    O QUE ISSO CUSTA, DITO POR EXTENSO
        Mais chaves é mais chance de duas pessoas caírem na mesma. Isso não faz
        o app errar: `identidade()` devolve {} quando a chave cai em mais de um,
        e `jogadores_no_texto` pula chave ambígua. O custo é virar "não sei"
        onde antes era uma resposta — e é por isso que existe o
        /api/diag/nomes-arabes, que conta exatamente quantos casos assim a
        regra cria no glossário DELE antes de a gente confiar nela.
    """
    import glossary
    principal = _chave(nome)
    if not principal:
        return []
    if not _e_arabe(nome):
        return [principal]
    composta = glossary.chave_arabe_composta(nome or "")
    return [principal, composta] if composta and composta != principal \
        else [principal]


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
    # A FAMÍLIA DE CADA GRAFIA: qual chave composta ela produz. Serve para o
    # passo final, e o porquê está explicado lá embaixo.
    pares: list = []

    def _guardar(dono, nome_cru, gravada=""):
        # A chave gravada pelo laboratório entra porque é ela que o banco usa
        # para procurar. As outras saem do nome CRU: o banco guardou uma
        # normalização só, e a composta nasceu depois dele.
        formas = _chaves(nome_cru or "")
        for chave in ([gravada.strip()] if gravada else []) + formas:
            if not chave:
                continue
            por_chave.setdefault(chave, [])
            if dono["id"] not in [x["id"] for x in por_chave[chave]]:
                por_chave[chave].append(dono)
            # A família é sempre a ÚLTIMA forma: `_chaves` devolve a composta
            # em segundo quando ela existe, e a principal sozinha quando não.
            pares.append((chave, formas[-1] if formas else chave, dono))

    for n in linhas_nome:
        dono = por_id.get(n["jogador_id"])
        if not dono:
            continue
        dono["grafias"].append(dict(n))
        _guardar(dono, n.get("nome") or "",
                 (n.get("nome_normalizado") or ""))

    # O nome principal e o árabe da própria ficha também valem como grafia:
    # eles vêm da SPL e são o que a tela mostra.
    for d in por_id.values():
        for campo in ("nome_principal", "nome_curto", "nome_ar"):
            if d.get(campo):
                _guardar(d, d[campo])

    # ── O PASSO QUE FAZ A AMBIGUIDADE APARECER ─────────────────────────────
    #
    # Sem ele a regra nova cria um palpite escondido, e o teste pegou isso.
    #
    # Imagine duas pessoas: uma escrita حيدر عبدالكريم (junto) e outra حيدر عبد
    # الكريم (separado). Elas têm o mesmo nome — o espaço não distingue pessoa
    # nenhuma. Mas as chaves PRINCIPAIS delas são diferentes, então uma notícia
    # escrita separado casaria só com a segunda, e o app citaria aquela com
    # toda a confiança do mundo.
    #
    # Aqui eu espalho: quem compartilha a chave composta compartilha TODAS as
    # chaves do grupo. Assim a dúvida fica visível nas duas pontas, e as duas
    # respondem "não sei" — que é o que `identidade()` e `jogadores_no_texto`
    # já fazem com chave de mais de um dono.
    #
    # Note que isto não inventa homônimo: se ninguém mais cai na mesma família,
    # nada muda. Só faz o app enxergar a colisão que a união criou.
    familias: dict = {}
    for _, familia, dono in pares:
        familias.setdefault(familia, {})[dono["id"]] = dono
    for chave, familia, _ in pares:
        parentes = familias.get(familia) or {}
        if len(parentes) < 2:
            continue
        atuais = {x["id"] for x in por_chave.get(chave) or []}
        for pid, pessoa in parentes.items():
            if pid not in atuais:
                por_chave.setdefault(chave, []).append(pessoa)

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
    # AS DUAS FORMAS, e não só a principal.
    #
    # O índice guarda o nome do Hayder pela grafia da SPL (junto). Quem chega
    # aqui com a grafia da imprensa (separado) normaliza para outra coisa, e a
    # consulta não achava nada — o mesmo silêncio que fez a notícia sair com
    # transliteração inventada. Perguntar pelas duas é o que liga as pontas.
    por_chave = carregar().get("por_chave") or {}
    achados, vistos = [], set()
    for chave in _chaves(nome):
        for pessoa in por_chave.get(chave) or []:
            if pessoa["id"] not in vistos:
                vistos.add(pessoa["id"])
                achados.append(pessoa)
    if not achados:
        return {}
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
        # Três varreduras. Duas porque as chaves são de dois alfabetos e cada
        # uma tem o seu normalizador — comparar árabe com a chave latina não
        # acha nada, e não acharia com erro, acharia com silêncio.
        #
        # A TERCEIRA é a composta, e ela precisa rodar sobre o TEXTO, não só
        # sobre as chaves. "عبد الكريم" no tweet só vira "عبدالكريم" se eu unir
        # as duas metades dos DOIS lados; unir só no índice deixaria a chave
        # nova procurando por uma palavra que o texto nunca escreve junto.
        for normalizar in (glossary.chave_latina, glossary.chave_arabe,
                           glossary.chave_arabe_composta):
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
    # O NOME TAMBÉM É ESCOLHA DELE, e isto entrou em 16/09/26.
    #
    # Eu tinha decidido que o glossário mandava no nome e pronto, e chamei de
    # "errado" o nome que a lista mostrava. Ele corrigiu:
    #
    #     "Mohammed Meité não é nome errado, tá tão certo quanto Kader Meité,
    #      mas é só como ele aparece em outras fichas. Deveria dar pra escolher
    #      sim, já que no glossário tem diferentes fontes. Eu gosto da
    #      padronização do transfermkt."
    #
    # Ele tem razão e eu não tinha. Não é erro contra acerto: são grafias, e
    # cada base tem a sua. O que faltava era PADRONIZAR — escolher uma e usá-la
    # em todo lugar. Isso é decisão editorial, e decisão editorial é dele.
    "nome":          {"spl": "nome_principal", "api_football": "af_nome",
                      "transfermarkt": "tm_nome"},
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
    for campo in ("nome", "foto", "posicao", "nacionalidade"):
        escolha = _fonte_escolhida(campo)
        if escolha == "melhor disponível":
            valor = ""
            for fonte in ORDEM_PADRAO:
                valor = _do_campo(j, campo, fonte) or ""
                if valor:
                    break
        else:
            valor = _do_campo(j, campo, escolha) or ""

        # O NOME É A ÚNICA EXCEÇÃO À REGRA DE "VAZIO É HONESTO".
        #
        # Nos outros campos, vazio é resposta: quer dizer "a fonte que você
        # escolheu não tem isto", e preencher com outra seria desfazer a
        # escolha dele em silêncio. Um card sem foto ainda funciona.
        #
        # Um card SEM NOME não funciona. Ele deixa de ser um card e vira uma
        # linha em branco que não dá para clicar nem procurar. Então aqui o
        # vazio cai no `nome_principal`, que é a âncora do glossário e nunca
        # é nulo — a escolha dele continua valendo em todo mundo que tem o
        # nome naquela fonte, e ninguém desaparece da tela por causa dela.
        if campo == "nome" and not valor:
            valor = j.get("nome_principal") or ""

        saida[campo] = valor
        saida[f"{campo}_fonte"] = escolha
    return saida
