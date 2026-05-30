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
Clubes: Al Hilal, Al Nassr, Al Ittihad, Al Ahli, Al Shabab, Al Taawoun, Al Fateh, Al Ettifaq,
Al Qadsiah, Al Fayha, Al Hazem, Al Khaleej, Al Kholood, Al Najma, Al Okhdood, Al Riyadh,
Al Diriyah, Al Ula, Damac, Neom S.C.
Competição: sempre "Saudi Pro League" (nunca "Liga Saudita" ou "Campeonato Saudita").
NUNCA use hífen nos nomes dos clubes (Al Hilal, não Al-Hilal).
"""


def apply_glossary(text: str) -> str:
    """Aplica correções pós-tradução no texto."""
    if not text:
        return text
    for wrong, correct in {**CLUB_NAMES, **COMPETITION_NAMES}.items():
        text = text.replace(wrong, correct)
    return text
