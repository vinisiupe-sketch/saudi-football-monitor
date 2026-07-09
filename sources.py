"""
Fontes monitoradas — organizadas por Tier de confiança.
"""

TIER_A = {
    # Twitter/X — prioridade máxima, sem RSS neste tier
    "twitter_accounts": [
        "saifmoalsaif", "bandar_52", "alaa_saeed88",
        "FabrizioRomano", "CLMerlo", "andrehernan",
        "venecasagrande", "MatteMoretto",
    ],
    "rss_feeds": [],
}

TIER_B = {
    "twitter_accounts": [
        "ariyadhiah_br", "aawsat_spt", "Rabanalsafena", "13saeed",
        "a_alhanyan", "majed_ma_10", "meejo_19",
        "Khvayaclubs", "NYF_5", "I_ABO3TB", "H_swilhy",
        "nawaf__oga", "zlatan_gh", "a_altamimi11", "Ali_alabdallh",
        "JacobsBen", "Santi_J_FM", "geglobo", "sachatavolieri",
        "FabriceHawkins", "DiMarzio", "Plettigoal", "sebsousapinto",
    ],
    "rss_feeds": [
        # arriyadiyah.com — principal jornal esportivo saudita. Única fonte RSS ativa.
        # Coletado via Google News (site:) para obter conteúdo completo dos artigos.
        "https://news.google.com/rss/search?q=site:arriyadiyah.com&hl=ar&gl=SA&ceid=SA:ar",
    ],
}

TIER_C = {
    "twitter_accounts": [
        # ariyadhiah removido do Twitter — hashtags em excesso nos tweets impediam
        # a coleta. Substituído por RSS via Google News (site:arriyadiyah.com) no
        # TIER_B.rss_feeds acima, que entrega o conteúdo completo dos artigos.
        "khaled_alhussan", "A_Ragab", "AHADI4",
        "OKAZ_online", "ahmed_aljadi68",
        "SultanALotaibi0", "samialqadi800", "k7aled_otb",
        "lequipe", "NicoSchira", "Glongari", "yagosabuncuoglu", "ahmad2man",
    ],
    "rss_feeds": [
        # Apenas RSS Saudi-específico; lequipe/athletic têm futebol global
        "https://news.google.com/rss/search?q=Saudi+Pro+League+rumor+transfer+2025&hl=en&gl=US&ceid=US:en",
    ],
}

TWITTER_RSS_PROVIDERS = [
    # RSSHub próprio (self-hosted no Railway com credenciais do X) — prioridade máxima
    "https://rsshub-production-794a.up.railway.app/twitter/user/{username}",
    # Fallbacks públicos (podem falhar de cloud)
    "https://rsshub.app/twitter/user/{username}",
    "https://nitter.poast.org/{username}/rss",
]

KEYWORDS = {
    "english": [
        "saudi", "spl", "saudi pro league", "roshn",
        "al hilal", "al nassr", "al ittihad", "al ahli",
        "al qadsiah", "al shabab", "al fateh", "al taawoun",
        "al ettifaq", "al wahda", "damac", "abha", "al fayha",
        "saudi football", "saudi league", "saudi arabia football",
        # Variante sem espaço/hífen — formato comum de hashtag (#AlAhli, #AlNassr...)
        "alhilal", "alnassr", "alittihad", "alahli", "alqadsiah",
        "alshabab", "alfateh", "altaawoun", "alettifaq", "alwahda", "alfayha",
        # Variante com hífen — grafia padrão da mídia em inglês (Al-Ettifaq, Al-Fayha...)
        # (al-hilal/al-nassr/al-ittihad/al-ahli já cobertos na lista "portuguese" abaixo)
        "al-qadsiah", "al-shabab", "al-fateh", "al-taawoun",
        "al-ettifaq", "al-wahda", "al-fayha",
    ],
    "portuguese": [
        "arábia saudita", "liga saudita", "futebol saudita",
        "al-hilal", "al-nassr", "al-ittihad", "al-ahli",
        "saudi pro league",
    ],
    "arabic": [
        # Termos exclusivamente sauditas
        "السعودي", "الدوري السعودي", "كرة القدم السعودية", "روشن", "دوري روشن",
        "دوري روشن السعودي للمحترفين",
        # Clubes sauditas (nomes próprios — não ambíguos)
        "الهلال", "النصر", "الأهلي", "الخلود",
        "الفيحاء", "الحزم", "النجمة", "الأخدود", "ضمك",
        "الاتحاد",  # Al Ittihad — clube saudita (estava faltando: nunca tinha sido
                    # adicionado de fato, só citado em comentário — bug real, ficava sem nenhum hit)
        # القادسية/الخليج/الاتفاق/التعاون/الشباب/الفتح foram REMOVIDOS daqui de propósito.
        # São palavras árabes genéricas (golfo/acordo/cooperação/jovens/conquista/batalha
        # histórica) que também são nomes de clube — confirmado por falsos positivos reais
        # em 2026-06-24 (reunião do Conselho de Cooperação do Golfo, jogadores jovens da
        # seleção mexicana). Tratá-las como keyword direta aqui as deixava sempre "diretas"
        # mesmo pra fontes Twitter com strict_ambiguous=False, contornando a defesa em
        # AMBIGUOUS_ARABIC. Agora são tratadas EXCLUSIVAMENTE via RISKY_VARIANTS/
        # match_saudi_club_risky em clubs.py, que exige corroboração sempre — não importa
        # o tipo de fonte. Não devolva esses termos pra esta lista sem reavaliar isso.
        # Termos de transferência/futebol em árabe — alto sinal quando combinados com clube
        "مدرب",     # treinador/coach
        "لاعب",     # jogador
        "صفقة", "صفقات",  # contratação/transferências
        "انتقال", "انتقالات",  # transferência
        "إعارة",    # empréstimo
        "رحيل",     # saída/partida
        "عقد",      # contrato
        "تعاقد",    # assinar contrato
        "تجديد",    # renovação
    ],
    "spanish": ["arabia saudita", "liga saudi", "al hilal", "al nassr"],
    "french": ["arabie saoudite", "championnat saoudien", "ligue saoudienne"],
    "italian": ["arabia saudita", "campionato saudita"],
    # Emoji de bandeira — sinal forte e não-ambíguo de Arábia Saudita,
    # comum em tweets de mercado de transferências (ex: "#AlAhli 🇸🇦")
    "symbols": ["🇸🇦"],
}

TIER_WEIGHTS = {"A": 3, "B": 2, "C": 1}

# Lua de confiabilidade por fonte (🌕 mais confiável → 🌗 menos)
SOURCE_MOON = {
    "saifmoalsaif":    "🌕",
    "bandar_52":       "🌕",
    "alaa_saeed88":    "🌕",
    "FabrizioRomano":  "🌕",
    "CLMerlo":         "🌕",
    "andrehernan":     "🌕",
    "venecasagrande":  "🌕",
    "MatteMoretto":    "🌕",
    "ariyadhiah_br":   "🌖",
    "aawsat_spt":      "🌖",
    "Rabanalsafena":   "🌖",
    "13saeed":         "🌖",
    "a_alhanyan":      "🌖",
    "majed_ma_10":     "🌖",
    "meejo_19":        "🌖",
    "Khvayaclubs":     "🌖",
    "NYF_5":           "🌖",
    "I_ABO3TB":        "🌖",
    "H_swilhy":        "🌖",
    "nawaf__oga":      "🌖",
    "zlatan_gh":       "🌖",
    "a_altamimi11":    "🌖",
    "Ali_alabdallh":   "🌖",
    "JacobsBen":       "🌖",
    "Santi_J_FM":      "🌖",
    "geglobo":         "🌖",
    "sachatavolieri":  "🌖",
    "FabriceHawkins":  "🌖",
    "DiMarzio":        "🌖",
    "Plettigoal":      "🌖",
    "sebsousapinto":   "🌖",
    "ariyadhiah":      "🌗",
    "khaled_alhussan": "🌗",
    "A_Ragab":         "🌗",
    "AHADI4":          "🌗",
    "OKAZ_online":     "🌗",
    "ahmed_aljadi68":  "🌗",
    "SultanALotaibi0": "🌗",
    "samialqadi800":   "🌗",
    "k7aled_otb":      "🌗",
    "lequipe":         "🌗",
    "NicoSchira":      "🌗",
    "Glongari":        "🌗",
    "yagosabuncuoglu": "🌗",
    "ahmad2man":       "🌗",
}
