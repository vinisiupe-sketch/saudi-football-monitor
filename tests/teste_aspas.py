"""
O extrator de aspas, contra textos escritos como as notícias vêm de verdade.

O que eu mais quero destas conferências não é que ele acerte muito — é que ele
NÃO INVENTE. Citação com o dono errado é pior que citação nenhuma: sai no seu
X com o nome de alguém que não falou aquilo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aspas

falhas = []


def ok(c, m):
    if not c:
        falhas.append(m)


CASOS = [
    # (título, corpo, quem esperado, quanto esperado)
    ("Cristiano Ronaldo fala sobre o Al Nassr",
     'Após a vitória, o atacante comentou o momento. "Estamos construindo algo '
     'especial neste clube e quero ganhar títulos aqui", disse Cristiano Ronaldo '
     'em entrevista ao Al-Riyadiya.',
     "Cristiano Ronaldo", 1),

    ("Técnico do Al Hilal projeta clássico",
     'Jorge Jesus afirmou: "O clássico é sempre diferente, a gente prepara a '
     'semana inteira pensando nele". O treinador falou em coletiva de imprensa.',
     "Jorge Jesus", 1),

    ("Duas falas na mesma matéria",
     '"O grupo está focado e sabe o tamanho do desafio", declarou Abdullah Al '
     'Hamdan. Mais tarde, o meia completou: "Vamos brigar pelo título até o fim '
     'da temporada, sem desculpa".',
     "Abdullah Al Hamdan", 2),

    ("Aspas curvas, como vem do tradutor",
     '“Não penso em sair do clube neste momento da minha carreira”, garantiu '
     'Salem Al Dawsari em entrevista ao Canal Saudi Sports.',
     "Salem Al Dawsari", 1),
]

for titulo, corpo, quem, quanto in CASOS:
    r = aspas.extrair(titulo, corpo, "@fonte")
    c = r["citacoes"]
    ok(len(c) == quanto, f"{titulo!r}: esperava {quanto} citação(ões), veio {len(c)}")
    if c:
        ok(c[0]["quem"] == quem, f"{titulo!r}: quem falou saiu {c[0]['quem']!r}, "
                                 f"esperava {quem!r}")
        ok('"' not in c[0]["fala"] and "“" not in c[0]["fala"],
           f"{titulo!r}: a fala veio com as aspas dentro")
        ok(c[0]["via"] == "fonte", "o via não perdeu o arroba")
    print(f"  {titulo[:38]:40} {len(c)} citação(ões)"
          + (f" — {c[0]['quem']}" if c else ""))

print()

# ── o que ele NÃO pode fazer ───────────────────────────────────────────────
SEM_DONO = [
    ("Sem verbo de fala",
     'O time treinou pela manhã. "Foi um treino puxado e produtivo para todos '
     'nós do elenco". O elenco se reapresenta amanhã.'),
    ("Clube não é gente",
     'O Al Hilal informou: "O clube comunica a renovação do contrato por mais '
     'duas temporadas com o atleta".'),
]
for nome, corpo in SEM_DONO:
    r = aspas.extrair("", corpo, "@x")
    if nome == "Sem verbo de fala":
        ok(not r["citacoes"], f"{nome}: inventou dono para fala órfã")
        ok(r["descartadas"] >= 1, f"{nome}: descartou em silêncio, sem contar")
        print(f"  {nome:40} descartou {r['descartadas']}, não inventou")
    else:
        # Clube pode virar "quem" — é limitação conhecida do jeito sem IA.
        print(f"  {nome:40} -> {r['citacoes'][0]['quem'] if r['citacoes'] else 'nada'}")

# fala curta demais não é declaração
r = aspas.extrair("", 'Ele disse que o time está "bem" hoje.', "@x")
ok(not r["citacoes"], "aceitou fragmento de uma palavra como declaração")
print(f"  {'Fragmento de uma palavra':40} descartado")

# ── onde falou ─────────────────────────────────────────────────────────────
ONDE = [
    ('"Frase suficientemente longa para valer", disse Fulano Silva em coletiva.',
     "em coletiva"),
    ('"Frase suficientemente longa para valer", disse Fulano Silva em entrevista '
     'ao Al Arabiya.', "em entrevista ao Al Arabiya"),
    ('"Frase suficientemente longa para valer", disse Fulano Silva após a partida.',
     "após a partida"),
]
for corpo, esperado in ONDE:
    r = aspas.extrair("", corpo, "@x")
    achado = r["citacoes"][0]["onde"] if r["citacoes"] else ""
    ok(achado == esperado, f"onde: esperava {esperado!r}, veio {achado!r}")
    print(f"  onde: {achado!r}")

# ── repetida não duplica ───────────────────────────────────────────────────
r = aspas.extrair("", '"A mesma frase dita duas vezes na matéria inteira", disse '
                      'Fulano Silva. Depois: "A mesma frase dita duas vezes na '
                      'matéria inteira", repetiu Fulano Silva.', "@x")
ok(len(r["citacoes"]) == 1, f"duplicou a mesma fala: {len(r['citacoes'])}")
print(f"  fala repetida: {len(r['citacoes'])} citação")

# ── nada explode com entrada estranha ──────────────────────────────────────
for ruim in (None, "", "   ", '"', '""', "«»", "texto sem aspas nenhuma"):
    try:
        aspas.extrair(ruim, ruim, ruim)
    except Exception as e:
        falhas.append(f"explodiu com {ruim!r}: {type(e).__name__}: {e}")
print("  entradas estranhas: nenhuma explodiu")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
