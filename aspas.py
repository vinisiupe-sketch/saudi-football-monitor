"""
Tira as declarações de dentro das notícias de entrevista.

SEM IA, DE PROPÓSITO
    Dava para pedir a um modelo que lesse e devolvesse quem falou e o que
    falou. Seria mais preciso e custaria uma chamada por notícia, todo dia.
    Aqui a conta é feita em cima do texto que JÁ foi traduzido e pago.

    O preço dessa escolha é honesto: eu não entendo o texto, eu reconheço
    padrões. "Fulano disse: 'frase'" eu pego. Frase solta no meio de um
    parágrafo, sem verbo de fala por perto, eu não pego — e prefiro não pegar
    a chutar um nome.

O QUE SAI DAQUI
    quem     — quem falou
    fala     — o que ele disse, sem as aspas
    onde     — "em entrevista ao Al-Riyadiya", "em coletiva"... quando dá
    via      — a fonte de onde a notícia veio

O QUE NÃO SAI
    Declaração sem dono. Se eu não achar quem falou com alguma confiança, a
    citação é descartada e entra na contagem de descartadas — que a tela
    mostra. Sumir com coisa em silêncio é pior que mostrar menos.
"""
import re
import unicodedata

# As aspas que aparecem de verdade em texto traduzido. O par tem que ser
# reconhecido junto: texto misturando " reto e “ curvo é comum.
PARES = [("“", "”"), ("‘", "’"), ("«", "»"),
         ('"', '"'), ("'", "'")]

# Verbos que denunciam fala. Sem um deles por perto, eu não digo de quem é.
VERBOS = (
    "disse", "afirmou", "declarou", "comentou", "garantiu", "explicou",
    "revelou", "destacou", "completou", "acrescentou", "contou", "avaliou",
    "ressaltou", "lamentou", "celebrou", "criticou", "elogiou", "admitiu",
    "prometeu", "reclamou", "confirmou", "negou", "respondeu", "concluiu",
    "analisou", "projetou", "relembrou", "brincou", "desabafou", "apontou",
)
_VERBOS_RE = "|".join(VERBOS)

# Onde a pessoa falou. A ordem importa: a primeira que casar vence, então as
# mais específicas vêm antes.
LUGARES = [
    (r"em entrevista (?:à|ao|a|para o|para a)\s+([A-ZÀ-Ú][\w\.\-]*(?:\s+[A-ZÀ-Ú][\w\.\-]*){0,3})",
     "em entrevista ao {0}"),
    (r"\bem coletiva de imprensa\b", "em coletiva de imprensa"),
    (r"\bem coletiva\b", "em coletiva"),
    (r"\bap[óo]s a partida\b", "após a partida"),
    (r"\bna zona mista\b", "na zona mista"),
    (r"\bem sua conta no ([A-ZÀ-Ú][\w]*)", "em sua conta no {0}"),
    (r"\b(?:ao|à|para o|para a) (?:canal|programa|jornal|site|r[áa]dio|portal)\s+"
     r"([A-ZÀ-Ú][\w\.\-]*(?:\s+[A-ZÀ-Ú][\w\.\-]*){0,2})", "ao {0}"),
    (r"\bem comunicado(?: oficial)?\b", "em comunicado oficial"),
    (r"\bem nota oficial\b", "em nota oficial"),
]

# Palavras que começam com maiúscula mas não são nome de gente. Sem esta
# lista, "O Al Hilal disse" me daria "Al Hilal" como pessoa — e o cartão diria
# que um clube abriu a boca.
NAO_E_NOME = {
    "o", "a", "os", "as", "e", "mas", "que", "quando", "segundo", "ele",
    "ela", "eles", "elas", "isso", "isto", "aquele", "no", "na", "em",
    "para", "por", "com", "sem", "sobre", "ainda", "também", "já", "não",
    "ao", "aos", "às", "de", "do", "da", "dos", "das", "um", "uma",
}

# Onde o nome acaba. Sem isto, "disse Cristiano Ronaldo em entrevista ao
# Al-Riyadiya" me dava "Cristiano Ronaldo Al-Riyadiya" como pessoa — o nome
# engolia o lugar. Foi o teste que pegou; eu tinha escrito confiante.
CORTA_NOME = re.compile(
    r"\s+(?:em|no|na|ao|à|aos|às|para|durante|após|apos|depois|antes|sobre|"
    r"que|e|ainda|também|tambem|nesta|neste|pelo|pela|com|sem)\b", re.I)

MIN_FALA = 25          # abaixo disso não é declaração, é fragmento
MAX_FALA = 600


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def _parece_nome(pedaco: str) -> str:
    """Devolve o nome próprio no fim do pedaço, ou "" se não houver.

    Aceito de uma a quatro palavras começando com maiúscula, porque nome
    saudita transliterado costuma ter partícula no meio: "Abdullah Al Hamdan".
    """
    palavras = re.findall(r"[A-ZÀ-Ú][\wÀ-ÿ'\-]+|\bAl\b|\bbin\b|\bel\b|\bde\b|\bdos\b",
                          pedaco)
    fim = []
    for p in reversed(palavras):
        if _sem_acento(p) in NAO_E_NOME and not fim:
            continue
        if _sem_acento(p) in NAO_E_NOME and fim:
            break
        fim.append(p)
        if len(fim) >= 4:
            break
    fim.reverse()
    while fim and _sem_acento(fim[0]) in NAO_E_NOME:
        fim.pop(0)
    nome = " ".join(fim).strip()
    if len(nome) < 3 or len(nome.split()) > 4:
        return ""
    # Uma palavra só, muito curta, quase sempre é lixo de pontuação.
    if len(nome.split()) == 1 and len(nome) < 4:
        return ""
    return nome


def _achar_falas(texto: str):
    """Os trechos entre aspas, com onde cada um começa e termina."""
    achados = []
    for ab, fe in PARES:
        if ab == fe:
            # Aspas iguais dos dois lados: pego aos pares, na ordem.
            posicoes = [m.start() for m in re.finditer(re.escape(ab), texto)]
            for i in range(0, len(posicoes) - 1, 2):
                ini, fim = posicoes[i], posicoes[i + 1]
                achados.append((ini, fim + 1, texto[ini + 1:fim]))
        else:
            for m in re.finditer(re.escape(ab) + r"(.+?)" + re.escape(fe),
                                 texto, re.S):
                achados.append((m.start(), m.end(), m.group(1)))
    achados.sort(key=lambda x: x[0])
    # Tiro os que estão dentro de outro (aspas dentro de aspas).
    limpos = []
    for a in achados:
        if not any(b[0] <= a[0] and a[1] <= b[1] and b is not a for b in achados):
            limpos.append(a)
    return limpos


def _quem_falou(texto: str, ini: int, fim: int) -> str:
    """Procura o dono da fala em volta dela.

    Primeiro DEPOIS ("...", disse Fulano), que é a construção mais comum em
    notícia traduzida, e a menos ambígua: o nome vem colado no verbo. Só então
    ANTES ("Fulano afirmou: ..."), que erra mais porque o nome pode estar
    longe do verbo, do outro lado da vírgula.
    """
    depois = texto[fim:fim + 90]
    m = re.match(r"[\s,\.\-—–]*(?:" + _VERBOS_RE + r")\s+(?:o\s+|a\s+)?(.{3,70}?)"
                 r"(?:[,\.;]|$)", depois, re.I)
    if m:
        nome = _parece_nome(CORTA_NOME.split(m.group(1))[0])
        if nome:
            return nome

    antes = texto[max(0, ini - 160):ini]
    m = re.search(r"(.{3,70}?)\s+(?:" + _VERBOS_RE + r")\s*[:,]?\s*$", antes, re.I)
    if m:
        nome = _parece_nome(m.group(1))
        if nome:
            return nome
    return ""


def _onde_falou(texto: str) -> str:
    for padrao, molde in LUGARES:
        m = re.search(padrao, texto, re.I)
        if m:
            if not m.groups():
                return molde
            # O ponto final da frase vinha grudado: "ao Al Arabiya." virava o
            # nome do canal. Tiro a pontuação de encerramento das pontas.
            pedacos = [g.strip(" .,;:!?—–-") for g in m.groups()]
            return molde.format(*pedacos)
    return ""


def extrair(titulo: str, corpo: str, fonte: str = "") -> dict:
    """As declarações de uma notícia.

    Devolve {"citacoes": [...], "descartadas": n}. O número de descartadas
    não é enfeite: é ele que diz se este extrator está servindo ou se está
    deixando metade do material para trás sem ninguém notar.
    """
    texto = f"{titulo or ''}\n{corpo or ''}".strip()
    onde = _onde_falou(texto)
    citacoes, descartadas = [], 0
    vistas = set()
    for ini, fim, fala in _achar_falas(texto):
        fala = " ".join(fala.split())
        if not (MIN_FALA <= len(fala) <= MAX_FALA):
            descartadas += 1
            continue
        chave = _sem_acento(fala)[:80]
        if chave in vistas:
            continue
        quem = _quem_falou(texto, ini, fim)
        if not quem:
            descartadas += 1
            continue
        vistas.add(chave)
        citacoes.append({"quem": quem, "fala": fala, "onde": onde,
                         "via": (fonte or "").lstrip("@")})
    return {"citacoes": citacoes, "descartadas": descartadas}
