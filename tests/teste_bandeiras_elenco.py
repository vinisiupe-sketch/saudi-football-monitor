"""
Toda nacionalidade que existe no elenco de verdade vira bandeira.

O QUE ACONTECEU (03/09/26)
    A escalação do PDF saía sem bandeirinha nenhuma, e sem erro em lugar
    nenhum. A causa: a tabela `jogador` vem da API da própria liga, e ela
    escreve a nacionalidade EM ÁRABE — "السعودية" para 255 dos 573
    jogadores. A tabela de bandeiras só tinha grafia latina, então
    `bandeira()` devolvia "" para quase todo mundo e o post saía limpo.

    Levou dias porque os três elos da corrente (cruzar pela camisa, ter
    nacionalidade, saber desenhar o país) davam exatamente o mesmo resultado
    na tela quando quebravam.

A LISTA ABAIXO É DADO REAL
    Foi tirada do /api/diag/escalacao rodando contra o banco de produção, no
    dia em que o defeito apareceu. Não é amostra inventada: é o conjunto de
    grafias que os 573 jogadores do elenco de fato têm. Se a liga passar a
    escrever um país de um jeito novo, é aqui que a falta aparece — e o
    diagnóstico já entrega a linha pronta para colar.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import arbitragem

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


# Grafias vistas no elenco real, com quantos jogadores cada uma tinha.
NO_ELENCO = [
    ("السعودية", 255), ("فرنسا", 22), ("البرازيل", 12), ("البرتغال", 12),
    ("إسبانيا", 10), ("السنغال", 10), ("المغرب", 7), ("الجزائر", 6),
    ("صربيا", 5), ("هولندا", 4), ("غينيا", 4), ("بلجيكا", 3),
    ("الكاميرون", 3), ("الكونغو الديمقراطية", 3), ("إنجلترا", 3),
    ("أوروغواي", 3), ("غامبيا", 3), ("غانا", 3), ("ساحل العاج", 3),
    ("ألبانيا", 2), ("الرأس الأخضر", 2), ("سلوفاكيا", 2), ("مالي", 2),
    ("غينيا بيساو", 2), ("أرمينيا", 1), ("ألمانيا", 1), ("إسكتلندا", 1),
    ("إيطاليا", 1), ("الأردن", 1), ("البوسنة والهرسك", 1), ("السويد", 1),
    ("الغابون", 1), ("الكونغو", 1), ("المكسيك", 1), ("النرويج", 1),
    ("اليونان", 1), ("بلغاريا", 1), ("بنما", 1), ("بولندا", 1),
    ("تركيا", 1), ("توغو", 1), ("تونس", 1), ("جزر القمر", 1),
    ("رواندا", 1), ("رومانيا", 1), ("زامبيا", 1), ("سورينام", 1),
    ("غيانا الفرنسية", 1), ("غينيا الاستوائية", 1), ("كرواتيا", 1),
    ("كندا", 1), ("كوراساو", 1), ("كوسوفو", 1), ("كولومبيا", 1),
    ("لوكسمبورغ", 1), ("ليبيريا", 1), ("ليتوانيا", 1), ("مصر", 1),
    # As latinas que também faltavam — o elenco tem as duas grafias.
    ("cabo verde", 1), ("ecuador", 1), ("new caledonia", 1), ("niger", 1),
    ("slovakia", 1), ("venezuela", 1),
]


def testar():
    falhas.clear()

    orfas = [(p, n) for p, n in NO_ELENCO if not arbitragem.bandeira(p)]
    perdidos = sum(n for _, n in orfas)
    for pais, n in orfas:
        falhas.append(f'"{pais}" não vira bandeira — {n} jogador(es) do elenco '
                      "sairiam sem bandeirinha no post")
    ok(not orfas,
       f"ao todo {perdidos} jogadores ficariam sem bandeira")

    # Algumas conferências de valor, e não só de existência: um país mapeado
    # para a sigla errada passa despercebido — a bandeira aparece, só que do
    # país errado, o que é pior que não aparecer.
    esperado = {"السعودية": "🇸🇦", "البرازيل": "🇧🇷", "البرتغال": "🇵🇹",
                "المغرب": "🇲🇦", "فرنسا": "🇫🇷", "السنغال": "🇸🇳",
                "الجزائر": "🇩🇿", "مصر": "🇪🇬", "الأردن": "🇯🇴",
                "أوروغواي": "🇺🇾", "الكونغو الديمقراطية": "🇨🇩",
                "الكونغو": "🇨🇬"}
    for pais, bandeira_certa in esperado.items():
        deu = arbitragem.bandeira(pais)
        if deu != bandeira_certa:
            falhas.append(f'"{pais}": esperava {bandeira_certa}, veio {deu!r}')

    # A grafia latina não pode ter se perdido no caminho: o mesmo elenco tem
    # as duas, e o árbitro (que usa esta mesma tabela) vem em inglês.
    for pais, bandeira_certa in (("Saudi Arabia", "🇸🇦"), ("Brazil", "🇧🇷"),
                                 ("Portugal", "🇵🇹"), ("Morocco", "🇲🇦")):
        deu = arbitragem.bandeira(pais)
        if deu != bandeira_certa:
            falhas.append(f"a grafia latina '{pais}' quebrou: veio {deu!r}")

    # País desconhecido continua devolvendo vazio, e não uma bandeira errada.
    for nada in ("", "   ", "Atlântida", None):
        if arbitragem.bandeira(nada) != "":
            falhas.append(f"{nada!r} devolveu bandeira — inventar país é pior "
                          "que não ter bandeira")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ bandeiras: as 64 grafias do elenco real viram bandeira, em "
          "árabe e em latim")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
