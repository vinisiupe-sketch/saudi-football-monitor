"""
O card da escalação nasce FECHADO e abre no clique.

POR QUE ISTO PRECISA DE TESTE
    Com todos os jogos do dia abertos, a guia Escalações virava uma parede:
    quatro jogos × dois times × onze nomes numa tela de celular. O Vini pediu
    o card fechado, com os escudos, para achar o jogo de relance (09/09/26).

    O jeito certo é `<details>/<summary>` — o navegador já sabe abrir e
    fechar, funciona pelo teclado, o leitor de tela anuncia o estado, e o que
    está fechado sobrevive à recarga automática de 30 em 30 segundos. O jeito
    errado é uma `div` com `onclick` mexendo em `display`: teria que
    reimplementar tudo isso à mão e perderia o estado a cada redesenho.

    Uma armadilha: `open` num `<details>` NÃO é `open="false"`. O atributo
    existir já abre o card, com qualquer valor. Por isso ele é montado como
    string vazia ou ' open', e o teste checa isso.

O QUE ESTE ARQUIVO VIGIA
    Que o card seja `<details>`, que o cabeçalho clicável seja `<summary>`,
    que os escudos estejam lá, que ninguém escreva `open` fixo, e que o marca-
    dor padrão do navegador continue escondido (o triângulo desalinha a linha
    de escudo–nome–hora–nome–escudo).
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def testar():
    falhas.clear()

    inicio = FONTE.find("jogos.forEach(function (j, i)")
    ok(inicio > 0, "sumiu o laço que monta os cards da guia Escalações")
    if inicio < 0:
        print("  ✗", falhas[0])
        return len(falhas)
    bloco = FONTE[inicio:inicio + 3000]

    # ── 1. é <details>, e não div com onclick ────────────────────────────
    ok("'<details class=\"esc-card'" in bloco,
       "o card deixou de ser <details>. Uma div com onclick perde o abre-e-"
       "fecha de graça do navegador, o teclado, o leitor de tela — e o estado "
       "aberto some a cada recarga automática")
    ok("'<summary>'" in bloco,
       "o cabeçalho do card não é mais <summary> — sem ele o <details> não "
       "tem onde ser clicado")
    # São DOIS caminhos de saída — o card sem escalação e o card com ela — e
    # cada um fecha a tag por conta própria. Conto as ocorrências em vez de
    # procurar '</details>' isolado: no código elas vêm coladas no </div> que
    # as antecede.
    ok(bloco.count("</details>") >= 2,
       f"achei {bloco.count('</details>')} fechamento(s) de <details> e são "
       "dois caminhos de saída (com escalação e sem). Um <details> que não "
       "fecha engole os cards seguintes para dentro dele")

    # ── 2. `open` é condicional, nunca fixo ──────────────────────────────
    ok("prontas === 1" in bloco,
       "a regra de abrir sozinho mudou. O card só abre sem clique quando há "
       "UMA escalação na tela; com várias, todos fechados")
    ok('"open"' not in bloco and "'<details class=\"esc-card\" open" not in bloco,
       "apareceu `open` fixo no <details>. Num <details>, o atributo existir "
       "JÁ abre o card — `open=\"false\"` abre igual")

    # ── 3. os escudos ────────────────────────────────────────────────────
    ok("escudo(casa)" in bloco and "escudo(fora)" in bloco,
       "os escudos saíram do cabeçalho do card — eram eles que deixavam o "
       "jogo reconhecível de relance com o card fechado")
    corpo = FONTE[FONTE.find("function escudo(lado)"):]
    corpo = corpo[:corpo.find("\n}}")]
    ok("esc(url)" in corpo,
       "a URL do escudo entra no HTML sem passar pelo esc() — é texto que "
       "vem de fora do app")
    ok("url ?" in corpo or "url ? " in corpo,
       "o escudo perdeu a guarda de URL vazia: sem ela sai um <img> quebrado "
       "no lugar do clube")

    # ── 4. o triângulo padrão continua escondido ─────────────────────────
    css = FONTE[FONTE.find(".esc-card > summary"):]
    css = css[:600]
    ok("list-style: none" in css,
       "voltou o marcador padrão do <details> — o triângulo entra na linha e "
       "empurra escudo, nome e hora para o lado")
    ok("cursor: pointer" in css,
       "o cabeçalho do card perdeu o cursor de mão: nada indica que ele abre")
    ok("::-webkit-details-marker" in FONTE,
       "sumiu a regra do -webkit-details-marker — no Safari, que é o "
       "navegador do celular do Vini, o triângulo volta a aparecer")

    # ── 5. o botão de upload não voltou ──────────────────────────────────
    ok("esc-drop" not in FONTE,
       "a área de arrastar o PDF voltou à tela. Quem busca o matchsheet "
       "agora é o monitor do Media Hub; o campo aqui só confunde")
    # Olho a FRASE que convida o Vini a enviar, e não a palavra "PDF": a tela
    # continua (com razão) dizendo "quando o monitor enviar um PDF", que fala
    # do monitor e não dele.
    ok("também pode enviar" not in FONTE,
       "o subtítulo da guia ainda convida a enviar um PDF à mão, e o campo "
       "para isso não existe mais")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ card de escalação: <details> fechado, escudos no cabeçalho, "
          "sem upload e sem triângulo")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
