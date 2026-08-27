"""
Geradores de post das rotinas do canal.

Escrito à mão, sem IA: o formato do BOLA ROLANDO é fixo e conhecido, e pedir
para um modelo redigi-lo só acrescentaria custo e a chance de inventar frase.
O único campo que varia por decisão humana é a transmissão.
"""
import os
import re
import unicodedata

DIR_ESCUDOS = os.path.join(os.path.dirname(__file__), "public", "escudos")

# Nome curto -> arquivo do escudo. A chave é o que sobra do nome do clube
# depois de tirar "Al", acentos e sufixos; ver _chave_clube.
ESCUDO_POR_CLUBE = {
    "hilal": "hilal", "nassr": "nassr", "ittihad": "ittihad", "ahli": "ahli",
    "qadsiah": "qadsiah", "qadisiyah": "qadsiah", "shabab": "shabab",
    "taawon": "taawoun", "taawoun": "taawoun", "khaleej": "khaleej",
    "fateh": "fateh", "fayha": "fayha", "riyadh": "riyadh", "ettifaq": "ettifaq",
    "hazm": "hazem", "hazem": "hazem", "neom": "neom", "kholood": "kholood",
    "okhdood": "okhdood", "diriyah": "diriyah", "faisaly": "faisaly",
    "abha": "abha", "najma": "najmah", "najmah": "najmah", "damac": "damac",
    "raed": "raed", "tai": "tai", "wehda": "wehda", "orobah": "orobah",
    "batin": "batin", "jabalin": "jabalin", "adalah": "adalah", "anwar": "anwar",
    "ula": "ula", "zulfi": "zulfi", "jeddah": "jeddah", "bukayriyah": "bukayriyah",
    # A API-Football grafa diferente do nome dos arquivos. Sem estes apelidos o
    # escudo some sem aviso — foi o que aconteceu com o Jabalain.
    "jabalain": "jabalin", "bukiryah": "bukayriyah", "taee": "tai",
    "khaleej": "khaleej", "kholoos": "kholood", "najm": "najmah",
}

# Competições fora do país: nelas o post usa bandeira em vez de cor de clube.
COMPETICOES_INTERNACIONAIS = {17, 18, 1168}


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "")
                   if unicodedata.category(c) != "Mn")


def _chave_clube(nome: str) -> str:
    n = _sem_acento(nome or "").lower()
    n = re.sub(r"\b(fc|sc|sfc|club|saudi|jeddah fc)\b", " ", n)
    n = re.sub(r"^\s*al[-\s]+", " ", " " + n)
    n = re.sub(r"[^a-z ]", " ", n)
    partes = [p for p in n.split() if p]
    return partes[0] if partes else ""


def escudo_de(nome_clube: str) -> str | None:
    """Caminho do arquivo do escudo, ou None se não temos aquele clube."""
    arq = ESCUDO_POR_CLUBE.get(_chave_clube(nome_clube))
    if not arq:
        return None
    caminho = os.path.join(DIR_ESCUDOS, arq + ".png")
    return caminho if os.path.exists(caminho) else None


# Fases de mata-mata em inglês, como a API-Football escreve. Traduzir aqui
# evita "Round of 32" aparecendo cru num post em português.
# ORDEM IMPORTA: do mais específico para o mais genérico. "final" precisa vir
# por último, senão "Quarter-finals" e "Semi-finals" casam com ele e viram "Final".
FASES = [
    ("round of 64", "32 avos de Final"), ("round of 32", "16 avos de Final"),
    ("round of 16", "Oitavas de Final"), ("8th finals", "Oitavas de Final"),
    ("quarter", "Quartas de Final"), ("semi", "Semifinal"),
    ("3rd place", "Disputa de 3º Lugar"), ("play-off", "Playoff"),
    ("playoff", "Playoff"), ("group stage", "Fase de Grupos"),
    ("group", "Fase de Grupos"), ("final", "Final"),
]


def _ordinal_rodada(rodada: str | None) -> str:
    """'Regular Season - 1' -> '1ª Rodada'; 'Round of 32' -> '16 avos de Final'."""
    r = (rodada or "").strip()
    baixo = r.lower()
    for chave, traducao in FASES:
        if chave in baixo:
            # Grupo com letra ("Group Stage - A") preserva a letra.
            g = re.search(r"group[^a-z]*(?:stage)?[^a-z]*([a-h])\b", baixo)
            return f"{traducao} {g.group(1).upper()}" if g else traducao
    m = re.search(r"(\d+)", r)
    return f"{m.group(1)}ª Rodada" if m else (r or "Rodada")


def montar_bola_rolando(casa: str, fora: str, cor_casa: str, cor_fora: str,
                        rodada: str | None, competicao: str = "Liga Saudita",
                        transmissao: str | None = None) -> str:
    """Texto no formato exato dos posts do canal."""
    linhas = [
        "⏱️🇸🇦 BOLA ROLANDO!",
        "",
        f"🆚 {cor_casa} {casa} vs {fora} {cor_fora}".replace("  ", " ").strip(),
        f"🏆 {_ordinal_rodada(rodada)} | {competicao}",
    ]
    # Sem transmissão definida, o post sai dizendo isso — que é a informação
    # verdadeira até alguém preencher. Nunca chutar canal.
    if isinstance(transmissao, list):
        linhas.append(linha_transmissao(transmissao))
    else:
        t = (transmissao or "").strip()
        linhas.append(f"🖥️ {t}" if t and t.lower() != "sem transmissão" else "❌ Sem transmissão")
    return "\n".join(linhas)


# Como cada competição aparece no post.
COMPETICOES = {
    307: "Liga Saudita",
    504: "Copa do Rei",
    826: "Supercopa Saudita",
    # A Divisão 1 saiu daqui a pedido: o canal não cobre a segunda divisão.
    # Basta tirar da lista — a agenda e o gerador leem só o que está aqui, e
    # o que já tiver entrado na fila é cancelado na subida (ver main.py).
    17:  "AFC Champions League Elite",
    18:  "AFC Champions League Two",
}

# Opções de transmissão que o canal usa. A ordem aqui é a ordem no post.
TRANSMISSOES = ["Canal GOAT 🐐", "Band", "BandSports", "XSports",
                "Sportv", "Sportv 2", "Sportv 3", "Sportv 4"]


def linha_transmissao(canais: list[str] | None) -> str:
    """'A, B e C' — como o canal escreve. Lista vazia vira 'Sem transmissão'."""
    limpos = [c for c in (canais or []) if c and c in TRANSMISSOES]
    if not limpos:
        return "❌ Sem transmissão"
    if len(limpos) == 1:
        return f"🖥️ {limpos[0]}"
    return "🖥️ " + ", ".join(limpos[:-1]) + " e " + limpos[-1]


def chave_do_jogo(fixture_id) -> str:
    """Identidade do post na fila: um jogo gera um BOLA ROLANDO, e só um."""
    return f"bola_rolando:{fixture_id}"


def jogo_da_chave(chave: str):
    """O caminho de volta: de 'bola_rolando:12345' para 12345.

    Devolve None se a chave não for de um jogo. Chutar um número aqui faria a
    transmissão ser gravada no jogo errado, e ninguém perceberia.
    """
    if not chave or ":" not in str(chave):
        return None
    tipo, _, resto = str(chave).partition(":")
    if tipo != "bola_rolando":
        return None
    try:
        return int(resto)
    except (TypeError, ValueError):
        return None


def canais_da_linha(texto: str) -> list[str] | None:
    """Lê de volta os canais de um post que já existe.

    Serve para o backfill e como rede: enquanto a tabela de transmissão não
    tiver a linha deste jogo, a tela ainda mostra o que o post diz.

    Devolve None quando o post não tem linha de transmissão nenhuma — que é
    diferente de [] ("marcado como sem transmissão").

    Casa pelo nome inteiro e não por 'está contido', porque "Sportv" está
    contido em "Sportv 2": procurar por pedaço acenderia o canal errado.
    """
    if not texto:
        return None
    linhas = [l.strip() for l in str(texto).split("\n") if l.strip()]
    linha = ""
    for l in reversed(linhas):
        if l.startswith("🖥️") or l.startswith("❌"):
            linha = l
            break
    if not linha:
        return None
    if linha.startswith("❌"):
        return []
    corpo = linha[len("🖥️"):].strip()
    pedacos = []
    for parte in corpo.split(","):
        pedacos.extend(p.strip() for p in parte.split(" e "))
    achados = [p for p in pedacos if p in TRANSMISSOES]
    # Um canal com " e " no nome sobreviveria partido em dois e sumiria da
    # lista. Se sobrou algo por reconhecer, tento a linha inteira também.
    for c in TRANSMISSOES:
        if c not in achados and (corpo == c or corpo.endswith(" e " + c)
                                 or corpo.startswith(c + ",")):
            achados.append(c)
    return [c for c in TRANSMISSOES if c in achados]
