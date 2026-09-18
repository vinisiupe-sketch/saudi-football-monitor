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


# ─────────────────────────────────────────────────────────────────────────
# A VERSÃO NO AR — "enviado" e "no ar" são perguntas diferentes
# ─────────────────────────────────────────────────────────────────────────
# O QUE ACONTECEU (18/09/26)
#     "Não subiu. A última atualização do railway é de 34 minutos atrás, você
#      fez o commit 27 minutos atrás."
#
#     Eu olhava o Git e dizia "está enviado" — estava, o reflog confirmava.
#     Ele olhava o app e dizia "não mudou" — não tinha mudado. Passamos meia
#     hora discutindo uma coisa que ninguém conseguia ver, porque o app não
#     sabia dizer qual versão ele próprio era.
#
# Executo o bloco de verdade, nos dois ambientes. Conferir que as variáveis
# estão CITADAS no código não prova que a linha sai preenchida.
import time                                               # noqa: E402
from datetime import datetime                             # noqa: E402
from zoneinfo import ZoneInfo                             # noqa: E402

ok("_INICIADO_EM = time.time()" in FONTE,
   "sumiu a marca de quando o processo subiu. Sem ela a saúde mostra a hora "
   "de agora, que não diz nada sobre quando o deploy rodou")
_i_marca = FONTE.index("_INICIADO_EM = time.time()")
ok(FONTE[:_i_marca].count("\ndef ") == 0 or "\napp = FastAPI" in FONTE[_i_marca:],
   "o `_INICIADO_EM` saiu do nível do módulo. Dentro de uma função ele passa "
   "a ser a hora da chamada, e a linha diria que o app subiu agora mesmo, "
   "sempre")

_i = FONTE.index("    # ── QUAL VERSÃO ESTÁ NO AR")
_bloco = "\n".join(l[4:] if l.startswith("    ") else l
                   for l in FONTE[_i:FONTE.index("    # ── o banco ", _i)]
                   .split("\n"))

_VARS = ("RAILWAY_GIT_COMMIT_SHA", "RAILWAY_GIT_BRANCH",
         "RAILWAY_GIT_COMMIT_MESSAGE")


def _rodar(ambiente):
    guardado = {k: os.environ.get(k) for k in _VARS}
    try:
        for k in _VARS:
            os.environ.pop(k, None)
        os.environ.update(ambiente)
        saida = []
        exec(_bloco, {"os": os, "datetime": datetime,
                      "BRT": ZoneInfo("America/Sao_Paulo"),
                      "_INICIADO_EM": time.time() - 1800,
                      "conta": lambda t, x, bem=True: saida.append((t, x, bem))})
        return saida
    finally:
        for k, v in guardado.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


_com = _rodar({"RAILWAY_GIT_COMMIT_SHA": "97bee1625a3b914d348dafe6a97e5151",
               "RAILWAY_GIT_BRANCH": "main",
               "RAILWAY_GIT_COMMIT_MESSAGE": "Assunto do commit\nCorpo dele"})
ok(len(_com) == 1, f"o bloco da versão escreveu {len(_com)} linhas; esperava 1")
if _com:
    _titulo, _texto, _bem = _com[0]
    ok("97bee16" in _texto,
       f"o commit no ar não aparece na linha: {_texto!r}. É o número que "
       f"responde 'subiu ou não subiu' sem ninguém precisar adivinhar")
    ok("97bee1625a3b914d348dafe6a97e5151" not in _texto,
       "o SHA saiu inteiro; sete caracteres é o que se compara de olho")
    ok("Corpo dele" not in _texto,
       "a mensagem do commit saiu inteira, com corpo e tudo. Numa página de "
       "diagnóstico isso vira parede de texto")
    ok("Assunto do commit" in _texto, "o assunto do commit sumiu da linha")
    ok("Deployments" in _texto,
       "a linha não diz onde olhar quando o commit no ar não for o último "
       "enviado. Saber que está velho sem saber o que fazer é meio caminho")
    ok(_bem is True, "com o carimbo presente a linha saiu marcada como erro")

_sem = _rodar({})
ok(len(_sem) == 1 and _sem[0][2] is False,
   "sem as variáveis do Railway a linha não avisa que não há carimbo. Ela "
   "não pode inventar um número nem fingir que está tudo certo")
ok("RAILWAY_GIT" in _sem[0][1],
   "a linha sem carimbo não diz por que não tem carimbo")

# E ELA É A PRIMEIRA DA PÁGINA. É a primeira pergunta quando algo não mudou.
ok(FONTE.index("# ── QUAL VERSÃO ESTÁ NO AR") <
   FONTE.index("    # ── o banco ", FONTE.index('@app.get("/api/diag/saude"')),
   "a versão no ar deixou de ser a primeira linha da página de saúde")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ página de saúde cobre as fontes, diz a versão no ar, e Elencos segue "
      "sem a API-Football")
