"""
A página que diz QUEM está de pé e QUEM está caído.

DE ONDE VEIO (16/09/26)
    A guia de Elencos quebrou e o Vini perguntou: "pode ser porque minha
    assinatura com a api football expirou?".

    A resposta era não — aquela rota nem fala com a API-Football; ela usa
    Transfermarkt, o elenco congelado no banco e o glossário. Mas ele não
    tinha como saber disso, e eu só soube depois de rastrear as chamadas da
    rota com a árvore sintática.

    A pergunta vai voltar toda vez que algo quebrar. Então passou a existir um
    lugar onde se pergunta: /api/diag/saude.

O QUE ESTE ARQUIVO VIGIA
    Que a página existe, que ela cobre cada fonte, que ela NUNCA levanta (uma
    página de diagnóstico que quebra ao diagnosticar é inútil justamente na
    hora em que serviria), e — o que vale mais — que a guia de Elencos continua
    sem depender da API-Football. Se um dia alguém ligar as duas, o teste
    avisa, e a resposta que eu dei a ele deixa de ser verdade em silêncio.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
ARVORE = ast.parse(FONTE)
FUNCOES = {n.name: n for n in ast.walk(ARVORE)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


def chamadas_de(nome, visto=None, prof=0):
    """Tudo que esta função chama, direta ou indiretamente."""
    if visto is None:
        visto = set()
    if nome in visto or prof > 8 or nome not in FUNCOES:
        return set()
    visto.add(nome)
    saida = set()
    for n in ast.walk(FUNCOES[nome]):
        if isinstance(n, ast.Call):
            f = n.func
            alvo = (f.id if isinstance(f, ast.Name)
                    else f.attr if isinstance(f, ast.Attribute) else None)
            if alvo:
                saida.add(alvo)
                saida |= chamadas_de(alvo, visto, prof + 1)
    return saida


# ─────────────────────────────────────────────────────────────────────────
# 1. A GUIA DE ELENCOS NÃO DEPENDE DA API-FOOTBALL
# ─────────────────────────────────────────────────────────────────────────
# Este é o teste que importa de verdade neste arquivo. Foi a resposta que eu
# dei a ele, e uma resposta dessas tem de continuar valendo — ou avisar.
elenco = chamadas_de("api_elencos_jogadores")
ok("_af_get" not in elenco,
   "a guia de Elencos passou a chamar a API-Football. Eu disse ao Vini que "
   "ela não dependia disso; se depender, uma assinatura vencida derruba a "
   "guia e a resposta que eu dei vira mentira")
ok("_af_temporada_corrente" not in elenco,
   "a guia de Elencos passou a perguntar a temporada à API-Football")

# E a ficha do jogador também não: ela lê do banco, o que é o que permite
# abrir vinte fichas seguidas sem gastar cota.
for rota, oque in (("_ficha_do_jogador", "a ficha do jogador"),
                   ("api_jogador_arte", "a arte que ele baixa"),
                   ("api_elencos_times", "a lista de clubes")):
    ok("_af_get" not in chamadas_de(rota),
       f"{oque} passou a chamar a API-Football. Isso não pode custar cota, e "
       f"com a assinatura vencida pararia de funcionar — foi o medo que ele "
       f"levantou, e a única razão de ele estar errado é que nada ali depende "
       f"dela")


# ─────────────────────────────────────────────────────────────────────────
# 2. A PÁGINA DE SAÚDE COBRE CADA FONTE
# ─────────────────────────────────────────────────────────────────────────
ok('@app.get("/api/diag/saude"' in FONTE,
   "sumiu a página de saúde — é onde ele pergunta quem está caído")

i = FONTE.index("async def api_diag_saude()")
j = FONTE.index('@app.get("/api/diag/banco"', i)
SAUDE = FONTE[i:j]

for peca, pista in (("Banco de dados", "get_conn"),
                    ("Glossário", "glossario.quantos"),
                    ("API da Saudi Pro League", "_clubes_da_liga_spl"),
                    ("API-Football", '_af_get("status"'),
                    ("Transfermarkt", "transfermarkt.com.br"),
                    ("Arte do jogador", "ficha_arte")):
    ok(peca in SAUDE and pista in SAUDE,
       f"a página de saúde parou de conferir '{peca}' (procurei por {pista!r})")

# A DATA DA ASSINATURA é a pergunta dele em pessoa: "expirou?".
#
# Procuro a CHAMADA e não a palavra: plantei o defeito que troca
# `assinatura.get("end")` por "?" e o teste passou, porque "end" é pedaço de
# "atendendo" e de "entrega", que estão no mesmo texto. Procurar palavra solta
# num arquivo grande encontra qualquer coisa.
for chamada in ('r.get("subscription")', 'assinatura.get("end")',
                'assinatura.get("active")'):
    ok(chamada in SAUDE,
       f"a página parou de ler {chamada} — a data em que a assinatura vence "
       f"era exatamente a pergunta que ele fez")

# UMA CHAMADA SÓ POR FONTE. Esta página é aberta quando algo já está errado;
# ela não pode ser mais um jeito de sobrecarregar quem já está de joelhos.
ok(SAUDE.count("_af_get(") == 1,
   "a página de saúde faz mais de uma chamada à API-Football")
ok(SAUDE.count("client.get(") == 1,
   "a página de saúde faz mais de uma chamada externa por HTTP")

# NADA PODE LEVANTAR. Cada conferência tem de estar dentro de um try — uma
# página de diagnóstico que quebra ao diagnosticar é inútil justamente na
# hora em que ela serviria.
corpo = FUNCOES["api_diag_saude"]
tentativas = [n for n in ast.walk(corpo) if isinstance(n, ast.Try)]
ok(len(tentativas) >= 5,
   f"a página de saúde tem só {len(tentativas)} blocos try. Cada fonte "
   f"precisa do seu: se a primeira que estiver fora derrubar a página, ela "
   f"não diz nada sobre as outras — e é justamente quando algo está fora que "
   f"ela é aberta")
for t in tentativas:
    ok(any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
           or h.type is None for h in t.handlers),
       "um dos try da página de saúde não pega Exception")

# E O RESULTADO É TEXTO, não JSON: ele abre isso colando o endereço na barra
# do navegador, como as outras páginas de diagnóstico do app.
ok('response_class=PlainTextResponse' in
   FONTE[FONTE.index('@app.get("/api/diag/saude"'):
        FONTE.index('@app.get("/api/diag/saude"') + 120],
   "a página de saúde deixou de ser texto puro — ele abre colando o endereço "
   "no navegador, e JSON cru ali é ilegível")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ página de saúde cobre as fontes, e Elencos segue sem a API-Football")
