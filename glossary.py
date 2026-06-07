"""
Glossário de termos do futebol saudita para padronizar traduções.
"""

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
GLOSSARY_PROMPT = """
Glossário obrigatório — use EXATAMENTE estes nomes, SEM hífen, sem variações:
Saudi Pro League: Al Hilal, Al Nassr, Al Ittihad, Al Ahli, Al Shabab, Al Taawoun, Al Fateh, Al Ettifaq, Al Qadsiah, Al Fayha, Al Hazem, Al Khaleej, Al Kholood, Al Najma, Al Okhdood, Al Riyadh, Damac, Neom S.C.
Yelo League (1ª divisão): Abha, Al Adalah, Al Anwar, Al Arabi, Al Batin, Al Bukiryah, Al Diriyah, Al Faisaly, Al Jabalain, Al Jandal, Al Jubail, Al Orobah, Al Raed, Al Shoulla, Al Tai, Al Ula, Al Wahda, Al Zulfi, Jeddah.
Segunda Divisão: Afif, Al Ain, Al Entesar, Al Ghottah, Al Jeel, Al Kawkab, Al Lewaa, Al Nairyah, Al Nojoom, Al Qala, Al Qous, Al Rawdhah, Al Rayyan, Al Sadd, Al Safa, Al Sahel, Al Saqer, Al Sharq, Al Taraji, Al Washm, Arar, Bisha, Hajer, Hetten, Jerash, Jubbah, Mudhar, Najran, Ohod, Tuwaiq, Wej.
Competição: sempre "Saudi Pro League". Yelo League = 1ª divisão. Segunda Divisão = 2ª divisão.
NUNCA use hífen nos nomes dos clubes (Al Hilal, não Al-Hilal).
NUNCA invente nomes — se não reconhecer, translitere do árabe literalmente (ex: الطائي = Al Tai, أبها = Abha).
DISTINÇÃO CRÍTICA: الاتفاق = Al Ettifaq (Dammam) | الاتحاد = Al Ittihad (Jeddah). Nunca confunda.
"""


def apply_glossary(text: str) -> str:
    """Aplica correções pós-tradução no texto."""
    if not text:
        return text
    for wrong, correct in {**CLUB_NAMES, **COMPETITION_NAMES}.items():
        text = text.replace(wrong, correct)
    return text
