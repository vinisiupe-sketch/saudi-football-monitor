"""
Campo com letra menor que 16px faz o iPhone dar zoom sozinho.

O QUE ACONTECEU (09/09/26)
    O Vini tocava na caixa de legenda do clipe, pelo celular, e a página dava
    um zoom que ele não pediu: o card saía do lugar e digitar virava briga —
    no meio do jogo, com o clipe esperando.

    Não é defeito do app. É regra do Safari do iOS: quando o campo que recebe
    o foco tem letra menor que 16px, ele aproxima a tela para o texto ficar
    legível. Não dá para desligar isso pelo CSS.

    A saída ERRADA seria pôr `maximum-scale=1` ou `user-scalable=no` no
    <meta viewport>. Isso mata o zoom da página inteira, para todo mundo,
    inclusive para quem depende do gesto de pinça para enxergar. Resolveria
    o sintoma cobrando de quem não tem nada a ver com ele.

    A saída certa é a letra do campo ter 16px.

COMO FICOU RESOLVIDO
    Uma regra global, em _SEM_ZOOM_NO_TOQUE, que só vale em tela de toque:

        @media (hover: none) and (pointer: coarse) {
          input, select, textarea { font-size: 16px !important; }
        }

    Varri o CSS e eram DEZ regras em seis telas diferentes — a legenda do
    clipe era só a que incomodava mais. Corrigir uma por uma deixaria a
    próxima que alguém escrever nascendo com o mesmo defeito.

    No desktop nada muda: o `pointer: coarse` é dedo, não mouse, e as tabelas
    densas continuam com a letra pequena com que foram desenhadas.

O QUE ESTE ARQUIVO VIGIA
    Que a regra global continue lá, que ela continue restrita a tela de
    toque, e que ninguém "resolva" o zoom travando o viewport.
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

MINIMO_PX = 16.0
RAIZ_PX = 16.0          # tamanho de fonte padrão do navegador

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _em_px(valor: str, unidade: str) -> float:
    return float(valor) * (RAIZ_PX if unidade in ("rem", "em") else 1.0)


def testar():
    falhas.clear()

    # ── 1. a regra global existe e está no <head> de todas as telas ─────────
    ok("_SEM_ZOOM_NO_TOQUE" in FONTE,
       "sumiu o _SEM_ZOOM_NO_TOQUE — sem ele, todo campo com letra menor que "
       "16px volta a fazer o iPhone dar zoom ao ser tocado")
    ok("_HEAD_COMUM = _THEME_INIT_SCRIPT + _PWA_HEAD + _SEM_ZOOM_NO_TOQUE" in FONTE,
       "a regra saiu do _HEAD_COMUM — ela precisa entrar no <head> de TODAS "
       "as telas, e é o _HEAD_COMUM que faz isso")

    bloco = FONTE[FONTE.find("_SEM_ZOOM_NO_TOQUE = "):]
    bloco = bloco[:bloco.find('"""', bloco.find('"""') + 3) + 3]
    ok("hover: none" in bloco and "pointer: coarse" in bloco,
       "a regra deixou de ser restrita a tela de toque — no desktop ela "
       "engorda o campo de toda tabela densa, que foi desenhada com letra "
       "pequena de propósito")
    m = re.search(r"font-size:\s*([\d.]+)(rem|px|em)", bloco)
    ok(m is not None, "a regra global perdeu o font-size")
    if m:
        px = _em_px(m.group(1), m.group(2))
        ok(px >= MINIMO_PX,
           f"a regra global está com {m.group(0)} ({px:.1f}px) — abaixo de "
           f"{MINIMO_PX:.0f}px o iPhone continua dando zoom")
    ok("!important" in bloco,
       "a regra perdeu o !important. Seletores como `.filters-row input` têm "
       "mais especificidade que `input`, e sem ele a media query perde para "
       "eles justamente nas telas que mais têm campo")

    # ── 2. ninguém travou o zoom para "resolver" ────────────────────────────
    # Olho as TAGS de viewport, e não o arquivo inteiro: na primeira versão eu
    # procurava "maximum-scale" em main.py e o teste falhava por causa do
    # comentário que explica por que NÃO usar maximum-scale. Teste que acusa a
    # própria documentação é teste que ninguém mantém.
    viewports = re.findall(r'<meta[^>]*name="viewport"[^>]*>', FONTE)
    ok(len(viewports) >= 3,
       f"achei só {len(viewports)} tags de viewport — a varredura está "
       "olhando para o lugar errado")
    for tag in viewports:
        for proibido, porque in (
                ("maximum-scale", "impede o gesto de pinça na página inteira"),
                ("user-scalable=no", "desliga o zoom para todo mundo"),
                ("user-scalable=0", "desliga o zoom para todo mundo")):
            ok(proibido not in tag,
               f"apareceu `{proibido}` num viewport — {porque}, inclusive "
               "para quem depende dele para enxergar. O jeito certo de não "
               "dar zoom ao focar um campo é a letra do campo ter 16px")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ zoom no celular: regra global de 16px só em tela de toque, "
          "e o gesto de pinça continua livre")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
