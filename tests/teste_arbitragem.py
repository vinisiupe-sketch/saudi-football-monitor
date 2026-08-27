"""
A leitura do calendário do SAFF e da página do apito.

Os pedaços de HTML aqui não foram inventados: são recortes do que o site
devolveu em 26 e 27/08/2026, sujeira inclusa. Isso importa porque a sujeira é
o teste. Nome em caixa alta, espaço duplo no meio, letra sobrando no fim,
título do jogo colado no nome da competição por um <br> — cada um desses já
seria um defeito silencioso se eu tivesse escrito uma fixture limpa.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arbitragem as arb


CALENDARIO = """
<table><tr><td>Local Events</td><td>International Events</td></tr></table>
<table>
<tr><td colspan="5">Wednesday 26-08-2026</td></tr>
<tr><td colspan="5"><a href="#">(16 National Team) 16 National Team Friendlies</a></td></tr>
<tr><td>18:30</td><td>Hungary</td><td>2 - 0</td><td>Saudi Arabia</td><td>Telki</td></tr>
<tr><td colspan="5"><a href="#">Roshn Saudi League</a></td></tr>
<tr><td>19:00</td><td>Al Faisaly</td><td>1 - 1</td><td>Al Fateh</td>
    <td>Majmaah Sports City (Al-Mjmaah)
      <span class="open-popup" data-url="matchestodayreferee.php?mid=33028&amp;mcode=zaSrhZMdFcYhSuZ926EI2w@3D@3D" title="Referee">
        <img src="../assets/images/whistle2.png" class="whistle-icon"></span></td></tr>
<tr><td>21:00</td><td>Al Diraiyah</td><td>1 - 1</td><td>Al Kholood</td>
    <td>ALAWWAL Park (Riyadh)
      <span class="open-popup" data-url="matchestodayreferee.php?mid=33029&amp;mcode=LMLzK6KnxAkaJsNSbD6NTQ@3D@3D" title="Referee">
        <img src="../assets/images/whistle2.png" class="whistle-icon"></span></td></tr>
<tr><td colspan="5"><a href="#">First Division League</a></td></tr>
<tr><td>18:45</td><td>Al Adalah</td><td>3 - 4</td><td>Al Tai</td>
    <td>Al-Ahsa
      <span class="open-popup" data-url="matchestodayreferee.php?mid=33490&amp;mcode=cUADwj6aA1NH70ixOAIi8w@3D@3D" title="Referee">
        <img src="../assets/images/whistle2.png" class="whistle-icon"></span></td></tr>
<tr><td colspan="5"><a href="#">ACL Two 2025- 2026</a></td></tr>
<tr><td>20:45</td><td>Al Nassr</td><td>0 - 1</td><td>Gamba Osaka - JPN</td>
    <td>ALAWWAL Park (Riyadh)
      <span class="open-popup" data-url="matchestodayreferee.php?mid=34001&amp;mcode=abc@3D@3D" title="Referee">
        <img src="../assets/images/whistle2.png" class="whistle-icon"></span></td></tr>
</table>
"""

APITO = """
<table border="0" class="table-striped">
<tr><td colspan="2" align="center">
Al Faisaly X Al Fateh<br>Roshn Saudi League
</td></tr>
<tr><td>Referee</td><td>Sami Aljurays (Saudi Arabia)</td></tr>
<tr><td>Assistant Referee 1</td><td>Omar Aljamal (Saudi Arabia)</td></tr>
<tr><td>Assistant Referee 2</td><td>Mazen Hadi (Saudi Arabia)</td></tr>
<tr><td>Fourth Official</td><td>Meshal Alshehri (Saudi Arabia)</td></tr>
<tr><td>VAR</td><td>Abdullah Alkhurbush (Saudi Arabia)</td></tr>
<tr><td>AVAR</td><td>Abdullah  Alojaym (Saudi Arabia)</td></tr>
</table>
"""

# Um jogo de ACL, com árbitro estrangeiro — o caso em que chutar 🇸🇦 sairia caro.
APITO_ACL = """
<table>
<tr><td colspan="2">Al Hilal X NEOM<br>ACL Two 2025- 2026</td></tr>
<tr><td>Referee</td><td>Anastasios Sidiropoulos (Greece)</td></tr>
<tr><td>Assistant Referee 1</td><td>Polychronis Kostaras (Greece)</td></tr>
<tr><td>Fourth Official</td><td>Khaled Al Turais (Saudi Arabia)</td></tr>
<tr><td>VAR</td><td>Angelos Evangelou (Greece)</td></tr>
<tr><td>AVAR</td><td>Reinhart Buxbaum (Neverland)</td></tr>
</table>
"""


def testar():
    falhas = []

    def conferir(nome, deu, esperado):
        if deu != esperado:
            falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")

    # ─────────────────────────────────────────────── calendário
    jogos = arb.jogos_do_calendario(CALENDARIO)
    conferir("quantidade com apito", len(jogos), 4)
    conferir("mids", [j["mid"] for j in jogos], [33028, 33029, 33490, 34001])
    conferir("horas", [j["hora"] for j in jogos],
             ["19:00", "21:00", "18:45", "20:45"])
    conferir("competição da linha", jogos[0]["competicao"], "Roshn Saudi League")
    # O &amp; do HTML tem que virar & na URL, senão o mcode chega quebrado e o
    # SAFF devolve página vazia — sem erro, só sem nomes.
    conferir("url sem &amp;", "&amp;" in jogos[0]["url"], False)
    conferir("url absoluta", jogos[0]["url"].startswith(arb.BASE), True)
    # A tabela de navegação do topo não pode virar jogo.
    conferir("nav ignorada", all("Local Events" not in j["linha"] for j in jogos), True)

    # ───────────────────────────────────────────── competições
    conferir("Roshn coberta", arb.competicao_coberta("Roshn Saudi League"), True)
    conferir("Copa do Rei coberta", arb.competicao_coberta("King Cup"), True)
    conferir("Supercopa coberta", arb.competicao_coberta("Saudi Super Cup"), True)
    conferir("ACL coberta", arb.competicao_coberta("ACL Two 2025- 2026"), True)
    conferir("Intercontinental coberta",
             arb.competicao_coberta("FIFA Intercontinental Cup 2026"), True)
    conferir("2ª divisão fora", arb.competicao_coberta("First Division League"), False)
    conferir("sub-16 fora", arb.competicao_coberta("Saudi U-16 Premier League"), False)
    conferir("futsal fora", arb.competicao_coberta("Saudi Futsal League"), False)
    conferir("vazio fora", arb.competicao_coberta(""), False)

    # ─────────────────────────────────────────────── página do apito
    e = arb.escala_da_pagina(APITO)
    # Este é o teste que justifica separar pelo <br>: sem ele, "Al Fateh" vira
    # "Al FatehRoshn Saudi League".
    conferir("casa", e["casa"], "Al Faisaly")
    conferir("fora", e["fora"], "Al Fateh")
    conferir("competição do apito", e["competicao"], "Roshn Saudi League")
    conferir("seis papéis", len(e["papeis"]), 6)
    conferir("primeiro é o árbitro", e["papeis"][0]["papel"], "Referee")
    conferir("país separado do nome", e["papeis"][0]["pais"], "Saudi Arabia")
    conferir("nome sem o país", e["papeis"][0]["nome_saff"], "Sami Aljurays")
    # Espaço duplo no meio do nome, como o SAFF manda.
    conferir("espaço duplo colapsado", e["papeis"][5]["nome_saff"], "Abdullah Alojaym")

    # ─────────────────────────────────────────────── bandeiras
    conferir("bandeira saudita", arb.bandeira("Saudi Arabia"), "🇸🇦")
    conferir("bandeira grega", arb.bandeira("Greece"), "🇬🇷")
    conferir("bandeira kuwaitiana", arb.bandeira("Kuwait"), "🇰🇼")
    conferir("país inventado sem bandeira", arb.bandeira("Neverland"), "")
    conferir("país vazio sem bandeira", arb.bandeira(""), "")
    conferir("caixa não importa", arb.bandeira("  saudi ARABIA "), "🇸🇦")
    acl = arb.escala_da_pagina(APITO_ACL)
    conferir("país sem bandeira é denunciado",
             arb.paises_desconhecidos([acl]), ["Neverland"])

    # ─────────────────────────────────────────────── chave do árbitro
    # Caixa alta, acento e espaço duplo não podem criar árbitro novo.
    conferir("caixa alta mesma chave",
             arb.chave_do_arbitro("KHALID ALJOHANI"),
             arb.chave_do_arbitro("Khalid Aljohani"))
    conferir("espaço duplo mesma chave",
             arb.chave_do_arbitro("Abdullah  Alojaym"),
             arb.chave_do_arbitro("Abdullah Alojaym"))
    conferir("chave de vazio", arb.chave_do_arbitro("   "), "")

    # ─────────────────────────────────────────────── texto
    traducoes = {
        "sami aljurays": "Sami Al Jaris",
        "omar aljamal": "Omar Al Jamal",
        "mazen hadi": "Mazen Hadi",
        "meshal alshehri": "Meshal Al Shehri",
        "abdullah alkhurbush": "Abdullah Al Kharboush",
        "abdullah alojaym": "Abdullah Al Ajeem",
    }
    def traduzir(n):
        return traducoes.get(arb.chave_do_arbitro(n), "")

    jogo = dict(e, mid=33028)
    texto = arb.montar_texto([jogo], traduzir)
    esperado = (
        "👨‍⚖️ 𝐀𝐑𝐁𝐈𝐓𝐑𝐀𝐆𝐄𝐌 𝐃𝐎 𝐃𝐈𝐀\n\n"
        "Al Faisaly x Al Fateh\n"
        "👤 🇸🇦 Sami Al Jaris\n"
        "🚩 🇸🇦 Omar Al Jamal\n"
        "🚩 🇸🇦 Mazen Hadi\n"
        "4️⃣ 🇸🇦 Meshal Al Shehri\n"
        "📟 🇸🇦 Abdullah Al Kharboush\n"
        "📟 🇸🇦 Abdullah Al Ajeem"
    )
    conferir("texto igual ao print", texto, esperado)

    # Sem tradução, o nome do SAFF aparece — e o árbitro entra na lista de
    # pendências. As duas coisas juntas, nunca só uma.
    cru = arb.montar_texto([jogo])
    conferir("sem glossário usa o SAFF", "Sami Aljurays" in cru, True)
    faltando = arb.nomes_sem_traducao([jogo])
    conferir("todos pendentes", len(faltando), 6)
    conferir("nenhum pendente com glossário",
             arb.nomes_sem_traducao([jogo], traduzir), [])
    # O mesmo árbitro em dois jogos não aparece duas vezes na lista.
    conferir("pendência sem repetido",
             len(arb.nomes_sem_traducao([jogo, dict(jogo, mid=99)])), 6)

    # ─────────────────────────────────────────────── nome do clube
    conferir("clube pelo glossário", arb.nome_do_clube("Al Diraiyah"), "Al Diriyah")
    conferir("NEOM em caixa alta", arb.nome_do_clube("NEOM"), "Neom S.C.")
    # Estrangeiro não está na tabela: cai o sufixo do país e usa como veio.
    conferir("estrangeiro sem sufixo",
             arb.nome_do_clube("Gamba Osaka - JPN"), "Gamba Osaka")
    conferir("desconhecido sai como veio",
             arb.nome_do_clube("Clube Que Não Existe"), "Clube Que Não Existe")

    # ──────────────────────────────── contra o HTML de verdade do SAFF
    # Tudo acima roda contra marcação que EU escrevi, e por isso concorda
    # comigo por construção. Estas amostras vieram do site. Já me enganei
    # antes exatamente assim: o teste do canal do YouTube passava porque eu
    # tinha escolhido títulos sem "|", e o mundo real veio cheio deles.
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amostras")

    def amostra(nome):
        with open(os.path.join(pasta, nome), encoding="utf-8") as f:
            return f.read()

    reais = arb.jogos_do_calendario(amostra("calendario_2026-08-26.html"))
    conferir("real: só os com apito", [j["mid"] for j in reais],
             [33028, 33029, 33490])
    conferir("real: horas", [j["hora"] for j in reais],
             ["19:00", "21:00", "18:45"])
    conferir("real: competição da linha", reais[0]["competicao"],
             "Roshn Saudi League")
    # O Intercontinental de 26/08 (Al Ahli x Auckland) NÃO tem apito: o SAFF
    # não escala árbitro de competição da FIFA nem da AFC. Quem cair na guia
    # esperando ver esse jogo precisa entender que a ausência é do site.
    conferir("real: jogo da FIFA sem apito",
             all(j["mid"] != 33012 for j in reais), True)
    conferir("real: amistoso de seleção sem apito",
             all(j["mid"] != 1557 for j in reais), True)
    cobertos = [j for j in reais if arb.competicao_coberta(j["competicao"])]
    conferir("real: dois jogos da Roshn", [j["mid"] for j in cobertos],
             [33028, 33029])

    real_apito = arb.escala_da_pagina(amostra("apito_33029.html"))
    conferir("real: casa", real_apito["casa"], "Al Diraiyah")
    conferir("real: fora", real_apito["fora"], "Al Kholood")
    conferir("real: competição", real_apito["competicao"], "Roshn Saudi League")
    conferir("real: seis papéis", len(real_apito["papeis"]), 6)
    conferir("real: nome do quarto árbitro",
             real_apito["papeis"][3]["nome_saff"], "Mohammed Alghamdi")
    conferir("real: todos com país",
             all(p["pais"] == "Saudi Arabia" for p in real_apito["papeis"]), True)
    # O clube do SAFF passa pelo glossário e vira a grafia do canal.
    conferir("real: clube traduzido no texto",
             "Al Diriyah x Al Kholood" in arb.montar_texto([real_apito]), True)

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    print("  ✓ arbitragem: calendário, apito, bandeiras, glossário e texto")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
