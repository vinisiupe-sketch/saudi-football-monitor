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
}


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


def _ordinal_rodada(rodada: str | None) -> str:
    """'Regular Season - 1' -> '1ª Rodada'."""
    m = re.search(r"(\d+)", rodada or "")
    return f"{m.group(1)}ª Rodada" if m else "Rodada"


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
    t = (transmissao or "").strip()
    # Sem transmissão definida, o post sai dizendo isso — que é a informação
    # verdadeira até alguém preencher. Nunca chutar canal.
    linhas.append(f"🖥️ {t}" if t and t.lower() != "sem transmissão" else "❌ Sem transmissão")
    return "\n".join(linhas)


def chave_do_jogo(fixture_id) -> str:
    """Identidade do post na fila: um jogo gera um BOLA ROLANDO, e só um."""
    return f"bola_rolando:{fixture_id}"
