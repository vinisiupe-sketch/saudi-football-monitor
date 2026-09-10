"""
Toda nacionalidade que aparece no elenco tem que virar bandeira.

O QUE ACONTECEU (09/09/26)
    A escalação do dia saiu com sete avisos de "país sem bandeira cadastrada":
    Lithuania, Suriname, Curaçao, French Guiana, Comoros, Togo, Albania,
    Bosnia and Herzegovina, Congo DR.

    O engraçado é que todos esses países JÁ estavam na tabela — em árabe.
    Faltava só a grafia latina. A tabela `PAISES` foi escrita à mão e cresceu
    por remendo: cada país novo que aparecia virava uma linha nova. Consertar
    aqueles sete e seguir a vida garantiria que a próxima rodada traria o
    oitavo.

COMO FICOU RESOLVIDO
    Uma segunda tabela, `PAISES_ISO`, com a ISO 3166-1 inteira escrita de uma
    vez. `PAISES` continua e continua tendo prioridade — é onde moram o árabe,
    os apelidos das fontes ("KSA", "UAE", "China PR") e as decisões já tomadas.
    E um índice sem acento por cima das duas, porque as fontes escrevem
    "Curaçao" e "Curacao" — às vezes as duas no mesmo dia.

O QUE ESTE ARQUIVO VIGIA
    Que os nove países do incidente continuem saindo com bandeira; que a
    tabela feita à mão não perca a prioridade (senão apelido e árabe param de
    valer); que acento não seja diferença; e que país que eu não conheço
    continue devolvendo "" em vez de uma bandeira errada.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import arbitragem as arb

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _iso(emoji: str) -> str:
    """A bandeira de volta em letras — 🇧🇷 vira "BR"."""
    return "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in emoji)


def testar():
    falhas.clear()

    # ── 1. os nove do incidente ──────────────────────────────────────────
    DO_INCIDENTE = {
        "Lithuania": "LT", "Suriname": "SR", "Curaçao": "CW",
        "French Guiana": "GF", "Comoros": "KM", "Togo": "TG",
        "Albania": "AL", "Bosnia and Herzegovina": "BA", "Congo DR": "CD",
    }
    for pais, sigla in DO_INCIDENTE.items():
        b = arb.bandeira(pais)
        ok(b != "", f'"{pais}" voltou a sair sem bandeira — foi um dos sete '
                    "que apareceram na escalação de 09/09/26")
        if b:
            ok(_iso(b) == sigla,
               f'"{pais}" saiu com {_iso(b)} e deveria ser {sigla}')

    # ── 2. o árabe e os apelidos continuam valendo ───────────────────────
    # A tabela da ISO não tem "KSA" nem "السعودية". Se ela passasse na frente
    # da feita à mão, metade do elenco (a metade cuja nacionalidade vem em
    # árabe da API da liga) perderia a bandeira de novo — e em silêncio.
    for pais, sigla in (("السعودية", "SA"), ("البرازيل", "BR"), ("KSA", "SA"),
                        ("UAE", "AE"), ("China PR", "CN"),
                        ("Korea Republic", "KR")):
        b = arb.bandeira(pais)
        ok(b != "" and _iso(b) == sigla,
           f'"{pais}" deveria dar {sigla} e deu {_iso(b) if b else "nada"} — '
           "a tabela escrita à mão tem que continuar tendo prioridade")

    # ── 2b. quando as duas tabelas discordam, a feita à mão ganha ────────
    # Hoje elas não discordam em lugar nenhum — conferi. Por isso este teste
    # FABRICA a divergência: senão a regra de prioridade estaria valendo por
    # coincidência, e o dia em que alguém puser uma linha conflitante o
    # comportamento mudaria sem nada acusar.
    #
    # O caso real que isso protege: a ISO diz que Inglaterra e Escócia têm
    # bandeira própria; aqui a decisão foi mandar as duas como Reino Unido,
    # porque bandeira de subdivisão não desenha em boa parte dos aparelhos.
    # Essa decisão mora na tabela feita à mão e precisa vencer.
    arb.PAISES["paisdeteste"] = "BR"
    arb.PAISES_ISO["paisdeteste"] = "AR"
    arb._montar_indice()
    try:
        ok(_iso(arb.bandeira("paisdeteste")) == "BR",
           "com as duas tabelas discordando, quem ganhou foi a da ISO. A "
           "feita à mão é que guarda as decisões já tomadas e os apelidos "
           "das fontes — ela tem que vencer")
        ok(_iso(arb.bandeira("PAISDETESTE")) == "BR",
           "a prioridade se perde quando a entrada vem em caixa alta")
    finally:
        arb.PAISES.pop("paisdeteste", None)
        arb.PAISES_ISO.pop("paisdeteste", None)
        arb._montar_indice()

    # ── 3. acento não é diferença ────────────────────────────────────────
    for com, sem in (("Curaçao", "Curacao"), ("Türkiye", "Turkiye"),
                     ("Réunion", "Reunion")):
        ok(arb.bandeira(com) == arb.bandeira(sem) != "",
           f'"{com}" e "{sem}" deveriam dar a mesma bandeira: '
           f"{arb.bandeira(com)!r} vs {arb.bandeira(sem)!r}")

    # Caixa e espaço sobrando também não são.
    ok(arb.bandeira("  BRAZIL  ") == arb.bandeira("brazil") != "",
       "caixa alta ou espaço sobrando mudou o resultado")

    # ── 4. o que eu não sei continua sem bandeira ────────────────────────
    # Este é o ponto que importa mais do que parece: inventar uma bandeira
    # errada é pior que não pôr nenhuma. Sem bandeira, o Vini vê que falta;
    # com a bandeira errada, ele publica um sírio como sueco.
    for nada in ("", "   ", "Wakanda", "xyz", "país", "12"):
        ok(arb.bandeira(nada) == "",
           f'"{nada}" produziu uma bandeira — país desconhecido tem que sair '
           'vazio, e não com um palpite')

    # ── 5. a tabela da ISO está inteira e bem formada ────────────────────
    ok(len(arb.PAISES_ISO) >= 200,
       f"a tabela da ISO ficou com {len(arb.PAISES_ISO)} entradas — ela "
       "existe justamente para não voltar a ser uma lista de remendos")
    for nome, sigla in arb.PAISES_ISO.items():
        ok(nome == nome.lower().strip(),
           f'a chave "{nome}" não está em minúsculas: a busca normaliza a '
           "entrada para minúscula e nunca acharia esta linha")
        ok(len(sigla) == 2 and sigla.isascii() and sigla.isupper(),
           f'"{nome}" está com a sigla {sigla!r}, e a bandeira é montada a '
           "partir de duas letras maiúsculas")

    # ── 6. uma escalação de verdade sai inteira ──────────────────────────
    # Os países dos onze do Al Kholood e do Abha em 09/09/26, que era o jogo
    # em que o aviso apareceu.
    DO_JOGO = ["Saudi Arabia", "Guinea", "Spain", "France", "Lithuania",
               "Suriname", "Curaçao", "French Guiana", "Belgium", "Colombia",
               "Portugal", "Croatia", "Senegal", "Brazil", "Uruguay",
               "Algeria", "Morocco", "Netherlands", "Serbia", "Comoros",
               "Togo", "Albania", "Bosnia and Herzegovina", "Congo DR"]
    sem = [p for p in DO_JOGO if not arb.bandeira(p)]
    ok(not sem, f"ainda saem sem bandeira: {sem}")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ bandeiras: ISO inteira, árabe e apelidos com prioridade, "
          "acento ignorado e nada inventado")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
