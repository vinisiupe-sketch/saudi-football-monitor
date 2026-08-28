"""
Quem a notícia está falando.

O QUE PODE DAR ERRADO AQUI, E POR QUE É PIOR QUE PARECE
    O erro que importa não é deixar de achar. É achar a pessoa ERRADA.

    Um jogador não encontrado é uma notícia sem foto — você vê e reclama. Um
    jogador errado colado numa notícia é uma foto errada no card, com cara de
    certa, assinada por você no ar. E como o elo depois vira hyperlink e
    estatística, o estrago não fica onde nasceu.

    Por isso quase todo teste daqui é sobre o que a regra RECUSA. São 573
    jogadores: 'محمد' aparece em dezenas deles, 'الدوسري' em vários. Qualquer
    regra que aceite palavra solta transforma toda notícia sobre o Al-Hilal
    numa notícia sobre sete pessoas.

O QUE ESTE ARQUIVO ACEITA PERDER
    'Al Dawsari marcou' não é encontrado, e está certo assim: existem dois Al
    Dawsari na liga. A regra é nome completo, na ordem. Quando eu tiver uma
    forma MEDIDA de usar o clube da notícia para desempatar sobrenome, isto
    aqui muda — e não antes.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import elos

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


GENTE = [
    {"spl_id": "salem", "nome": "Salem Al Dawsari", "nome_ar": "سالم الدوسري"},
    {"spl_id": "moh", "nome": "Mohammed Al Dawsari", "nome_ar": "محمد الدوسري"},
    {"spl_id": "hamdan", "nome": "Abdullah Al Hamdan", "nome_ar": "عبدالله الحمدان"},
    {"spl_id": "cr", "nome": "Cristiano Ronaldo", "nome_ar": "كريستيانو رونالدو"},
    # Duas pessoas com o nome completo idêntico. Existe, e é o caso em que
    # escolher uma seria acertar metade das vezes.
    {"spl_id": "xis1", "nome": "Ali Majrashi", "nome_ar": "علي مجرشي"},
    {"spl_id": "xis2", "nome": "Ali Majrashi", "nome_ar": "علي مجرشي"},
    # Nome de uma palavra só: não pode virar chave de jeito nenhum.
    {"spl_id": "solo", "nome": "Talisca", "nome_ar": "تاليسكا"},
]


def testar():
    falhas.clear()
    indice, ambiguas = elos.indice_de_jogadores(GENTE)
    clubes = elos.indice_de_clubes()

    def quem(ar="", pt=""):
        return elos.jogadores_no_texto(ar, pt, indice)

    # ── 1. acha o nome completo, nas duas escritas ─────────────────────────
    conferir("nome completo em latim",
             quem(pt="Salem Al Dawsari marcou duas vezes"), {"salem": "latim"})
    conferir("nome completo em árabe",
             quem(ar="سجل سالم الدوسري هدفين"), {"salem": "árabe"})
    conferir("hífen não atrapalha",
             quem(pt="Al-Dawsari? Não: Salem Al-Dawsari"), {"salem": "latim"})

    # ── 2. عبد الله contra عبدالله ─────────────────────────────────────────
    # A divergência mais comum da escrita árabe, e a que nenhuma regra de
    # letra resolve: a diferença é só onde alguém apertou espaço. Escrevi uma
    # guarda que impedia a chave colada de existir; este teste é o que
    # mostrou, porque o nome estava no texto e não era encontrado.
    conferir("Abdullah separado acha o Abdullah colado",
             quem(ar="عبد الله الحمدان يغيب"), {"hamdan": "árabe colado"})
    conferir("e colado também acha",
             quem(ar="عبدالله الحمدان يغيب"), {"hamdan": "árabe"})

    # ── 3. O QUE ELA TEM QUE RECUSAR ───────────────────────────────────────
    conferir("sobrenome solto não vira ninguém",
             quem(pt="Al Dawsari marcou o gol"), {})
    conferir("primeiro nome solto não vira ninguém",
             quem(pt="Mohammed jogou bem"), {})
    conferir("sobrenome solto em árabe também não",
             quem(ar="سجل الدوسري هدفا"), {})
    conferir("nome de uma palavra não entra no índice",
             quem(pt="Talisca decidiu a partida"), {})
    # Toda chave ou tem duas palavras, ou é uma forma colada longa. O que não
    # pode existir é chave curta de palavra única: 'محمد' casaria com meio
    # elenco.
    for k in indice["chave"]:
        ok(len(k.split()) >= 2 or (" " not in k and len(k) >= 8),
           f"chave curta e de uma palavra só entrou no índice: {k!r}")

    # ── 4. nome completo repetido: ninguém é escolhido ─────────────────────
    # Dois 'Ali Majrashi' de verdade nesta liga, em clubes diferentes. A chave
    # cai em dois, então ela é jogada fora — não desempatada.
    conferir("nome que cai em duas pessoas não casa",
             quem(pt="Ali Majrashi entrou no segundo tempo"), {})
    ok("ali majrashi" in ambiguas,
       "a chave repetida não foi nem registrada como descartada")
    ok("ali majrashi" not in indice["chave"],
       "a chave repetida ficou no índice apontando para UMA das duas pessoas")

    # ── 5. o texto mais longo não engole o mais curto ──────────────────────
    # Procuro do nome maior para o menor. Sem isso, um texto com
    # 'Mohammed Al Dawsari' poderia casar 'Al Dawsari' de outra pessoa.
    conferir("acha o dono do nome completo, não um pedaço",
             quem(pt="Mohammed Al Dawsari cruzou para Salem Al Dawsari"),
             {"moh": "latim", "salem": "latim"})

    # ── 6. clubes ──────────────────────────────────────────────────────────
    conferir("clube em latim",
             elos.clubes_no_texto("", "O Al-Nassr venceu o Al Ittihad", clubes),
             ["Al Ittihad", "Al Nassr"])
    conferir("clube em árabe",
             elos.clubes_no_texto("فاز الهلال على النصر", "", clubes),
             ["Al Hilal", "Al Nassr"])
    # O artigo `ال` é o que separa o clube da palavra comum. 'النصر' é o
    # Al-Nassr; 'نصر' é "vitória". Sem preservar o artigo, o Al-Nassr era
    # citado em toda notícia que falasse em vencer — e o mesmo vale para
    # 'الفتح' (abertura) e 'الحزم' (firmeza).
    conferir("palavra comum sem artigo não vira clube",
             elos.clubes_no_texto("حقق نصر كبير في المباراة", "", clubes), [])
    conferir("mas com artigo vira",
             elos.clubes_no_texto("الفتح يتعادل", "", clubes), ["Al Fateh"])
    conferir("texto sem clube nenhum",
             elos.clubes_no_texto("", "A rodada foi fraca", clubes), [])
    # Palavra inteira, não pedaço: 'al ahli' está contido em 'al ahliya'.
    ok("Al Ahli" not in elos.clubes_no_texto("", "o time alahliyat jogou", clubes),
       "casou clube dentro de outra palavra")

    # ── 7. entradas estranhas não explodem ─────────────────────────────────
    for ar, pt in (("", ""), (None, None), ("...", "!!!"), ("ال", "al")):
        try:
            elos.jogadores_no_texto(ar, pt, indice)
            elos.clubes_no_texto(ar, pt, clubes)
        except Exception as e:
            falhas.append(f"explodiu com ({ar!r}, {pt!r}): {type(e).__name__}: {e}")

    # ── 8. índice vazio não inventa nada ───────────────────────────────────
    vazio, _ = elos.indice_de_jogadores([])
    conferir("sem jogadores, sem elos",
             elos.jogadores_no_texto("سالم الدوسري", "Salem Al Dawsari", vazio), {})
    # Jogador sem id não entra: um elo sem para onde apontar não é um elo.
    sem_id, _ = elos.indice_de_jogadores([{"nome": "Salem Al Dawsari"}])
    conferir("jogador sem spl_id fica de fora", sem_id["chave"], {})

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ elos: acha o nome inteiro nas duas escritas, e recusa o resto")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
