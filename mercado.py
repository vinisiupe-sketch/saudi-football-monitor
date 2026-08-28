"""
O passo a passo de uma negociação, montado a partir das notícias.

A IDEIA, QUE É DO VINI
    A guia de mercado hoje é uma lista de notícias soltas. Ela vira uma lista
    de NEGOCIAÇÕES: um card por jogador+destino, com rosto, escudos, e a
    linha do tempo do que foi saindo — data, status e veículo.

    O que isso resolve para mim é maior do que parece. Eu vinha caçando nome
    de jogador dentro de texto corrido e perdendo 'تمبكتي يغيب', porque me
    recuso a aceitar sobrenome solto com 573 jogadores parecidos. Aqui eu
    paro de caçar: o modelo lê a notícia e me entrega o nome limpo. Só então
    eu procuro esse nome na tabela.

    E o card falha para o lado certo: notícia que eu não consigo ligar
    simplesmente não entra. Ela não cria um card errado.

O QUE A LINHA DO TEMPO NÃO FAZ
    Não corrige ninguém. Uma negociação vai 'Sondagem → Negociação → Acerto
    → Melou', volta atrás, e duas fontes discordam no mesmo dia. Guardo todos
    os passos com data e veículo; o card mostra o mais recente e não apaga o
    resto. Se um diz Acerto e outro diz Melou, os dois ficam lá — isso é
    matéria-prima de quem narra, não sujeira para limpar.

POR QUE HAIKU
    Isto não é tradução, é extração de campo com vocabulário fechado, que o
    próprio Vini já tinha escrito no gerador de post. O app já usa Haiku para
    a triagem de categoria pela mesma razão.
"""
import json

# O `processor` (e o `httpx`, e o banco por tabela) só é importado DENTRO da
# função que fala com o modelo. As funções puras deste arquivo — conferir o
# que voltou, montar a chave da negociação, escolher entre homônimos — são as
# que mais precisam de teste, e não faz sentido exigir a pilha inteira de IA
# instalada para poder testá-las.

# O vocabulário é o do Vini, copiado do gerador de post — não um novo que eu
# tenha inventado. Se existissem dois, a guia e o post começariam a dizer
# coisas diferentes sobre a mesma negociação.
STATUS = ("Sondagem", "Interesse", "Consulta", "Conversas", "Negociação",
          "Proposta", "Avançado", "Encaminhado", "Acerto", "Anunciado",
          "Oficial", "Opção", "De Saída", "Melou")

SISTEMA = (
    "Você acompanha o mercado de transferências da Saudi Pro League. "
    "Extrai de uma notícia os dados de UMA negociação. "
    "Responde APENAS com JSON válido, sem markdown."
)


def montar_pedido(artigo: dict) -> str:
    titulo = artigo.get("title_pt") or artigo.get("title_orig") or ""
    corpo = artigo.get("body_pt") or artigo.get("body_orig") or ""
    return f"""Analise a notícia e diga se ela trata de UMA negociação
específica de um jogador (transferência, empréstimo, renovação ou saída).

Título: {titulo}
Texto: {corpo[:900]}

Responda com este JSON exato:
{{
  "e_negociacao": true,
  "jogador": "nome do jogador em alfabeto latino",
  "jogador_orig": "o nome exatamente como aparece no texto",
  "clube_origem": "clube de onde ele sai, ou null se a notícia não disser",
  "clube_destino": "clube que quer contratá-lo, ou null",
  "status": "um valor da lista abaixo",
  "valor": "valor citado, ex '25 milhões de euros', ou null",
  "confianca": "alta|media|baixa"
}}

status deve ser EXATAMENTE um destes: {", ".join(STATUS)}

Se a notícia NÃO for sobre uma negociação específica de um jogador — se for
resultado de jogo, lesão, entrevista, ou uma lista de vários negócios sem
foco em um —, responda apenas: {{"e_negociacao": false}}

Regras:
- clube_origem é o clube ATUAL do jogador; clube_destino é quem o quer.
- Renovação: origem e destino são o mesmo clube, status 'Acerto' ou 'Oficial'.
- 'Melou' quando a notícia diz que a negociação caiu, esfriou ou foi recusada.
- confianca 'baixa' quando o texto é vago sobre quem é o jogador ou os clubes.
- NÃO invente clube que a notícia não cita. Prefira null."""


def _limpar(bruto: str) -> dict:
    bruto = (bruto or "").strip()
    if bruto.startswith("```"):
        bruto = bruto.split("```")[1]
        if bruto.startswith("json"):
            bruto = bruto[4:]
    return json.loads(bruto.strip())


def conferir(dados: dict) -> dict | None:
    """O que o modelo devolveu, só que sem confiar nele.

    Três coisas são recusadas aqui, e nenhuma é preciosismo:

    - status fora da lista. O card e o post têm que dizer a mesma palavra;
      um 'Quase certo' inventado pelo modelo viraria uma categoria fantasma
      na guia, com um card só, que ninguém entende de onde veio.
    - sem jogador ou sem destino. Sem os dois não existe negociação para
      identificar — é notícia de mercado genérica.
    - clube igual a jogador, ou nome de uma letra. Sinal de que o modelo
      preencheu campo para não deixar vazio.
    """
    if not isinstance(dados, dict) or not dados.get("e_negociacao"):
        return None
    jogador = " ".join(str(dados.get("jogador") or "").split())
    destino = " ".join(str(dados.get("clube_destino") or "").split())
    if len(jogador) < 3 or len(destino) < 3:
        return None
    if jogador.lower() == destino.lower():
        return None
    status = str(dados.get("status") or "").strip()
    if status not in STATUS:
        # Tolero só a diferença de caixa; o resto é invenção.
        casados = [s for s in STATUS if s.lower() == status.lower()]
        if not casados:
            return None
        status = casados[0]
    origem = " ".join(str(dados.get("clube_origem") or "").split())
    return {
        "jogador": jogador,
        "jogador_orig": " ".join(str(dados.get("jogador_orig") or "").split()) or jogador,
        "clube_origem": origem or "",
        "clube_destino": destino,
        "status": status,
        "valor": " ".join(str(dados.get("valor") or "").split()) or "",
        "confianca": (str(dados.get("confianca") or "media").lower()
                      if str(dados.get("confianca") or "").lower()
                      in ("alta", "media", "baixa") else "media"),
    }


async def extrair(artigo: dict, cliente) -> dict | None:
    """Uma notícia, uma negociação — ou None."""
    from processor import call_claude, CLAUDE_MODEL_TRIAGEM
    try:
        bruto = await call_claude(montar_pedido(artigo), SISTEMA, cliente,
                                  max_tokens=300, cache_system=True,
                                  model=CLAUDE_MODEL_TRIAGEM)
        return conferir(_limpar(bruto))
    except Exception as e:
        titulo = (artigo.get("title_pt") or artigo.get("title_orig") or "")[:50]
        print(f"   ⚠️  mercado, '{titulo}': {type(e).__name__}: {e}")
        return None


# ── A identidade da negociação ──────────────────────────────────────────────
def chave_da_negociacao(jogador: str, destino: str) -> str:
    """Jogador + clube de destino, normalizados.

    A escolha é do Vini e ela é a certa: se o Al Hilal e o Al Nassr disputam o
    mesmo jogador, são DUAS negociações com histórias separadas. Um 'Melou' de
    uma não pode aparecer na linha do tempo da outra.
    """
    import glossary
    clube = glossary.padronizar_clube(destino) or destino
    return f"{glossary.chave_latina(jogador)}|{glossary.chave_latina(clube)}"


def procurar_na_liga(nome: str, indice: dict) -> str:
    """O spl_id de quem já joga na liga, ou "".

    Aqui eu reaproveito o índice de nomes que já existe para as notícias:
    chave completa, nas duas escritas, ambiguidade descartada. Quem está nos
    573 sai daqui com foto, nascimento, altura e clube — sem gastar uma única
    requisição em lugar nenhum.
    """
    import elos
    achados = elos.jogadores_no_texto("", nome, indice)
    if not achados:
        achados = elos.jogadores_no_texto(nome, "", indice)
    return next(iter(achados)) if len(achados) == 1 else ""


def escolher_de_fora(nome: str, candidatos: list[dict], clube_origem: str) -> dict | None:
    """Qual dos homônimos da API-Football é o da notícia.

    Este é o ponto onde eu quase errei. Buscar 'Martinelli' devolve 28
    resultados, e o Gabriel do Arsenal NÃO está nos três primeiros — vêm um
    suíço e dois italianos antes. Pegar o primeiro poria a cara de um zagueiro
    suíço no card de um ponta do Arsenal, com aparência de acerto.

    O desempate vem da própria notícia: o clube de origem. 'Ritsu Doan do
    Eintracht' só casa com o Doan que está no Eintracht. Sem clube de origem,
    ou com mais de um sobrando, eu devolvo None — card sem rosto é honesto,
    rosto errado não é.
    """
    import glossary
    if not candidatos:
        return None
    alvo = glossary.chave_latina(clube_origem or "")
    if not alvo:
        return None
    iguais = [c for c in candidatos
              if glossary.chave_latina(c.get("clube") or "") == alvo]
    if len(iguais) != 1:
        return None
    escolhido = iguais[0]
    # O nome ainda tem que ter alguma coisa a ver. A API abrevia o primeiro
    # nome ('O. Watkins'), então exijo uma palavra em comum, não o nome todo.
    meu = set(glossary.chave_latina(nome).split())
    seu = set(glossary.chave_latina(escolhido.get("nome") or "").split())
    if meu and seu and not (meu & seu):
        return None
    return escolhido
