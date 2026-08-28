"""
Glossário de termos do futebol saudita para padronizar traduções.
"""
import re

# Mapeamento canônico: qualquer variação → forma correta
CLUB_NAMES = {
    # Al Ahli
    "Al-Ahli": "Al Ahli", "Alahli": "Al Ahli", "Al-ahli": "Al Ahli", "الأهلي": "Al Ahli",
    # Al Ettifaq
    "Al-Ettifaq": "Al Ettifaq", "Alettifaq": "Al Ettifaq", "Al-ettifaq": "Al Ettifaq", "الاتفاق": "Al Ettifaq",
    # Al Fateh
    "Al-Fateh": "Al Fateh", "Alfateh": "Al Fateh", "الفتح": "Al Fateh",
    # Al Fayha
    "Al-Fayha": "Al Fayha", "Alfayha": "Al Fayha", "الفيحاء": "Al Fayha",
    # Al Hazem
    "Al-Hazem": "Al Hazem", "Alhazem": "Al Hazem", "الحزم": "Al Hazem",
    # Al Hilal
    "Al-Hilal": "Al Hilal", "Alhilal": "Al Hilal", "Al-hilal": "Al Hilal", "الهلال": "Al Hilal",
    # Al Ittihad
    "Al-Ittihad": "Al Ittihad", "Alittihad": "Al Ittihad", "Al-ittihad": "Al Ittihad", "الاتحاد": "Al Ittihad",
    # Al Khaleej
    "Al-Khaleej": "Al Khaleej", "Alkhaleej": "Al Khaleej", "الخليج": "Al Khaleej",
    # Al Kholood
    "Al-Kholood": "Al Kholood", "Alkholood": "Al Kholood", "الخلود": "Al Kholood",
    # Al Najma
    "Al-Najma": "Al Najma", "Alnajma": "Al Najma", "النجمة": "Al Najma",
    # Al Nassr
    "Al-Nassr": "Al Nassr", "Alnassr": "Al Nassr", "Al-nassr": "Al Nassr", "النصر": "Al Nassr",
    # Al Okhdood
    "Al-Okhdood": "Al Okhdood", "Alokhdood": "Al Okhdood", "الأخدود": "Al Okhdood",
    # Al Qadsiah
    "Al-Qadsiah": "Al Qadsiah", "Alqadsiah": "Al Qadsiah", "القادسية": "Al Qadsiah",
    # Al Riyadh
    "Al-Riyadh": "Al Riyadh", "Alriyadh": "Al Riyadh", "الرياض": "Al Riyadh",
    # Al Shabab
    "Al-Shabab": "Al Shabab", "Alshabab": "Al Shabab", "Al-shabab": "Al Shabab", "الشباب": "Al Shabab",
    # Al Taawoun
    "Al-Taawoun": "Al Taawoun", "Altaawoun": "Al Taawoun", "Al Tawoun": "Al Taawoun", "التعاون": "Al Taawoun",
    # Damac
    "ضمك": "Damac",
    # Neom S.C.
    "Neom": "Neom S.C.", "نيوم": "Neom S.C.",
    # Al Diriyah
    "Al-Diriyah": "Al Diriyah", "الدرعية": "Al Diriyah",
    # Al Ula
    "Al-Ula": "Al Ula", "العلا": "Al Ula",
    # ── Yelo League (1ª Divisão) ──────────────────────────────────────────
    # Abha
    "أبها": "Abha", "Abha Club": "Abha",
    # Al Adalah
    "Al-Adalah": "Al Adalah", "العدالة": "Al Adalah",
    # Al Anwar
    "Al-Anwar": "Al Anwar", "الأنوار": "Al Anwar",
    # Al Arabi
    "Al-Arabi": "Al Arabi", "العربي": "Al Arabi",
    # Al Batin
    "Al-Batin": "Al Batin", "الباطن": "Al Batin",
    # Al Bukiryah
    "Al-Bukiryah": "Al Bukiryah", "البكيرية": "Al Bukiryah",
    # Al Faisaly
    "Al-Faisaly": "Al Faisaly", "الفيصلي": "Al Faisaly",
    # Al Jabalain
    "Al-Jabalain": "Al Jabalain", "الجبلين": "Al Jabalain",
    # Al Jandal
    "Al-Jandal": "Al Jandal", "الجندل": "Al Jandal",
    # Al Jubail
    "Al-Jubail": "Al Jubail", "الجبيل": "Al Jubail",
    # Al Orobah
    "Al-Orobah": "Al Orobah", "العروبة": "Al Orobah",
    # Al Raed
    "Al-Raed": "Al Raed", "الرائد": "Al Raed",
    # Al Shoulla
    "Al-Shoulla": "Al Shoulla", "الشعلة": "Al Shoulla",
    # Al Tai
    "Al-Tai": "Al Tai", "الطائي": "Al Tai",
    # Al Wahda / Al Wehda
    "Al-Wahda": "Al Wahda", "Al-Wehda": "Al Wahda", "الوحدة": "Al Wahda",
    # Al Zulfi
    "Al-Zulfi": "Al Zulfi", "الزلفي": "Al Zulfi",
    # Jeddah FC
    "Jeddah FC": "Jeddah", "نادي جدة": "Jeddah",
    # ── Second Division League (2ª Divisão) ──────────────────────────────
    # Group A
    "Afif": "Afif", "عفيف": "Afif",
    "Al-Ain": "Al Ain", "العين": "Al Ain",
    "Al-Entesar": "Al Entesar", "الانتصار": "Al Entesar",
    "Al-Jeel": "Al Jeel", "الجيل": "Al Jeel",
    "Al-Nojoom": "Al Nojoom", "النجوم": "Al Nojoom",
    "Al-Rawdhah": "Al Rawdhah", "الروضة": "Al Rawdhah",
    "Al-Sadd": "Al Sadd", "السد": "Al Sadd",
    "Al-Sahel": "Al Sahel", "الساحل": "Al Sahel",
    "Al-Sharq": "Al Sharq", "الشرق": "Al Sharq",
    "Al-Taraji": "Al Taraji", "الترجي": "Al Taraji",
    "Al-Washm": "Al Washm", "الوشم": "Al Washm",
    "Jerash": "Jerash", "جرش": "Jerash",
    "Jubbah": "Jubbah", "جبة": "Jubbah",
    "Najran": "Najran", "نجران": "Najran",
    "Tuwaiq": "Tuwaiq", "طويق": "Tuwaiq",
    # Group B
    "Al-Ghottah": "Al Ghottah", "الغطة": "Al Ghottah",
    "Al-Kawkab": "Al Kawkab", "الكوكب": "Al Kawkab",
    "Al-Lewaa": "Al Lewaa", "اللواء": "Al Lewaa",
    "Al-Nairyah": "Al Nairyah", "النيرية": "Al Nairyah",
    "Al-Qala": "Al Qala", "القلعة": "Al Qala",
    "Al-Qous": "Al Qous", "القوس": "Al Qous",
    "Al-Rayyan": "Al Rayyan", "الريان": "Al Rayyan",
    "Al-Safa": "Al Safa", "الصفا": "Al Safa",
    "Al-Saqer": "Al Saqer", "الصقر": "Al Saqer",
    "Arar": "Arar", "عرعر": "Arar",
    "Bisha": "Bisha", "بيشة": "Bisha",
    "Hajer": "Hajer", "هجر": "Hajer",
    "Hetten": "Hetten", "حطين": "Hetten",
    "Mudhar": "Mudhar", "مضر": "Mudhar",
    "Ohod": "Ohod", "أحد": "Ohod",
    "Wej": "Wej", "وج": "Wej",
    # ── Outros ───────────────────────────────────────────────────────────
    # Al Ansar
    "Al-Ansar": "Al Ansar", "الأنصار": "Al Ansar",
    # Kingdom Holding
    "المملكة القابضة": "Kingdom Holding",
    # PIF
    "صندوق الاستثمارات العامة": "PIF",
}

# Listas canônicas usadas para montar o glossário enviado à IA na tradução
# (processor.py) e na geração de posts (main.py) — fonte única, evita que os
# dois prompts fiquem com listas de clubes divergentes/desatualizadas entre si.
SPL_CLUBS = [
    "Al Hilal", "Al Nassr", "Al Ittihad", "Al Ahli", "Al Shabab", "Al Taawoun",
    "Al Fateh", "Al Ettifaq", "Al Qadsiah", "Al Fayha", "Al Hazem", "Al Khaleej",
    "Al Kholood", "Al Najma", "Al Okhdood", "Al Riyadh", "Al Diriyah", "Al Ula",
    "Damac", "Neom S.C.",
]

# Yelo League — nome comercial da "1ª Divisão" saudita (2º nível da pirâmide,
# abaixo da Saudi Pro League). Citados com frequência em notícias de
# empréstimos/transferências envolvendo a SPL (ex: Abha).
YELO_CLUBS = [
    "Abha", "Al Adalah", "Al Anwar", "Al Arabi", "Al Batin", "Al Bukiryah",
    "Al Faisaly", "Al Jabalain", "Al Jandal", "Al Jubail", "Al Orobah",
    "Al Raed", "Al Shoulla", "Al Tai", "Al Wahda", "Al Zulfi", "Jeddah",
]

COMPETITION_NAMES = {
    "Liga Saudita": "Saudi Pro League",
    "Liga Árabe Saudita": "Saudi Pro League",
    "Liga Profissional Saudita": "Saudi Pro League",
    "Campeonato Saudita": "Saudi Pro League",
    "Campeonato Árabe Saudita": "Saudi Pro League",
    "دوري روشن": "Saudi Pro League",
    "دوري روشن السعودي": "Saudi Pro League",
    "Roshn League": "Saudi Pro League",
    "Roshn Saudi League": "Saudi Pro League",
}

# Glossário resumido para o system prompt da tradução
# Mantido curto intencionalmente — glossários longos degradam qualidade do Haiku.
# O apply_glossary() pós-processamento cobre as variações de grafia LATINA dos
# clubes (ex: "Al-Hilal" → "Al Hilal"); ele NÃO corrige nomes árabes que o
# modelo deixou de traduzir ou alucinou — para isso o clube precisa estar
# listado abaixo, no prompt que a IA vê ANTES de responder.
GLOSSARY_PROMPT = f"""
Glossário obrigatório — use EXATAMENTE estes nomes, SEM hífen, sem variações:
Clubes SPL (1ª divisão): {", ".join(SPL_CLUBS)}.
Clubes Yelo League (2º nível, abaixo da SPL, aparecem em notícias de empréstimo/transferência): {", ".join(YELO_CLUBS)}.
Competição: sempre "Saudi Pro League" (nunca "Liga Saudita" ou "Campeonato Saudita").
DISTINÇÃO CRÍTICA: الاتفاق = Al Ettifaq (Dammam) | الاتحاد = Al Ittihad (Jeddah). Nunca confunda.
NUNCA invente nomes de jogadores em árabe — translitere letra por letra.
"""


def apply_glossary(text: str) -> str:
    """Aplica correcoes pos-traducao. Retorna texto inalterado se nao houver substituicoes."""
    return text


# ══════════════════════════════════════════════════════════════════════════
# NOME DE CLUBE PARA O QUE VAI AO AR
# ══════════════════════════════════════════════════════════════════════════
#
# As duas APIs escrevem o mesmo clube de jeitos diferentes — "Al-Hilal Saudi
# FC", "Al Khaleej Saihat", "Al-Qadisiyah FC", "NEOM" — e antes o post saía
# com o que viesse, só tirando hífen e subindo a caixa. Aqui o nome passa pela
# tabela e sai sempre igual, venha de onde vier.
#
# A ponte é o clubs.py, que já guarda todas as grafias de cada clube. Eu ia
# escrever mais um normalizador; não escrevo. Da última vez que tentei, o meu
# fazia Al-Hilal e Al-Ahli virarem a mesma coisa.

NOME_DE_EXIBICAO = {
    # Saudi Pro League
    "al_ahli": "Al Ahli", "al_ettifaq": "Al Ettifaq", "al_fateh": "Al Fateh",
    "al_fayha": "Al Fayha", "al_hazem": "Al Hazem", "al_hilal": "Al Hilal",
    "al_ittihad": "Al Ittihad", "al_khaleej": "Al Khaleej",
    "al_kholood": "Al Kholood", "al_najmah": "Al Najma", "al_nassr": "Al Nassr",
    "al_okhdood": "Al Okhdood", "al_qadsiah": "Al Qadsiah",
    "al_riyadh": "Al Riyadh", "al_shabab": "Al Shabab",
    "al_taawoun": "Al Taawoun", "damac": "Damac", "neom": "Neom S.C.",
    # Yelo League
    "abha": "Abha", "al_adalah": "Al Adalah", "al_anwar": "Al Anwar",
    "al_arabi": "Al Arabi", "al_batin": "Al Batin",
    "al_bukiryah": "Al Bukiryah", "al_diraiyah": "Al Diriyah",
    "al_faisaly": "Al Faisaly", "al_jabalain": "Al Jabalain",
    "al_jandal": "Al Jandal", "al_jubail": "Al Jubail",
    "al_orobah": "Al Orobah", "al_raed": "Al Raed", "al_tai": "Al Tai",
    "al_ula": "Al Ula", "al_wehda": "Al Wahda", "al_zulfi": "Al Zulfi",
    "jeddah": "Jeddah",
}

# Sufixos que as APIs grudam no nome e que a tabela não tem. Só caem quando
# sobra alguma coisa: o clube "Jeddah" existe, e tirar " jeddah" dele deixaria
# string vazia.
_SUFIXOS = (" saudi fc", " saudi club", " saudi", " jeddah", " saihat",
            " mecca", " unaizah", " s.c.", " sfc", " fc", " sc", " club")


def _achatar(nome: str) -> str:
    """Forma de comparação: minúscula, sem pontuação, espaços colapsados."""
    t = (nome or "").strip().lower()
    for ch in "-_.'’‏‎":
        t = t.replace(ch, " " if ch in "-_" else "")
    return " ".join(t.split())


def _indice_de_variantes() -> dict:
    import clubs
    idx = {}
    for chave, variantes in clubs.ALL_CLUBS.items():
        exibicao = NOME_DE_EXIBICAO.get(chave)
        if not exibicao:
            continue
        for v in variantes:
            achatado = _achatar(v.replace("#", ""))
            if achatado:
                idx.setdefault(achatado, exibicao)
    return idx


_POR_VARIANTE = _indice_de_variantes()


def padronizar_clube(nome: str) -> str:
    """O nome do clube na grafia da tabela, ou "" se eu não reconhecer.

    Devolver "" de propósito, em vez de chutar o mais parecido: um chute erra
    calado e o erro vai para o ar assinado por você. Quem chama decide o que
    fazer com o desconhecido — e o que fazemos é deixar passar o nome cru.
    """
    achatado = _achatar(nome)
    if not achatado:
        return ""
    if achatado in _POR_VARIANTE:
        return _POR_VARIANTE[achatado]
    for sufixo in _SUFIXOS:
        if achatado.endswith(sufixo):
            resto = achatado[: -len(sufixo)].strip()
            if resto and resto in _POR_VARIANTE:
                return _POR_VARIANTE[resto]
    return ""


def nome_para_card(nome: str) -> str:
    """Nome em caixa alta para o card de gol: "AL HILAL", "NEOM S.C."."""
    padrao = padronizar_clube(nome)
    if padrao:
        return padrao.upper()
    # Desconhecido — adversário de torneio asiático, por exemplo. Faço o
    # arrumado mínimo e mantenho o nome, que é melhor que apagá-lo.
    limpo = (nome or "").strip()
    for sufixo in (" Saudi FC", " FC", " SC", " Club"):
        if limpo.endswith(sufixo):
            limpo = limpo[: -len(sufixo)]
    return limpo.replace("-", " ").upper().strip()


# O grito, do jeito que você escreve. São símbolos matemáticos (U+1D400), não
# letras comuns: é por isso que o X conta cada um como DOIS caracteres.
GRITO_DE_GOL = "\U0001D46E" + "\U0001D476" * 14 + "\U0001D473"


# ══════════════════════════════════════════════════════════════════════════
# O QUE VAI PARA O BANCO
# ══════════════════════════════════════════════════════════════════════════

# A API-Football escreve "A. Al Hussain" onde a liga escreve "Ali Al Hussain".
# Não é outra transliteração — é abreviação sistemática do primeiro nome. Isso
# tem conserto por regra, e regra não é chute: a inicial ou bate ou não bate.
_SO_INICIAL = re.compile(r"^\s*([A-Za-zÀ-ÿ])\.?\s+(.+)$")


def partir_por_inicial(nome: str) -> tuple[str, str]:
    """('a', 'al hussain') para 'A. Al Hussain'. ('', '') se não for abreviado.

    Só considero abreviação quando a primeira palavra tem UMA letra. "Ali Al
    Hussain" não entra aqui — ele já é o nome inteiro, e tratar as duas formas
    do mesmo jeito faria a busca comparar coisas diferentes.
    """
    m = _SO_INICIAL.match(nome or "")
    if not m:
        return "", ""
    inicial = chave_latina(m.group(1))[:1]
    return inicial, chave_latina(m.group(2))


def inicial_e_resto(nome: str) -> tuple[str, str]:
    """O mesmo formato, para um nome COMPLETO: ('a', 'al hussain').

    É o outro lado da comparação. 'Ali Al Hussain' vira ('a', 'al hussain') e
    bate com o que veio abreviado — sem que eu precise adivinhar que o "A." é
    "Ali".
    """
    partes = chave_latina(nome).split()
    if len(partes) < 2:
        return "", ""
    return partes[0][:1], " ".join(partes[1:])


def clube_para_guardar(nome: str) -> str:
    """O nome do clube como ele deve ser GRAVADO.

    A medição de 27/08 mostrou 29 clubes escritos de mais de um jeito dentro
    do próprio app — 'Al Hilal' nas lesões, 'Al-Hilal SFC' na janela,
    'Al-Hilal Saudi FC' na prévia, 'Al Diraiyah' na arbitragem. Nenhuma dessas
    grafias foi inventada aqui: são as fontes. O erro era guardar o texto cru
    em vez do canônico, e depois traduzir só na hora de mostrar — o que
    funciona numa tela e não funciona quando você quer cruzar duas.

    Por que dá para gravar o canônico sem guardar o original ao lado: o
    `padronizar_clube` não chuta. Ele casa contra uma lista explícita de
    variantes e devolve "" quando não conhece. Não existe o caso de "ele achou
    parecido e errou" — ou sabe, ou não sabe. Onde não sabe, o nome cru passa
    inteiro, e aparece em /api/diag/nomes para eu ampliar a lista.

    Isso vale para clube saudita. Ajax, Atalanta e os sub-21 da janela caem no
    "não sei" de propósito: forçá-los para dentro da tabela saudita seria
    inventar um clube que não existe lá.
    """
    limpo = " ".join((nome or "").split())
    if not limpo:
        return ""
    return padronizar_clube(limpo) or limpo


def clubes_do_texto(*nomes) -> list[str]:
    """Vários de uma vez, na mesma regra."""
    return [clube_para_guardar(n) for n in nomes]


# ══════════════════════════════════════════════════════════════════════════
# CHAVES DE COMPARAÇÃO DE NOME
#
# Não são nomes para mostrar. São a forma reduzida usada para dizer "isto e
# aquilo são a mesma pessoa". Ninguém lê uma chave; ela só é comparada.
# ══════════════════════════════════════════════════════════════════════════

# Sinais que a escrita árabe usa e que a imprensa aplica de forma inconsistente.
# Nenhum deles muda quem é a pessoa.
_HARAKAT = "".join(chr(c) for c in list(range(0x064B, 0x0653)) + [0x0670, 0x0640])

# Letras que são a mesma consoante escrita de jeitos diferentes. أ إ آ ٱ são
# todas alif; ة e ه se confundem no fim da palavra; ى e ي idem.
_MESMA_LETRA = {
    "أ": "ا", "إ": "ا", "آ": "ا",
    "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ة": "ه",
    "ؤ": "و",
}

# O artigo definido. "الاتحاد" e "اتحاد" são o mesmo clube, e a imprensa usa os
# dois. Tiro do começo de cada palavra — mas só quando sobra palavra: sem essa
# guarda, "الله" viraria "له", que não é nada.
_ARTIGO = "ال"


def chave_arabe(nome: str) -> str:
    """A forma do nome árabe usada para comparar.

    O que ela apaga é exatamente o que varia de fonte para fonte sem mudar a
    pessoa: harakat, tatweel, alif com e sem hamza, tá-marbuta contra há, o
    artigo ال grudado.

    O que ela NÃO faz é adivinhar. Duas grafias que sobrarem diferentes
    continuam diferentes — quem decide se são a mesma pessoa é o índice de
    apelidos, não esta função.
    """
    t = (nome or "")
    t = "".join(c for c in t if c not in _HARAKAT)
    t = "".join(_MESMA_LETRA.get(c, c) for c in t)
    # Fora letra árabe, dígito e espaço, nada mais importa para comparar.
    t = "".join(c if ("ء" <= c <= "ي" or c.isdigit() or c.isspace())
                else " " for c in t)
    palavras = []
    for p in t.split():
        if p.startswith(_ARTIGO) and len(p) > 4:
            p = p[2:]
        if p:
            palavras.append(p)
    return " ".join(palavras)


def chave_latina(nome: str) -> str:
    """A mesma ideia, para nome em alfabeto latino.

    'Al-Hilal', 'Al Hilal' e 'AlHilal' viram a mesma coisa. Acento sai, caixa
    sai, pontuação sai. É a chave que casa o que o Transfermarkt escreve com o
    que a liga escreve.
    """
    import unicodedata
    t = unicodedata.normalize("NFKD", (nome or "")).encode("ascii", "ignore").decode()
    t = "".join(c if (c.isalnum() or c.isspace()) else " " for c in t).lower()
    palavras = []
    for p in t.split():
        # 'alhilal' e 'al hilal' precisam colidir, então o prefixo colado é
        # separado — mas só quando o resto continua sendo uma palavra.
        if p.startswith("al") and len(p) > 4 and p not in ("also", "alan"):
            palavras.append("al")
            palavras.append(p[2:])
        else:
            palavras.append(p)
    return " ".join(x for x in palavras if x)


def chave_colada(chave: str) -> str:
    """A chave sem espaço nenhum.

    Existe por causa de 'عبدالله' contra 'عبد الله' — Abdullah escrito junto ou
    separado. É a divergência mais comum em nome árabe e nenhuma regra de
    letra resolve, porque a diferença é só onde alguém apertou espaço.

    Guardo as duas formas em vez de usar só esta: colar tudo aumenta a chance
    de dois nomes diferentes colidirem, então a busca tenta primeiro a chave
    com espaço e só depois esta.
    """
    return "".join((chave or "").split())
