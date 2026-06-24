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


def _build_pattern(clubs: dict[str, list[str]]) -> re.Pattern:
    """
    Regex única com todas as variantes, usando fronteiras de palavra
    ((?<!\\w) / (?!\\w)) em vez de simples substring "in" — necessário porque
    a lista tem variantes curtas (ex: "tai", "raid", "ola", "tay", "fath")
    que apareceriam dentro de palavras comuns em inglês ("obtain", "father",
    "cola") se fosse um match de substring ingênuo. Hashtags (#al-ahli) já
    começam com um caractere não-alfanumérico, então a fronteira do início
    é satisfeita naturalmente.
    """
    variants: set[str] = set()
    for vs in clubs.values():
        variants.update(v.lower() for v in vs)
    escaped = sorted((re.escape(v) for v in variants), key=len, reverse=True)
    pattern = r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)"
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


_CLUB_PATTERN = _build_pattern(ALL_CLUBS)


def match_saudi_club(text: str) -> bool:
    """True se o texto citar qualquer clube saudita (SPL ou Yelo), em
    qualquer grafia/transliteração/variação de hashtag conhecida."""
    if not text:
        return False
    return bool(_CLUB_PATTERN.search(text))


def find_saudi_clubs(text: str) -> list[str]:
    """Retorna as chaves dos clubes citados no texto (pode ter mais de um)."""
    if not text:
        return []
    text_lower = text.lower()
    found = []
    for key, variants in ALL_CLUBS.items():
        for v in variants:
            if re.search(r"(?<!\w)" + re.escape(v.lower()) + r"(?!\w)", text_lower):
                found.append(key)
                break
    return found
