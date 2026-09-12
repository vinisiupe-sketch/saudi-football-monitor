"""
Reconhecer QUAL jogo da liga é a transmissão do canal.

O QUE ACONTECEU (12/09/26)
    Al Nassr x Al Khaleej, pela Saudi Pro League, no ar — e sem botão de
    gravar na guia de Clipes.

    A guia só oferece para gravar o que ela reconhece como jogo da liga. O
    reconhecimento lia o título assim: "os dois times antes da primeira barra,
    separados por um X". É um bom palpite sobre um título, e é um palpite
    sobre um texto que o Vini escreve à mão, no celular, minutos antes de o
    jogo começar.

    Qualquer uma destas variações derrubava o casamento:

        "AO VIVO | AL NASSR X AL KHALEEJ | ..."   o padrão não é o 1º pedaço
        "🔴 AL NASSR X AL KHALEEJ | ..."          emoji colado no nome
        "AL NASSR X AL KHALEEJ AO VIVO | ..."     sem barra antes do resto
        "AL NASSR x AL KHALEEJ - SAUDI ..."       traço em vez de barra

    E derrubava em SILÊNCIO: o jogo virava "não é da liga", era filtrado, e a
    tela dizia que o canal não estava transmitindo nada.

A INVERSÃO
    Em vez de "que jogo este título descreve?", que exige entender o título,
    a segunda tentativa pergunta "qual dos jogos de HOJE tem os dois clubes
    citados aqui?". O formato deixa de importar.

    É seguro porque a lista é curta, porque exige os DOIS clubes, e porque
    desiste quando mais de um jogo responde. Casar por um clube só, num dia
    de nove partidas, gravaria a partida errada — e gravação errada tem toda a
    cara de certa até alguém assistir.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import liga_spl

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _jogo(casa, fora):
    return {"home": {"shortName": casa}, "away": {"shortName": fora}}


# A rodada de 12/09/26, que é quando isto apareceu.
RODADA = [
    _jogo("Al Nassr", "Al Khaleej"),
    _jogo("Al Hilal", "Al Ahli"),
    _jogo("Al Ittihad", "Al Fateh"),
    _jogo("Al Qadsiah", "Al Taawoun"),
]


def _casou(titulo):
    j = liga_spl.achar_jogo(titulo, RODADA)
    if not j:
        return ""
    return f"{j['home']['shortName']} x {j['away']['shortName']}"


def testar():
    falhas.clear()
    ALVO = "Al Nassr x Al Khaleej"

    # ── 1. o formato de sempre continua funcionando ──────────────────────
    for t in ("AL NASSR X AL KHALEEJ | AO VIVO | SAUDI PRO LEAGUE",
              "AL KHALEEJ X AL NASSR | AO VIVO | SAUDI PRO LEAGUE",
              "AL-NASSR X AL-KHALEEJ | AO VIVO",
              "Al Nassr vs Al Khaleej | Saudi Pro League"):
        ok(_casou(t) == ALVO, f"o formato de sempre parou de casar: {t!r}")

    # ── 2. as variações que custaram o jogo de 12/09 ─────────────────────
    for t in ("AO VIVO | AL NASSR X AL KHALEEJ | SAUDI PRO LEAGUE",
              "\U0001F534 AL NASSR X AL KHALEEJ | AO VIVO | SAUDI PRO LEAGUE",
              "AL NASSR X AL KHALEEJ AO VIVO | SAUDI PRO LEAGUE",
              "AL NASSR x AL KHALEEJ - SAUDI PRO LEAGUE",
              "AO VIVO: AL NASSR RECEBE O AL KHALEEJ PELA SAUDI PRO LEAGUE",
              "SAUDI PRO LEAGUE | AL NASSR X AL KHALEEJ | 4ª RODADA"):
        ok(_casou(t) == ALVO,
           "o título não foi reconhecido e o jogo sumiria da lista de gravar: "
           f"{t!r}")

    # ── 3. O QUE ELE NÃO PODE FAZER ──────────────────────────────────────
    # Errar aqui não erra de leve: grava a partida errada, e gravação errada
    # parece certa até alguém assistir.
    ok(_casou("CRISTIANO RONALDO JOGA HOJE | SAUDI PRO LEAGUE") == "",
       "título sem clube nenhum casou com um jogo")
    ok(_casou("AL NASSR: A PREPARAÇÃO PARA A RODADA") == "",
       "UM clube só bastou para casar. Num dia de nove jogos isso grava a "
       "partida errada")
    ok(_casou("") == "", "título vazio casou com alguma coisa")
    # Dois jogos inteiramente citados: não sei de qual é a transmissão, e
    # escolher um seria escolher no escuro.
    ok(_casou("AL NASSR X AL KHALEEJ E AL HILAL X AL AHLI, AO VIVO") == "",
       "com dois jogos citados por inteiro, escolheu um. Desistir é o certo: "
       "não dá para saber qual está no ar")
    # Clube que não joga hoje não inventa jogo.
    ok(_casou("AL NASSR X AL RIYADH | AO VIVO") == "",
       "casou um confronto que não está no calendário de hoje")

    # ── 4. NOME DE CLUBE NÃO PODE CASAR DENTRO DE OUTRA PALAVRA ─────────
    # O glossário tem variantes de três letras: 'ola' é Al Ula, 'tai' e 'tay'
    # são Al Tai. Sem fronteira de palavra, "GOLAÇO" cita o Al Ula e "STAY"
    # cita o Al Tai — e aí um título perfeitamente comum passa a citar quatro
    # clubes, dois jogos ficam possíveis, e a transmissão certa é recusada por
    # ambiguidade que eu mesmo inventei.
    #
    # O título é de propósito um dos que o leitor de FORMATO não resolve
    # (começa com "AO VIVO |"), senão a primeira tentativa acertaria antes e a
    # segunda nunca seria exercitada — o teste passaria sem testar nada.
    rodada_curta = RODADA + [_jogo("Al Ula", "Al Tai")]
    j = liga_spl.achar_jogo("AO VIVO | AL HILAL X AL AHLI | GOLAÇO! STAY TUNED",
                            rodada_curta)
    ok(j and j["home"]["shortName"] == "Al Hilal",
       "'GOLAÇO' e 'STAY' passaram a citar o Al Ula e o Al Tai porque o nome "
       "do clube casou DENTRO de outra palavra. O jogo certo some por "
       "ambiguidade inventada")

    rodada_neom = [_jogo("NEOM", "Damac"), _jogo("Al Hilal", "Al Ahli")]
    j = liga_spl.achar_jogo("NEOM X DAMAC | AO VIVO", rodada_neom)
    ok(j and j["home"]["shortName"] == "NEOM",
       "o jogo do NEOM parou de ser reconhecido")

    # Variante de uma ou duas letras nunca entra na busca, mesmo que alguém
    # acrescente uma ao glossário um dia. Com fronteira de palavra ela exigiria
    # a letra solta — e "X" ou "E" soltos existem em qualquer título.
    import glossary as _g
    _orig = _g.variantes_de_clube
    _g.variantes_de_clube = lambda: dict(_orig(), **{"x": "Al Hilal"})
    try:
        # Um clube real citado (Al Ahli) mais o "X" solto do título, que a
        # variante de uma letra transformaria numa citação ao Al Hilal — e os
        # dois juntos fecham um jogo que não está no ar.
        ok(liga_spl.achar_jogo("AL AHLI ANALISA X RODADA DA SAUDI PRO LEAGUE",
                               [_jogo("Al Hilal", "Al Ahli")]) == {},
           "uma variante de uma letra entrou na busca: o 'X' que separa os "
           "times do título virou citação a um clube, e um programa de "
           "estúdio passou a ser oferecido como jogo para gravar")
    finally:
        _g.variantes_de_clube = _orig

    # ── 4b. o leitor de FORMATO ainda serve para o que a inversão não pega ─
    # A inversão depende do glossário conhecer os dois clubes. Time recém
    # promovido, ou escrito de um jeito que ninguém cadastrou, só é reconhecido
    # pelo caminho antigo — que continua vindo primeiro por isso.
    desconhecido = [_jogo("Klube Novo FC", "Outro Clube SC")]
    j = liga_spl.achar_jogo("KLUBE NOVO FC X OUTRO CLUBE SC | AO VIVO",
                            desconhecido)
    ok(j != {},
       "o leitor de formato sumiu. Ele é o único caminho para um clube que o "
       "glossário ainda não conhece — e clube novo aparece toda temporada")

    # ── 5. o leitor de título continua devolvendo os dois nomes ──────────
    # Ele é usado também pelo clipe automático (mesmo_jogo). Se ele mudar de
    # contrato, quebra lá, e lá o prejuízo é clipe da partida errada.
    a, b = liga_spl.clubes_do_titulo("AL NASSR X AL KHALEEJ | AO VIVO")
    ok((a, b) == ("AL NASSR", "AL KHALEEJ"),
       f"clubes_do_titulo mudou de contrato: devolveu {(a, b)!r}")
    ok(liga_spl.mesmo_jogo("AL NASSR X AL KHALEEJ | AO VIVO",
                           "Al-Nassr", "Al Khaleej"),
       "mesmo_jogo (o clipe automático) parou de reconhecer o confronto")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ título da transmissão: reconhece o jogo sem depender do formato")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
