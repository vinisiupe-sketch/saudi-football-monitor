"""
A prévia de um jogo, para você usar no ar.

PARA QUEM É
    Para o comentarista, não para o público. Isso muda tudo: o texto não
    precisa explicar quem é Al Hilal, precisa te dar o número que você não
    lembra de cabeça no minuto 63.

A REGRA QUE MANDA AQUI
    O modelo escreve SÓ a partir do que este módulo entrega. Nada de
    conhecimento próprio, nada de "sabe-se que". Um modelo escrevendo prévia
    de futebol inventa estatística com uma naturalidade assustadora — sai
    "quinto jogo sem vencer fora de casa" com a mesma confiança de um número
    que veio da tabela.

    Por isso, depois de escrever, cada número do texto é procurado nos dados
    de entrada. O que não for encontrado vira uma lista visível na tela. Não
    apago o relatório por causa disso: um número não conferido, mostrado como
    não conferido, é útil; a mesma frase sem aviso é uma armadilha.

A ESCALAÇÃO
    A liga só publica a oficial, e só quando ela sai. Antes disso monto uma
    PROVÁVEL contando quem começou nas últimas rodadas — e ela sai carimbada
    como dedução, com quantos jogos cada um foi titular ao lado. Quando a
    oficial aparece, substitui.
"""
import json
import re
import unicodedata

RODADAS_PARA_O_PROVAVEL = 5


# ── Escalação ───────────────────────────────────────────────────────────────
def _nome_do_jogador(j: dict) -> str:
    return (j.get("shortName") or j.get("displayName")
            or " ".join(x for x in (j.get("mediaFirstName"),
                                    j.get("mediaLastName")) if x) or "").strip()


def escalacao_oficial(escala: dict, lado: str) -> dict:
    """Os onze e o banco, como a liga publicou."""
    time = (escala or {}).get(lado) or {}
    titulares = []
    for j in (time.get("fielded") or []):
        titulares.append({
            "nome": _nome_do_jogador(j),
            "camisa": j.get("bibNumber") or "",
            "posicao": j.get("roleLabel") or "",
            "capitao": bool(j.get("isCaptain")),
            "pendurado": j.get("isOneBookingAway"),
        })
    return {"formacao": time.get("tacticalFormation") or "",
            "titulares": titulares,
            "banco": [_nome_do_jogador(j) for j in (time.get("benched") or [])],
            "origem": "oficial"}


def escalacao_provavel(jogos_do_time: list[dict], escalas: dict, time_id: str) -> dict:
    """Quem mais começou nas últimas rodadas, com a conta à mostra.

    `escalas` é {matchId: resposta do endpoint lineups}. Conto aparições como
    titular e devolvo os onze mais frequentes, cada um com em quantos dos
    jogos olhados ele começou. Esse número não é enfeite: "titular em 5 de 5"
    e "titular em 2 de 5" são graus de certeza muito diferentes, e quem vai
    falar no ar precisa saber de qual dos dois se trata.

    Empate desempata por quem jogou mais recentemente — um titular que voltou
    de lesão na última rodada vale mais que um reserva com o mesmo total.
    """
    contagem: dict[str, dict] = {}
    olhados = 0
    formacao = ""
    for i, j in enumerate(jogos_do_time):
        escala = escalas.get(j.get("matchId"))
        if not escala:
            continue
        lado = "home" if ((escala.get("home") or {}).get("teamId") == time_id) else "away"
        time = escala.get(lado) or {}
        if (time.get("teamId") or "") != time_id:
            continue
        fielded = time.get("fielded") or []
        if not fielded:
            continue
        olhados += 1
        if not formacao:
            formacao = time.get("tacticalFormation") or ""
        for p in fielded:
            nome = _nome_do_jogador(p)
            if not nome:
                continue
            reg = contagem.setdefault(nome, {
                "nome": nome, "vezes": 0, "ultima": 10**6,
                "camisa": p.get("bibNumber") or "",
                "posicao": p.get("roleLabel") or "",
            })
            reg["vezes"] += 1
            reg["ultima"] = min(reg["ultima"], i)
    ordenados = sorted(contagem.values(),
                       key=lambda r: (-r["vezes"], r["ultima"], r["nome"]))
    return {"formacao": formacao,
            "titulares": ordenados[:11],
            "banco": [],
            "jogos_olhados": olhados,
            "origem": "provavel"}


# ── Montagem dos fatos ──────────────────────────────────────────────────────
def _resumo_da_tabela(linha: dict) -> dict:
    """Só o que interessa no ar, com nomes em português."""
    if not linha:
        return {}
    return {
        "posicao": linha.get("rank"),
        "pontos": linha.get("points"),
        "jogos": linha.get("matches-played"),
        "vitorias": linha.get("win"),
        "empates": linha.get("draw"),
        "derrotas": linha.get("lose"),
        "gols_pro": linha.get("goals-for"),
        "gols_contra": linha.get("goals-against"),
        "saldo": linha.get("goal-difference"),
        "forma": linha.get("forma") or [],
    }


def _resumo_do_confronto(previa: dict, casa: str, fora: str) -> dict:
    h2h = (previa or {}).get("headToHead") or {}
    ultimos = []
    for m in ((previa or {}).get("lastMatches") or [])[:6]:
        ultimos.append({
            "quando": (m.get("matchDateLocal") or m.get("matchDateUtc") or "")[:10],
            "casa": ((m.get("home") or {}).get("shortName") or ""),
            "fora": ((m.get("away") or {}).get("shortName") or ""),
            "placar": f"{m.get('providerHomeScore')}-{m.get('providerAwayScore')}",
            "competicao": ((m.get("competition") or {}).get("name") or ""),
        })
    return {
        "vitorias_de": {h2h.get("winsHomeLabel") or casa: h2h.get("winsHome"),
                        h2h.get("winsAwayLabel") or fora: h2h.get("winsAway")},
        "empates": h2h.get("draws"),
        "ultimos_encontros": ultimos,
    }


def montar_fatos(jogo: dict, tabela_casa: dict, tabela_fora: dict,
                 previa_liga: dict, escala_casa: dict, escala_fora: dict,
                 arbitragem: list, lesoes: list, noticias: list,
                 transferencias: list) -> dict:
    """Tudo que o modelo vai poder usar, e nada além disso.

    Chaves em português de propósito: o modelo escreve em português, e
    misturar `goals-for` com "gols marcados" no mesmo prompt é um convite a
    ele traduzir errado ou inventar um campo que não existe.
    """
    forma_previa = previa_liga or {}
    return {
        "jogo": {
            "casa": jogo.get("casa"), "fora": jogo.get("fora"),
            "quando": jogo.get("quando"), "competicao": jogo.get("competicao"),
            "rodada": jogo.get("rodada") or "",
            "estadio": jogo.get("estadio") or "",
            "transmissao": jogo.get("canais") or [],
        },
        "tabela": {jogo.get("casa"): _resumo_da_tabela(tabela_casa),
                   jogo.get("fora"): _resumo_da_tabela(tabela_fora)},
        "forma_recente": {
            jogo.get("casa"): ((forma_previa.get("home") or {}).get("form") or []),
            jogo.get("fora"): ((forma_previa.get("away") or {}).get("form") or []),
        },
        "confronto_direto": _resumo_do_confronto(forma_previa, jogo.get("casa"),
                                                 jogo.get("fora")),
        "escalacao": {jogo.get("casa"): escala_casa, jogo.get("fora"): escala_fora},
        "arbitragem": arbitragem or [],
        "desfalques": lesoes or [],
        "noticias_da_semana": noticias or [],
        "movimentacao": transferencias or [],
    }


# ── Conferência dos números ─────────────────────────────────────────────────
# Números que aparecem em texto sem virem de dado nenhum: "os 11", "no
# primeiro tempo", "os 90 minutos". Deixo passar porque recusá-los encheria a
# lista de ruído e faria você parar de olhar — que é o pior desfecho possível
# para um aviso.
NUMEROS_DE_FUTEBOL = {"1", "2", "3", "4", "5", "11", "45", "90", "0"}
_SO_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


def _numeros_de(valor) -> tuple[set, set]:
    """Devolve (todos, contáveis).

    A separação não é preciosismo. "2026-08-28T18:00" solta 2026, 08, 28, 18 e
    00 no monte. Se esses pedaços de data entrarem na soma, 9 + 18 = 27 vira
    número "conferido", e a frase inventada "há 27 jogos invicto" passa batido.
    Foi exatamente o que aconteceu na primeira versão deste conferidor.

    Então: pedaço de texto (data, formação 4-3-3, "titular em 5 de 5") é aceito
    LITERALMENTE, mas não faz conta. Só número que veio como número soma.
    """
    todos, contaveis = set(), set()

    def andar(v):
        if isinstance(v, dict):
            for k, x in v.items():
                andar(k)
                andar(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                andar(x)
        elif isinstance(v, bool):
            pass
        elif isinstance(v, (int, float)):
            todos.add(str(v))
            contaveis.add(str(v))
            if isinstance(v, float) and v.is_integer():
                todos.add(str(int(v)))
                contaveis.add(str(int(v)))
        elif isinstance(v, str):
            for m in _SO_NUMERO.findall(v):
                todos.add(m.replace(",", "."))
                todos.add(m.lstrip("0") or "0")
    andar(valor)
    return todos, contaveis


def conferir_numeros(texto: str, fatos: dict) -> list[str]:
    """Os números do texto que NÃO existem nos dados de entrada.

    Não é prova de erro — o modelo pode ter somado dois números certos. Mas é
    o lugar exato para olhar antes de falar isso no ar.
    """
    todos, contaveis = _numeros_de(fatos)
    permitidos = todos | NUMEROS_DE_FUTEBOL
    # Somar dois números dos dados é operação legítima (gols do confronto,
    # total de pontos dos dois). Aceito, para o aviso não virar ruído — mas só
    # entre números que eram números na origem.
    inteiros = [int(n) for n in contaveis if n.isdigit() and len(n) <= 3]
    for a in inteiros:
        for b in inteiros:
            permitidos.add(str(a + b))
            if a >= b:
                permitidos.add(str(a - b))
    suspeitos = []
    for m in _SO_NUMERO.findall(texto or ""):
        n = m.replace(",", ".")
        if n in permitidos or (n.lstrip("0") or "0") in permitidos:
            continue
        if n not in suspeitos:
            suspeitos.append(n)
    return suspeitos


# ── O pedido ao modelo ──────────────────────────────────────────────────────
SISTEMA = """Você prepara um comentarista brasileiro para narrar/comentar uma \
partida do futebol saudita AO VIVO.

REGRA ABSOLUTA: use SOMENTE os dados do JSON que vem na mensagem. Você não \
sabe nada sobre esses times além do que está ali. Não complete lacuna com \
conhecimento próprio, não estime, não arredonde para um número "mais bonito", \
não escreva sequência do tipo "quinto jogo sem vencer" a menos que ela esteja \
literalmente nos dados. Se um dado não estiver no JSON, simplesmente não fale \
dele — a ausência é aceitável, a invenção não é.

QUEM LÊ: um comentarista com o jogo prestes a começar, no celular. Ele conhece \
futebol. Não explique o óbvio, não faça introdução, não escreva conclusão.

FORMATO: markdown, com estas seções, nesta ordem, e só as que tiverem \
conteúdo real:

## Antes de entrar no ar
Onde os dois estão na tabela, o que está em jogo, como chegaram. 3 a 5 linhas.

## Os onze
Uma linha por time: formação e os nomes. Se a escalação for provável, diga \
isso na primeira palavra da linha e mantenha o "titular em X de Y" ao lado dos \
nomes em que esse dado existir.

## Para citar
5 ou 6 fatos prontos para falar, cada um com o número junto. Um por linha, \
começando com hífen. Prefira o que surpreende ao que é previsível.

## Radar
O que pode acontecer neste jogo e vale notar na hora: marcas próximas, \
jogador pendurado, sequência que pode quebrar. Só o que os dados sustentam.

## A semana
O que saiu na imprensa sobre os dois clubes, com a fonte. Só do que estiver \
no JSON.

## Atenção
Arbitragem do jogo e desfalques. Curto.

TOM: direto, sem adjetivo de encher. Frase curta. Nada de "é importante \
ressaltar", "vale lembrar", "sem dúvida"."""


def montar_pedido(fatos: dict) -> str:
    return ("Prepare a prévia com estes dados, e apenas com eles:\n\n"
            + json.dumps(fatos, ensure_ascii=False, indent=1, default=str))


def sem_dados_suficientes(fatos: dict) -> str:
    """Diz por que não dá para escrever, quando não dá.

    Gastar uma chamada de modelo com JSON vazio produz um texto bonito e
    inteiramente inventado — que é o pior resultado possível aqui.
    """
    tabela = fatos.get("tabela") or {}
    tem_tabela = any(v for v in tabela.values())
    tem_forma = any(fatos.get("forma_recente", {}).values())
    if not tem_tabela and not tem_forma:
        return ("não achei este jogo na base da liga — sem tabela nem forma "
                "recente não há prévia possível")
    return ""
