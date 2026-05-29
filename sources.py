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
        "a_alhanyan", "majed_ma_10", "meejo_19", "Maaalnews",
        "Khvayaclubs", "NYF_5", "I_ABO3TB", "H_swilhy",
        "nawaf__oga", "zlatan_gh", "a_altamimi11", "Ali_alabdallh",
        "JacobsBen", "Santi_J_FM", "geglobo", "sachatavolieri",
        "FabriceHawkins", "DiMarzio", "Plettigoal", "sebsousapinto",
    ],
    "rss_feeds": [
        # Google News — fallback confiável
        "https://news.google.com/rss/search?q=Saudi+Pro+League+football&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Saudi+Arabia+football+transfer&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=futebol+Arabia+Saudita+Saudi+Pro+League&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://news.google.com/rss/search?q=%D9%83%D8%B1%D8%A9+%D8%A7%D9%84%D9%82%D8%AF%D9%85+%D8%A7%D9%84%D8%B3%D8%B9%D9%88%D8%AF%D9%8A%D8%A9&hl=ar&gl=SA&ceid=SA:ar",
        # Sites especializados
        "https://www.arabnews.com/taxonomy/term/305/feed",
        "https://saudigazette.com.sa/section/sports/feed",
        "https://www.goal.com/feeds/en/news",
        "http://feeds.bbci.co.uk/sport/football/rss.xml",
        "https://ge.globo.com/rss/feed.xml",
    ],
}

TIER_C = {
    "twitter_accounts": [
        "ariyadhiah", "khaled_alhussan", "A_Ragab", "AHADI4",
        "OKAZ_online", "AlArabiya_spt", "ahmed_aljadi68",
        "SultanALotaibi0", "samialqadi800", "k7aled_otb",
        "lequipe", "NicoSchira", "Glongari", "yagosabuncuoglu",
    ],
    "rss_feeds": [
        "https://www.lequipe.fr/rss/actu_rss_Football.xml",
        "https://theathletic.com/rss",
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
    ],
    "portuguese": [
        "arábia saudita", "liga saudita", "futebol saudita",
        "al-hilal", "al-nassr", "al-ittihad", "al-ahli",
        "saudi pro league",
    ],
    "arabic": [
        "السعودي", "الدوري السعودي", "الهلال", "النصر", "الاتحاد",
        "الأهلي", "الشباب", "الفتح", "التعاون", "الاتفاق",
        "كرة القدم السعودية", "روشن", "دوري روشن",
    ],
    "spanish": ["arabia saudita", "liga saudi", "al hilal", "al nassr"],
    "french": ["arabie saoudite", "championnat saoudien", "ligue saoudienne"],
    "italian": ["arabia saudita", "campionato saudita"],
}

TIER_WEIGHTS = {"A": 3, "B": 2, "C": 1}
