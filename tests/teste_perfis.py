"""
A leitura da página de jogador da liga — de onde vem a data de nascimento.

POR QUE ESTE ARQUIVO EXISTE
    A página não é JSON. É dado de RSC do Next embutido no HTML, com as aspas
    escapadas, e os objetos de jogador vêm colados um no outro. Pior: a MESMA
    página traz DUAS listas. Uma com biografia completa (nascimento, altura,
    nacionalidade) e outra só com nome, número e foto — a lista do elenco.

    Isso cria a chance de erro mais perigosa deste passo: um jogador da lista
    curta, que não tem data nenhuma, herdar a data do jogador anterior por eu
    procurar "o dateOfBirth mais próximo". O resultado seria uma data errada,
    completa, plausível, gravada com a mesma confiança de uma certa — e a data
    é justamente a chave que vai casar as fontes. Um erro aqui não aparece:
    ele vira uma estatística atribuída à pessoa errada, meses depois.

    Por isso a leitura corta o texto no PRÓXIMO playerId, e por isso o teste
    mais importante daqui é o de número 2.

SOBRE A AMOSTRA
    O formato abaixo foi copiado de uma página real (spl.com.sa/en/players/
    abdou-diallo/, agosto de 2026): mesmas chaves, mesma ordem, mesmo
    escapamento `\\"`, mesmo objeto `team` aninhado depois dos campos da
    pessoa, e as duas listas na ordem em que aparecem.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import perfil_spl

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


# ── a amostra ──────────────────────────────────────────────────────────────
# Primeiro a biografia completa (com o objeto `team` no meio, que também tem
# um shortName — o da EQUIPE, não o da pessoa), depois a lista curta do
# elenco, onde ninguém tem data.
BIO = (
    r'\"playerId\":\"spl::Football_Player::c5dc\",'
    r'\"playerSlug\":\"abdou-diallo\",'
    r'\"mediaFirstName\":\"Abdou\",\"mediaLastName\":\"Diallo\",'
    r'\"shirtName\":\"A. Diallo\",\"shortName\":\"A. Diallo\",'
    r'\"roleLabel\":\"Defender\",\"weight\":\"87\",\"height\":\"187\",'
    r'\"nationality\":\"Senegal\",\"nationalityIsoCode\":\"SEN\",'
    r'\"dateOfBirth\":\"1996-05-04T00:00:00Z\",'
    r'\"playerStatus\":\"Active\",\"bibNumber\":\"22\",'
    # A seção de biografia traz a URL INTEIRA. A da lista curta traz o
    # caminho. As duas convivem na mesma página, e só uma serve para a coluna.
    r'\"playerImage\":\"https://media-sdp.spl.com.sa/playerImages/c5dc_middle.webp\",'
    r'\"team\":{\"teamSlug\":\"abha\",\"officialName\":\"Abha\",'
    r'\"mediaShortName\":\"Abha\",\"shortName\":\"Abha\",\"height\":\"999\"},'
)
CURTA = (
    r'\"playerId\":\"spl::Football_Player::b49f\",'
    r'\"bibNumber\":\"\",\"roleLabel\":\"Defender\",'
    r'\"mediaFirstName\":\"Nawaf\",\"mediaLastName\":\"Al Ghulaimish\",'
    r'\"nationality\":\"Saudi Arabia\",\"nationalityIsoCode\":\"KSA\",'
    r'\"imagery\":{\"playerImage_home_middle\":\"playerImages/b49f_middle.webp\"},'
)
SEGUNDA_BIO = (
    r'\"playerId\":\"spl::Football_Player::b49f\",'
    r'\"playerSlug\":\"nawaf-al-ghulaimish\",'
    r'\"mediaFirstName\":\"Nawaf\",\"mediaLastName\":\"Al Ghulaimish\",'
    r'\"height\":\"180\",\"nationality\":\"Saudi Arabia\",'
    r'\"dateOfBirth\":\"1997-02-02T00:00:00Z\",\"bibNumber\":\"4\",'
)
# Uma TERCEIRA pessoa, com biografia, logo depois da lista curta.
#
# Ela existe por causa de um erro meu: a primeira versão deste teste punha a
# lista curta no FIM da amostra, e por isso passava mesmo com a leitura
# quebrada. O vazamento não vem de trás, vem da frente — quem procura sem
# limite acha o dateOfBirth do PRÓXIMO jogador, não o do anterior. Sem alguém
# depois da lista curta, não há o que vazar, e o teste não testava nada.
TERCEIRA_BIO = (
    r'\"playerId\":\"spl::Football_Player::3c97\",'
    r'\"playerSlug\":\"bader-al-mutairi\",'
    r'\"mediaFirstName\":\"Bader\",\"mediaLastName\":\"Al Mutairi\",'
    r'\"height\":\"175\",\"nationality\":\"Saudi Arabia\",'
    r'\"dateOfBirth\":\"2003-04-18T00:00:00Z\",\"bibNumber\":\"28\",'
)
# Lixo de HTML que também contém a palavra height, para o caso de alguém
# trocar o corte por uma busca solta.
LIXO = '<img width=48 height=48 decoding=async src="x.webp">'

PAGINA = (f"<html><body>{LIXO}{BIO}{CURTA}{TERCEIRA_BIO}"
          f"{SEGUNDA_BIO}{LIXO}</body></html>")

# A página em árabe é a MESMA página noutro idioma: mesmos ids, nomes na outra
# escrita. A segunda aparição do c5dc vem sem nome — como na lista curta — e
# está aqui para provar que ela não apaga o nome que a primeira trouxe.
PAGINA_AR = (
    r'\"playerId\":\"spl::Football_Player::c5dc\",'
    r'\"mediaFirstName\":\"عبدو\",\"mediaLastName\":\"ديالو\",'
    r'\"dateOfBirth\":\"1996-05-04T00:00:00Z\",'
    r'\"playerId\":\"spl::Football_Player::3c97\",'
    r'\"mediaFirstName\":\"بدر\",\"mediaLastName\":\"المطيري\",'
    r'\"dateOfBirth\":\"2003-04-18T00:00:00Z\",'
    # Terceira aparição do c5dc: tem data, mas os nomes vieram vazios. É essa
    # combinação que dá trabalho — a entrada não pode ser descartada inteira
    # (a data serve) e ao mesmo tempo o nome vazio não pode sobrescrever o que
    # a primeira trouxe.
    r'\"playerId\":\"spl::Football_Player::c5dc\",'
    r'\"mediaFirstName\":\"\",\"mediaLastName\":\"\",'
    r'\"dateOfBirth\":\"1996-05-04T00:00:00Z\",\"bibNumber\":\"22\",'
)


class ClienteFalso:
    """Devolve a página de quem eu pedir, no idioma que eu pedir."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.pedidos = []

    def get(self, url, **k):
        self.pedidos.append(url)
        corpo = ""
        for chave, texto in self.paginas.items():
            if f"/players/{chave}/" in url:
                corpo = PAGINA_AR if "/ar/players/" in url else texto
                break

        class R:
            status_code = 200 if corpo else 404
            text = corpo
        return R()


def testar():
    falhas.clear()

    # ── 1. lê o que está lá ────────────────────────────────────────────────
    gente = perfil_spl.desdobrar(PAGINA)
    diallo = gente.get("spl::Football_Player::c5dc") or {}
    conferir("nascimento", diallo.get("nascimento"), "1996-05-04")
    conferir("altura", diallo.get("altura"), "187")
    conferir("nome", diallo.get("nome"), "Abdou Diallo")
    conferir("slug", diallo.get("slug"), "abdou-diallo")
    conferir("nacionalidade", diallo.get("nac_iso"), "SEN")
    conferir("camisa", diallo.get("camisa"), "22")
    # A foto é o CAMINHO de `imagery`, não a URL inteira de `playerImage`.
    # A coluna guarda caminho desde a varredura de escalação; misturar os dois
    # formatos na mesma coluna quebraria a montagem do endereço na tela.
    conferir("foto é o caminho de imagery",
             (gente.get("spl::Football_Player::b49f") or {}).get("foto"),
             "playerImages/b49f_middle.webp")
    ok(not (diallo.get("foto") or "").startswith("http"),
       "guardei a URL inteira em vez do caminho")

    # ── 2. E NÃO lê o que NÃO está lá ──────────────────────────────────────
    # Este é o teste que justifica o arquivo. O segundo jogador aparece duas
    # vezes: uma na lista curta, sem data nenhuma, e outra na longa, com a
    # dela. Se a leitura pegasse "a data mais próxima", a entrada curta
    # levaria 1996-05-04 — a data do Diallo — e ninguém veria.
    # A lista curta fica ENTRE duas biografias. Sem alguém depois dela não há
    # o que vazar, porque a busca de um campo anda para a frente.
    so_curta = perfil_spl.desdobrar(f"<html>{BIO}{CURTA}{TERCEIRA_BIO}</html>")
    nawaf = so_curta.get("spl::Football_Player::b49f") or {}
    conferir("o da lista curta veio", nawaf.get("nome"), "Nawaf Al Ghulaimish")
    ok("nascimento" not in nawaf,
       "o jogador SEM data herdou a data do jogador SEGUINTE — "
       "o corte no próximo playerId falhou")
    ok("altura" not in nawaf,
       "o jogador SEM altura herdou a altura do seguinte")
    ok((so_curta.get("spl::Football_Player::3c97") or {}).get("nascimento")
       == "2003-04-18",
       "e o dono da data continua com ela")

    # ── 3. mas as duas aparições se completam ──────────────────────────────
    conferir("a bio da segunda lista chega no mesmo id",
             (gente.get("spl::Football_Player::b49f") or {}).get("nascimento"),
             "1997-02-02")
    conferir("e a altura também",
             (gente.get("spl::Football_Player::b49f") or {}).get("altura"), "180")

    # ── 3b. o clube da página vale para todo mundo da página ───────────────
    # Isso não é palpite: conferi que a página do Diallo tem 29 jogadores e um
    # único teamSlug, a do Salem tem 29 e outro único, e não há uma pessoa em
    # comum entre as duas. A lista é o elenco do clube.
    conferir("o clube chega em quem só aparece na lista curta",
             (gente.get("spl::Football_Player::b49f") or {}).get("clube"), "Abha")
    conferir("e no dono da página também", diallo.get("clube"), "Abha")
    # Mas se a premissa cair — dois clubes na mesma página — eu não escolho.
    dois = perfil_spl.desdobrar(
        PAGINA + BIO.replace(r'\"abha\"', r'\"al-hilal\"')
                    .replace(r'\"officialName\":\"Abha\"',
                             r'\"officialName\":\"Al Hilal\"'))
    ok(not any(p.get("clube") for p in dois.values()),
       "com dois clubes na mesma página eu escolhi um em vez de deixar vazio")
    conferir("e o resto continua sendo lido",
             (dois.get("spl::Football_Player::3c97") or {}).get("nascimento"),
             "2003-04-18")

    # ── 4. o `team` aninhado não contamina a pessoa ────────────────────────
    # O objeto do clube vem DEPOIS dos campos da pessoa e tem chaves com o
    # mesmo nome. Se a leitura pegasse a última ocorrência em vez da primeira,
    # a altura do Diallo viraria 999.
    conferir("altura é a da pessoa, não a do objeto do clube",
             diallo.get("altura"), "187")

    # ── 5. o árabe entra sem apagar o latim ────────────────────────────────
    cli = ClienteFalso({"abdou-diallo": PAGINA})
    perfil_spl.colher("abdou-diallo", cli, com_arabe=False)
    conferir("sem árabe, uma requisição", len(cli.pedidos), 1)

    cli2 = ClienteFalso({"abdou-diallo": PAGINA})
    j = perfil_spl.colher("abdou-diallo", cli2)
    conferir("com árabe, duas requisições", len(cli2.pedidos), 2)
    d = j.get("spl::Football_Player::c5dc") or {}
    conferir("nome árabe", d.get("nome_ar"), "عبدو ديالو")
    conferir("e o latino continua lá", d.get("nome"), "Abdou Diallo")
    # A segunda aparição do mesmo id na página árabe vem sem nome. Se ela
    # sobrescrevesse, a coluna ficaria vazia — e vazia é pior que ausente,
    # porque parece que a fonte não tem o dado.
    #
    # Conferido DENTRO de `desdobrar`, e não pelo resultado de `colher`:
    # `colher` tem a sua própria guarda contra vazio, e ela escondia o defeito
    # aqui. Duas guardas é bom; testar as duas pela de fora é o mesmo que
    # testar só uma.
    ar = perfil_spl.desdobrar(PAGINA_AR, arabe=True)
    conferir("a aparição SEM nome não apaga o nome árabe da primeira",
             (ar.get("spl::Football_Player::c5dc") or {}).get("nome_ar"),
             "عبدو ديالو")
    ok("nome" not in (ar.get("spl::Football_Player::c5dc") or {}),
       "a passada em árabe inventou um nome latino")

    # ── 6. o slug ──────────────────────────────────────────────────────────
    conferir("slug simples", perfil_spl.slug_de("Abdou Diallo"), "abdou-diallo")
    conferir("slug com acento", perfil_spl.slug_de("Donovan Léon"), "donovan-leon")
    conferir("slug com hífen", perfil_spl.slug_de("Al-Dawsari"), "al-dawsari")
    conferir("slug vazio", perfil_spl.slug_de(""), "")

    # ── 7. o chute do slug é CONFERIDO ─────────────────────────────────────
    # Chutar o slug pelo nome erra para quem tem nome do meio. O erro aceitável
    # é não achar; o inaceitável é achar a página de OUTRA pessoa e gravar o
    # elenco dela por cima. Por isso a página só vale se falar do id pedido.
    cli3 = ClienteFalso({"abdou-diallo": PAGINA})
    colhido, como = perfil_spl.colher_a_partir_de(
        [{"spl_id": "spl::Football_Player::NAO_EXISTE", "nome": "Abdou Diallo"}],
        cli3)
    conferir("página que não fala de quem eu procurei é descartada", colhido, {})
    conferir("e isso é contado", como.get("paginas_sem_serventia"), 1)

    cli4 = ClienteFalso({"abdou-diallo": PAGINA})
    colhido, como = perfil_spl.colher_a_partir_de(
        [{"spl_id": "spl::Football_Player::c5dc", "nome": "Abdou Diallo"}], cli4)
    conferir("página certa rende o elenco inteiro", len(colhido), 3)
    conferir("uma página lida", como.get("paginas_lidas"), 1)

    # ── 7b. a porta pode ser um colega que já está completo ────────────────
    # O caso real: nove do Al Khaleej sem nome em árabe. O slug deles é longo
    # e o chute erra. Quem abriria a página do clube é o 'Raed Al Shanqiti',
    # de nome curto — mas ele já estava completo, e por isso ficava de fora
    # da lista de candidatos. Resultado: a página do Al Khaleej nunca era
    # aberta de novo e os nove não saíam do lugar em rodada nenhuma.
    elencos = {
        "Al Khaleej": [
            {"spl_id": "porta", "nome": "Raed Al Shanqiti", "clube": "Al Khaleej"},
            {"spl_id": "preso", "nome": "Abdulmajeed Abdullah Fehaid Al Khathami",
             "clube": "Al Khaleej"},
        ],
    }
    faltam = [{"spl_id": "preso",
               "nome": "Abdulmajeed Abdullah Fehaid Al Khathami",
               "clube": "Al Khaleej"}]
    sementes, clubes = perfil_spl.sementes_para(
        faltam, lambda c: elencos.get(c, []))
    conferir("o clube de quem falta é visitado", clubes, ["Al Khaleej"])
    ok(any(s["spl_id"] == "porta" for s in sementes),
       "o colega já completo não entrou como porta — os presos continuam presos")
    ok(sementes[0]["spl_id"] == "porta",
       "a porta de nome curto tem que ser tentada antes da de nome longo")

    # Um clube com alguém incompleto aparece UMA vez, não uma por pessoa.
    muitos = [{"spl_id": f"p{i}", "nome": f"Fulano {i}", "clube": "Al Khaleej"}
              for i in range(30)]
    _, clubes = perfil_spl.sementes_para(muitos, lambda c: elencos.get(c, []))
    conferir("clube repetido conta uma vez", clubes, ["Al Khaleej"])

    # Quem não tem clube não some: aí não há elenco onde procurar uma porta,
    # e o próprio nome é a única tentativa possível.
    sementes, clubes = perfil_spl.sementes_para(
        [{"spl_id": "solto", "nome": "Sem Clube", "clube": ""}],
        lambda c: elencos.get(c, []))
    conferir("sem clube, nenhum clube visitado", clubes, [])
    conferir("mas ele mesmo é tentado",
             [s["spl_id"] for s in sementes], ["solto"])

    # ── 8. o teto existe ───────────────────────────────────────────────────
    cli5 = ClienteFalso({})
    _, como = perfil_spl.colher_a_partir_de(
        [{"spl_id": f"id{i}", "nome": f"Fulano {i}"} for i in range(200)],
        cli5, teto=3)
    conferir("o teto de páginas é respeitado", como.get("paginas_tentadas"), 3)

    # ── 9. página vazia não vira nada ──────────────────────────────────────
    conferir("html vazio", perfil_spl.desdobrar(""), {})
    conferir("html sem jogador", perfil_spl.desdobrar("<html>oi</html>"), {})

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ perfis: nascimento e altura da página da liga, sem herdar do vizinho")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
