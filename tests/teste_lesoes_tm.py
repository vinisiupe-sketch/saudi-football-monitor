"""
Os lesionados da SPL no Transfermarkt, lidos do HTML de verdade.

POR QUE ESTA FONTE ENTROU
    A sub-aba de conferência consultava o endpoint `injuries` da
    API-Football. Ela não trazia nada, e o Vini reclamou com razão: a liga
    saudita tem `coverage.injuries = false` — a API responde com SUCESSO e
    lista VAZIA, para sempre. Uma aba que só sabe dizer "nada" não confere
    coisa nenhuma.

    O Transfermarkt tem a página, com 87 lesionados quando eu conferi
    (11/09/26): jogador, clube, tipo da lesão e data prevista de retorno.

O QUE FAZ ELA VALER MAIS QUE AS OUTRAS: O ID
    A tabela `jogador` deste app já guarda `tm_id`, porque os elencos vêm do
    Transfermarkt. Então o casamento entre a lesão e o jogador não passa por
    nome: é o mesmo número dos dois lados.

    É diferente de tudo que já tentei aqui. O casamento com a SAFF eu tive de
    fazer pela data do jogo, para fugir do árabe x latino. O do monitor por
    notícia depende da transliteração da IA — e é justamente ele que produz
    "Fares Abdy" numa tela e "Faris Abdi" na outra. Este é exato, e de graça.

A ARMADILHA DA DATA
    A página está em inglês e mesmo assim escreve dia/mês/ano ("31/03/2027").
    Se um dia o TM inverter para mês/dia, um retorno de março viraria um de
    31 de... nada. Por isso a conversão recusa mês fora de 01–12: uma
    inversão aparece como data FALTANDO, que é visível, e não como data
    errada, que ninguém percebe.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import lesoes_tm

AMOSTRA = os.path.join(RAIZ, "tests", "amostras", "tm_lesionados_SA1.html")

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def testar():
    falhas.clear()

    # ── 1. a data ────────────────────────────────────────────────────────
    ok(lesoes_tm._data_iso("31/03/2027") == "2027-03-31",
       f"data errada: {lesoes_tm._data_iso('31/03/2027')!r}")
    ok(lesoes_tm._data_iso("28/02/2027") == "2027-02-28", "data errada")
    for ruim in ("?", "", None, "sem data", "31/13/2027"):
        ok(lesoes_tm._data_iso(ruim) == "",
           f"{ruim!r} virou data — mês fora de 01-12 tem que sair vazio, para "
           "uma eventual inversão dia/mês aparecer como falta e não como erro")

    # ── 2. o HTML REAL ───────────────────────────────────────────────────
    ok(os.path.exists(AMOSTRA), f"sumiu a amostra: {AMOSTRA}")
    if not os.path.exists(AMOSTRA):
        for f in falhas:
            print("  ✗", f)
        return len(falhas)

    html = open(AMOSTRA, encoding="utf-8").read()
    r = lesoes_tm.ler_lesionados(html)
    ok(not r["erros"], f"erros ao ler a página real: {r['erros']}")
    ok(len(r["lesoes"]) == 4,
       f"a amostra tem 4 linhas, saíram {len(r['lesoes'])}")

    por_id = {l["tm_id"]: l for l in r["lesoes"]}
    roger = por_id.get("906329")
    ok(roger is not None, f"não achei o Roger Fernandes: {list(por_id)}")
    if roger:
        ok(roger["nome"] == "Roger Fernandes", f"nome: {roger['nome']!r}")
        ok(roger["posicao"] == "Right Winger", f"posição: {roger['posicao']!r}")
        ok(roger["clube"] == "Al-Ittihad Club", f"clube: {roger['clube']!r}")
        ok(roger["clube_tm_id"] == "8023", f"id do clube: {roger['clube_tm_id']!r}")
        ok(roger["lesao"] == "Cruciate ligament tear", f"lesão: {roger['lesao']!r}")
        ok(roger["ate"] == "2027-03-31", f"retorno: {roger['ate']!r}")
        ok(roger["escudo"].startswith("http"), f"escudo: {roger['escudo']!r}")

    # A célula do jogador é uma tabela aninhada — nome numa linha, posição na
    # outra. Se a leitura pegar o bloco inteiro, o "nome" sai com a posição
    # grudada e o casamento por nome (que é o plano B) morre junto.
    for l in r["lesoes"]:
        ok("\n" not in l["nome"] and l["posicao"] not in l["nome"],
           f"o nome saiu com a posição grudada: {l['nome']!r}")

    # Jogador sem data de retorno ("?") continua na lista, sem data inventada.
    sem = por_id.get("222222")
    ok(sem is not None and sem["ate"] == "" and sem["ate_texto"] == "?",
       f"o lesionado sem previsão de retorno saiu errado: {sem}")

    # ── 3. o casamento pelo ID ───────────────────────────────────────────
    elenco = [
        {"tm_id": "906329", "spl_id": "A", "nome": "Roger Fernandes",
         "nome_curto": "Roger", "foto": "f.jpg", "clube": "Al-Ittihad FC"},
        # O elenco escreve o nome de OUTRO jeito: é exatamente o caso que o
        # casamento por id resolve e o casamento por nome erraria.
        {"tm_id": "593337", "spl_id": "B", "nome": "Hamed Al Ghamdi",
         "nome_curto": "H. Al Ghamdi", "foto": "g.jpg", "clube": "Al-Ittihad FC"},
    ]
    n = lesoes_tm.casar_com_elenco(r["lesoes"], elenco)
    ok(n == 2, f"deviam casar 2 pelo id, casaram {n}")
    ok(por_id["593337"].get("nome_elenco") == "Hamed Al Ghamdi",
       "o nome que vai para a tela tem que ser o do ELENCO — é ele que "
       "aparece na escalação, no campinho e nos pendurados. O do TM escreve "
       "'Hamed Al-Ghamdi', com hífen, e o mesmo jogador vira duas pessoas")
    ok(por_id["593337"].get("clube_elenco") == "Al-Ittihad FC",
       "o clube também vem do elenco, senão não casa com o escudo")

    # Quem NÃO está no elenco continua na lista, com o nome do TM e marcado.
    fora = por_id["1033919"]
    ok(fora.get("no_elenco") is False,
       "o jogador fora do elenco não foi marcado como tal — sem essa marca, "
       "a tela mostra o nome do TM achando que é o nome de casa")
    ok(fora.get("nome") == "Mahamadou Doumbia",
       "quem não casa tem que continuar aparecendo. Sumir seria pior: "
       "recém-contratado ainda não está no elenco guardado, e é justamente "
       "dele que ninguém sabe se está machucado")

    # Elenco vazio não derruba nada.
    ok(lesoes_tm.casar_com_elenco(r["lesoes"], []) == 0,
       "elenco vazio devia casar zero, sem estourar")

    # ── 4. falhar de forma visível ───────────────────────────────────────
    # Sem a tabela, o mais provável é bloqueio do TM (ele devolve 403 sem
    # User-Agent) ou mudança de layout. Devolver lista vazia calada passaria
    # por "ninguém machucado" — numa guia de lesões, a leitura errada.
    for entrada in ("", "<html><body>bloqueado</body></html>"):
        s = lesoes_tm.ler_lesionados(entrada)
        ok(s["lesoes"] == [] and s["erros"],
           f"HTML sem tabela devia devolver ERRO, e não silêncio: {s}")
    vazia = lesoes_tm.ler_lesionados('<table class="items"><tbody></tbody></table>')
    ok(vazia["erros"],
       "tabela sem linhas legíveis devia acusar mudança de layout")

    # ── 4b. A VISÃO DETALHADA, com o `since` ─────────────────────────────
    # Foi o Vini quem apontou o /plus/1. A visão simples tem 5 colunas e só a
    # previsão de retorno; a detalhada tem 8 — com Idade e Nacionalidade no
    # meio — e a data em que a lesão COMEÇOU, que é o que põe a entrada no
    # lugar certo da linha do tempo.
    #
    # As colunas são achadas pelo CABEÇALHO, e não pela posição: contando a
    # partir do fim, a leitura funcionava numa versão e lia a nacionalidade
    # como lesão na outra — sem erro nenhum, porque texto é texto.
    DETALHADA = os.path.join(RAIZ, "tests", "amostras",
                             "tm_lesionados_SA1_detalhado.html")
    ok(os.path.exists(DETALHADA), f"sumiu a amostra detalhada: {DETALHADA}")
    if os.path.exists(DETALHADA):
        d = lesoes_tm.ler_lesionados(open(DETALHADA, encoding="utf-8").read())
        ok(not d["erros"], f"erros na visão detalhada: {d['erros']}")
        ok(len(d["lesoes"]) == 2, f"saíram {len(d['lesoes'])} de 2")
        por = {x["tm_id"]: x for x in d["lesoes"]}
        r1 = por.get("906329") or {}
        ok(r1.get("desde") == "2026-09-05",
           f"o `since` saiu como {r1.get('desde')!r} — é ele que diz quando a "
           "lesão começou, e sem ele a entrada no histórico ia carimbada com "
           "a data de hoje")
        ok(r1.get("ate") == "2027-03-31", f"o `until`: {r1.get('ate')!r}")
        ok(r1.get("lesao") == "Cruciate ligament tear",
           f"a lesão saiu como {r1.get('lesao')!r}. Se vier '20' ou "
           "'Portugal', a leitura voltou a contar coluna a partir do fim e "
           "está lendo idade ou nacionalidade no lugar")
        ok(r1.get("clube") == "Al-Ittihad Club", f"clube: {r1.get('clube')!r}")
        # Sem previsão de retorno: campo vazio, e não data inventada.
        r2 = por.get("111111") or {}
        ok(r2.get("desde") == "2026-08-14" and r2.get("ate") == "",
           f"o caso sem previsão de retorno saiu errado: {r2}")

    # ── 5. o download não mora junto com a leitura ───────────────────────
    # httpx importado no topo faria a leitura do HTML depender de biblioteca
    # de rede — e é a leitura que erra, não o download. Mesmo princípio do
    # arbitragem.py. Este teste roda em máquina SEM httpx: se o import subir
    # para o topo, ele nem começa.
    fonte = open(os.path.join(RAIZ, "lesoes_tm.py"), encoding="utf-8").read()
    topo = fonte[:fonte.find("def ")]
    ok("import httpx" not in topo,
       "o httpx subiu para o topo do lesoes_tm. A leitura do HTML tem que ser "
       "testável sem rede — este arquivo de teste é a prova de que era")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ lesões do TM: HTML real lido, casamento pelo id do "
          "Transfermarkt e falha visível quando a página muda")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
