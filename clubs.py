"""
Lista mestre de clubes sauditas — Primeira divisão (Saudi Pro League / SPL) e
Segunda divisão (Yelo League) — com grafias em árabe, alfabeto latino,
transliterações alternativas e variações de hashtag/hífen/espaço.

Fonte: lista fornecida pelo usuário em 2026-06-24, criada justamente pra
resolver o problema recorrente de nomes de clube ausentes/incompletos nas
keywords espalhadas em sources.py/collector.py (ex: "الاتحاد" nunca foi
adicionado, "Al-Ettifaq" com hífen não batia com nada, clubes da Yelo League
como "Al-Diriyah" não existiam em lugar nenhum).

Esse arquivo é a referência central — qualquer clube novo (promoção/rebaixamento,
variação de transliteração) deve ser adicionado aqui, e o matching (via
match_saudi_club / find_saudi_clubs) é usado automaticamente por collector.py
sem precisar tocar em FOOTBALL_REQUIRED/KEYWORDS.
"""
import re

# --- Primeira divisão (Saudi Pro League) ---
_RAW_SPL = """
al-ahli, alahli, al ahli, ahli, al-ahly, alahly, al ahly, ahly, الأهلي, الاهلي, #alahli, #al-ahli, #alahly, #al-ahly, #الأهلي, #الاهلي
al-ettifaq, alettifaq, al ettifaq, ettifaq, al-ittifaq, alittifaq, al ittifaq, ittifaq, الاتفاق, #alettifaq, #al-ettifaq, #alittifaq, #al-ittifaq, #الاتفاق
al-fateh, alfateh, al fateh, fateh, al-fath, alfath, al fath, fath, الفتح, #alfateh, #al-fateh, #alfath, #al-fath, #الفتح
al-fayha, alfayha, al fayha, fayha, al-feiha, alfeiha, al feiha, feiha, al-faiha, alfaiha, al faiha, faiha, الفيحاء, #alfayha, #al-fayha, #alfeiha, #al-feiha, #alfaiha, #al-faiha, #الفيحاء
al-hazem, alhazem, al hazem, hazem, al-hazm, alhazm, al hazm, hazm, الحزم, #alhazem, #al-hazem, #alhazm, #al-hazm, #الحزم
al-hilal, alhilal, al hilal, hilal, الهلال, #alhilal, #al-hilal, #الهلال
al-ittihad, alittihad, al ittihad, ittihad, al-ittihad jeddah, ittihad jeddah, الاتحاد, #alittihad, #al-ittihad, #ittihadjeddah, #الاتحاد
al-khaleej, alkhaleej, al khaleej, khaleej, al-khalij, alkhalij, al khalij, khalij, الخليج, #alkhaleej, #al-khaleej, #alkhalij, #al-khalij, #الخليج
al-kholood, alkholood, al kholood, kholood, al-khlood, alkhlood, al khlood, khlood, al-khulood, alkhulood, al khulood, khulood, al-kholud, alkholud, al kholud, kholud, الخلود, #alkholood, #al-kholood, #alkhulood, #al-khulood, #alkholud, #al-kholud, #الخلود
al-najmah, alnajmah, al najmah, najmah, al-najma, alnajma, al najma, najma, النجمة, #alnajmah, #al-najmah, #alnajma, #al-najma, #النجمة
al-nassr, alnassr, al nassr, nassr, al-nasr, alnasr, al nasr, nasr, النصر, #alnassr, #al-nassr, #alnasr, #al-nasr, #النصر
al-okhdood, alokhdood, al okhdood, okhdood, al-okhdud, alokhdud, al okhdud, okhdud, al-akhdoud, alakhdoud, al akhdoud, akhdoud, al-ukhdood, alukhdood, al ukhdood, ukhdood, الأخدود, الاخدود, #alokhdood, #al-okhdood, #alokhdud, #al-okhdud, #alakhdoud, #al-akhdoud, #الأخدود, #الاخدود
al-qadsiah, alqadsiah, al qadsiah, qadsiah, al-qadisiyah, alqadisiyah, al qadisiyah, qadisiyah, al-qadisiya, alqadisiya, al qadisiya, qadisiya, al-quadisiya, alquadisiya, al quadisiya, quadisiya, القادسية, #alqadsiah, #al-qadsiah, #alqadisiyah, #al-qadisiyah, #alqadisiya, #al-qadisiya, #alquadisiya, #al-quadisiya, #القادسية
al-riyadh, alriyadh, al riyadh, riyadh, al-riyad, alriyad, al riyad, riyad, الرياض, #alriyadh, #al-riyadh, #alriyad, #al-riyad, #الرياض
al-shabab, alshabab, al shabab, shabab, الشباب, #alshabab, #al-shabab, #الشباب
al-taawoun, altaawoun, al taawoun, taawoun, al-taawon, altaawon, al taawon, taawon, al-ta'awoun, altaawun, al taawun, taawun, التعاون, #altaawoun, #al-taawoun, #altaawon, #al-taawon, #altaawun, #al-taawun, #التعاون
damac, damac fc, damac club, damak, damak fc, dhamk, dhamk club, ضمك, #damac, #damacfc, #damak, #dhamk, #ضمك
neom, neom sc, neom s.c., neom sports club, نيوم, #neom, #neomsc, #نيوم
"""

# --- Segunda divisão (Yelo League) ---
_RAW_YELO = """
abha, abha club, abha fc, أبها, ابها, #abha, #abhaclub, #abhafc, #أبها, #ابها
al-faisaly, alfaisaly, al faisaly, faisaly, al-faysaly, alfaysaly, al faysaly, faysaly, al-faisali, alfaisali, al faisali, faisali, الفيصلي, #alfaisaly, #al-faisaly, #alfaysaly, #al-faysaly, #alfaisali, #al-faisali, #الفيصلي
al-diraiyah, aldiraiyah, al diraiyah, diraiyah, al-diriyah, aldiriyah, al diriyah, diriyah, al-deriyah, alderiyah, al deriyah, deriyah, diriyah club, الدرعية, #aldiraiyah, #al-diraiyah, #aldiriyah, #al-diriyah, #alderiyah, #al-deriyah, #الدرعية
al-ula, alula, al ula, ula, al-ula fc, al ula fc, alula fc, al-ola, alola, al ola, ola, alula club, العلا, العُلا, #alula, #al-ula, #alolafc, #al-ola, #العلا, #العُلا
al-orobah, alorobah, al orobah, orobah, al-orubah, alorubah, al orubah, orubah, al-orouba, alorouba, al orouba, orouba, al-aruba, alaruba, al aruba, aruba, العروبة, #alorobah, #al-orobah, #alorubah, #al-orubah, #alorouba, #al-orouba, #العروبة
al-jabalain, aljabalain, al jabalain, jabalain, al-jableen, aljableen, al jableen, jableen, al-jabalein, aljabalein, al jabalein, jabalein, الجبلين, #aljabalain, #al-jabalain, #aljableen, #al-jableen, #aljabalein, #al-jabalein, #الجبلين
al-raed, alraed, al raed, raed, al-ra'ed, alra'ed, al ra'ed, ra'ed, al-raid, alraid, al raid, الرائد, #alraed, #al-raed, #alraid, #al-raid, #الرائد
al-zulfi, alzulfi, al zulfi, zulfi, al-zulfi sfc, zulfi sfc, الزلفي, #alzulfi, #al-zulfi, #zulfisfc, #الزلفي
al-tai, altai, al tai, tai, al-taee, altaee, al taee, taee, al-ta'ee, alta'ee, al ta'ee, ta'ee, al-tay, altay, al tay, tay, الطائي, #altai, #al-tai, #altaee, #al-taee, #altay, #al-tay, #الطائي
al-wehda, alwehda, al wehda, wehda, al-wahda, alwahda, al wahda, wahda, al-wihda, alwihda, al wihda, wihda, al-wehda mecca, al-wahda mecca, الوحدة, #alwehda, #al-wehda, #alwahda, #al-wahda, #alwihda, #al-wihda, #الوحدة
al-bukiryah, albukiryah, al bukiryah, bukiryah, al-bukayriyah, albukayriyah, al bukayriyah, bukayriyah, al-bukairiyah, albukairiyah, al bukairiyah, bukairiyah, البكيرية, #albukiryah, #al-bukiryah, #albukayriyah, #al-bukayriyah, #albukairiyah, #al-bukairiyah, #البكيرية
al-anwar, alanwar, al anwar, anwar, الأنوار, الانوار, #alanwar, #al-anwar, #الأَنوار, #الأنوار, #الانوار
jeddah, jeddah sc, jeddah club, jeddah fc, jidda, jiddah, جدة, #jeddah, #jeddahsc, #jeddahclub, #jiddah, #jidda, #جدة
al-adalah, aladalah, al adalah, adalah, al-adala, aladala, al adala, adala, al-adalh, aladalh, العدالة, #aladalah, #al-adalah, #aladala, #al-adala, #العدالة
al-jandal, aljandal, al jandal, jandal, al-jandal sc, al jandal sc, الجندل, #aljandal, #al-jandal, #aljandalsc, #al-jandal-sc, #الجندل
al-batin, albatin, al batin, batin, al-baten, albaten, al baten, baten, al-batin fc, الباطن, #albatin, #al-batin, #albaten, #al-baten, #الباطن
al-arabi, alarabi, al arabi, arabi, al-araby, alaraby, al araby, araby, al-arabi unaizah, al-arabi unayzah, العربي, #alarabi, #al-arabi, #alaraby, #al-araby, #العربي
al-jubail, aljubail, al jubail, jubail, al-jubayl, aljubayl, al jubayl, jubayl, الجبيل, #aljubail, #al-jubail, #aljubayl, #al-jubayl, #الجبيل
"""


def _parse(raw: str) -> dict[str, list[str]]:
    clubs: dict[str, list[str]] = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        variants = [v.strip() for v in line.split(",") if v.strip()]
        if not variants:
            continue
        key = (
            variants[0]
            .replace("#", "")
            .replace("-", "_")
            .replace(" ", "_")
            .replace("'", "")
        )
        # Remove duplicatas preservando ordem (a lista bruta tem alguma repetição)
        clubs[key] = list(dict.fromkeys(variants))
    return clubs


SPL_CLUBS: dict[str, list[str]] = _parse(_RAW_SPL)
YELO_CLUBS: dict[str, list[str]] = _parse(_RAW_YELO)
ALL_CLUBS: dict[str, list[str]] = {**SPL_CLUBS, **YELO_CLUBS}

# Variantes "arriscadas": formas isoladas (sem hífen/sufixo/hashtag) que coincidem
# com palavra genérica do dicionário árabe/inglês ou com nome de cidade/projeto
# saudita que aparece o tempo todo em noticiário NÃO esportivo. Confirmado por
# casos reais sinalizados pelo usuário em 2026-06-24 (ex: "مجلس التعاون لدول
# الخليج العربية" = Conselho de Cooperação do Golfo, bateu em Al-Taawoun + Al-Khaleej
# sem ter nada a ver com futebol).
# Essas formas só contam como sinal de clube se OUTRO sinal claro também estiver
# presente no texto — formas com hífen/espaço+sufixo/hashtag (#alkhaleej, "al-khaleej",
# "jeddah sc"...) continuam diretas, pois aí a intenção de citar o clube é explícita.
RISKY_VARIANTS: frozenset[str] = frozenset(v.lower() for v in [
    # Al-Khaleej — "الخليج"/"khaleej" bare = "golfo" (geográfico/político, comum)
    "الخليج", "khaleej",
    # Al-Taawoun — "التعاون" bare = "cooperação" (ex: Conselho de Cooperação do Golfo)
    "التعاون", "taawoun", "taawon", "taawun",
    # Al-Shabab — "الشباب" bare = "jovens/juventude" (usado em qualquer contexto)
    "الشباب", "shabab",
    # Al-Fateh — "الفتح" bare = "a conquista/abertura" (histórico/religioso)
    "الفتح", "fateh", "fath",
    # Al-Ettifaq — "الاتفاق" bare = "o acordo" (político/comercial, muito comum)
    "الاتفاق",
    # Al-Qadsiah — "القادسية" é também a famosa batalha histórica de Qadisiyyah
    "القادسية", "qadsiah", "qadisiyah", "qadisiya", "quadisiya",
    # Al-Riyadh — "الرياض"/"riyadh" bare = a capital saudita, citada em qualquer notícia do país
    "الرياض", "riyadh", "riyad",
    # Jeddah — "جدة"/"jeddah" bare = a cidade, citada em qualquer notícia do país
    "جدة", "jeddah", "jidda", "jiddah",
    # Al-Wehda — "الوحدة" bare = "a unidade" (político/social, muito comum)
    "الوحدة", "wehda", "wahda", "wihda",
    # Al-Adalah — "العدالة" bare = "a justiça" (jurídico/político, muito comum)
    "العدالة", "adalah", "adala",
    # Al-Arabi — "العربي"/"arabi" bare = "o árabe" (adjetivo genérico extremamente comum)
    "العربي", "arabi", "araby",
    # NEOM — "نيوم"/"neom" bare = megaprojeto saudita, constante em noticiário de
    # negócios/turismo sem relação com o clube de futebol NEOM SC
    "نيوم", "neom",
    # Al-Diriyah — "الدرعية" bare = sítio histórico/turístico (Diriyah Gate), muito
    # noticiado fora do contexto do clube
    "الدرعية", "diriyah", "diraiyah", "deriyah",
    # Al-Ula — "العلا"/"alula" bare = destino turístico/patrimônio mundial (AlUla),
    # muito noticiado fora do contexto do clube
    "العلا", "العُلا", "ula", "alula", "ola", "alola",
    # Abha — "أبها"/"abha" bare = capital da região de Asir, cidade turística
    "أبها", "ابها", "abha",
    # Al-Jubail — "الجبيل"/"jubail" bare = grande cidade industrial/petroquímica
    "الجبيل", "jubail", "jubayl",
    # Al-Najmah — "النجمة" bare = "a estrela/celebridade" (genérico, comum)
    "النجمة", "najmah", "najma",
])


def _build_pattern(variants: set[str]) -> re.Pattern:
    """
    Regex única com fronteiras de palavra em vez de simples substring "in" —
    necessário porque a lista tem variantes curtas (ex: "tai", "ola", "tay",
    "fath") que apareceriam dentro de palavras comuns em inglês ("obtain",
    "father", "cola") se fosse um match de substring ingênuo. Hashtags
    (#al-ahli) já começam com um caractere não-alfanumérico, então a fronteira
    do início é satisfeita naturalmente.

    Fronteira usa (?<![^\\W_]) / (?![^\\W_]) em vez do \\w padrão — propositalmente
    trata "_" como fronteira válida (não como caractere de palavra), porque
    hashtags árabes no Twitter costumam juntar palavras com underscore
    (#الهلال_السعودي, #دوري_روشن_السعودي). Com \\b/\\w puro, "الهلال" dentro de
    "الهلال_السعودي" não bateria, pois "_" conta como \\w e bloquearia a
    fronteira — bug real descoberto ao validar os casos do usuário em 2026-06-24.

    Variantes com mais de uma palavra (ex: "al ahli", "jeddah sc") também
    precisam casar quando o separador real no texto é "_" em vez de espaço
    (mesmo motivo acima) — por isso o espaço escapado vira [\\s_]+ no lugar de
    um espaço literal.
    """
    if not variants:
        return re.compile(r"(?!)")  # nunca bate
    escaped = sorted(
        (re.escape(v).replace(r"\ ", r"[\s_]+") for v in variants),
        key=len, reverse=True,
    )
    pattern = r"(?<![^\W_])(?:" + "|".join(escaped) + r")(?![^\W_])"
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


def _all_variants_lower() -> set[str]:
    variants: set[str] = set()
    for vs in ALL_CLUBS.values():
        variants.update(v.lower() for v in vs)
    return variants


_ALL_VARIANTS_LOWER = _all_variants_lower()
_SAFE_VARIANTS = _ALL_VARIANTS_LOWER - RISKY_VARIANTS
_RISKY_PRESENT = _ALL_VARIANTS_LOWER & RISKY_VARIANTS

_SAFE_PATTERN = _build_pattern(_SAFE_VARIANTS)
_RISKY_PATTERN = _build_pattern(_RISKY_PRESENT)


def match_saudi_club(text: str) -> bool:
    """True se o texto citar um clube saudita (SPL ou Yelo) de forma segura —
    qualquer grafia/transliteração/hashtag, EXCETO as formas isoladas que
    colidem com palavra genérica ou nome de cidade/projeto (ver RISKY_VARIANTS).
    Usado para satisfazer o gate "é sobre futebol" e como hit direto."""
    if not text:
        return False
    return bool(_SAFE_PATTERN.search(text.lower()))


def match_saudi_club_risky(text: str) -> bool:
    """True se o texto citar uma forma 'arriscada' (ver RISKY_VARIANTS) — só
    deve contar como sinal adicional se outro sinal claro também estiver
    presente, nunca como prova isolada de contexto futebolístico saudita."""
    if not text:
        return False
    return bool(_RISKY_PATTERN.search(text.lower()))


def find_saudi_clubs(text: str) -> list[str]:
    """Retorna as chaves dos clubes citados no texto (pode ter mais de um),
    considerando tanto variantes seguras quanto arriscadas."""
    if not text:
        return []
    text_lower = text.lower()
    found = []
    for key, variants in ALL_CLUBS.items():
        for v in variants:
            v_pattern = re.escape(v.lower()).replace(r"\ ", r"[\s_]+")
            if re.search(r"(?<![^\W_])" + v_pattern + r"(?![^\W_])", text_lower):
                found.append(key)
                break
    return found
