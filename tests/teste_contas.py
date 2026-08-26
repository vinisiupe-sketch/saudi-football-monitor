"""
Senhas, sessões e quem pode entrar.

Esta é a parte do app onde errar é caro de um jeito diferente: um botão feio
irrita, uma sessão que dá para forjar entrega a conta. Por isso aqui eu testo
os ataques, não só o caminho feliz.
"""
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ["SESSAO_SECRETA"] = "segredo-de-teste-nao-usar"
import contas

falhas = []


def ok(c, m):
    if not c:
        falhas.append(m)


# ── senha ──────────────────────────────────────────────────────────────────
h = contas.guardar_senha("umaSenhaBoa123")
ok(contas.senha_confere("umaSenhaBoa123", h), "não reconhece a senha certa")
ok(not contas.senha_confere("umaSenhaBoa124", h), "aceitou senha errada")
ok("umaSenhaBoa123" not in h, "A SENHA ESTÁ EM TEXTO NO QUE VAI PARA O BANCO")
ok(h.startswith("scrypt$"), "não é scrypt")
ok(contas.guardar_senha("igual") != contas.guardar_senha("igual"),
   "duas senhas iguais geram o mesmo registro — falta o sal")
print("  senha: hash com sal, não guarda o texto, reconhece a certa")

# registro corrompido não pode virar exceção nem passar
for lixo in ("", None, "abc", "scrypt$x$y$z$a$b", "outro$1$2$3$4$5"):
    ok(contas.senha_confere("qualquer", lixo) is False,
       f"registro corrompido {lixo!r} não devolveu False limpo")
print("  registro corrompido: False, sem explodir")

ok(contas.senha_fraca("1234567"), "aceitou senha de 7 caracteres")
ok(not contas.senha_fraca("12345678"), "recusou senha de 8")
print(f"  mínimo de {contas.SENHA_MINIMA} caracteres")

# ── sessão ─────────────────────────────────────────────────────────────────
c = contas.criar_sessao("Vini@Exemplo.COM ")
ok(contas.ler_sessao(c) == "vini@exemplo.com", "não normaliza o e-mail")
print("  sessão: cria e lê, normalizando o e-mail")

# os ataques
ataques = {
    "assinatura trocada": c[:-4] + "beef",
    "corpo trocado": "eyJlIjoiaW52YXNvckBtYWwuY29tIiwidiI6OTk5OTk5OTk5OX0." + c.split(".")[1],
    "sem assinatura": c.split(".")[0],
    "vazio": "",
    "lixo": "não é nem base64",
    "só ponto": ".",
}
for nome, cookie in ataques.items():
    ok(contas.ler_sessao(cookie) == "", f"cookie forjado passou: {nome}")
print(f"  {len(ataques)} tentativas de forjar cookie: todas recusadas")

# sessão vencida
import base64 as _b64, hashlib as _hl, hmac as _hm, json as _j
corpo = _j.dumps({"e": "a@b.com", "v": int(time.time()) - 10},
                 separators=(",", ":")).encode()
dados = _b64.urlsafe_b64encode(corpo).decode().rstrip("=")
venc = dados + "." + _hm.new(b"segredo-de-teste-nao-usar", dados.encode(),
                             _hl.sha256).hexdigest()
ok(contas.ler_sessao(venc) == "", "sessão vencida continuou valendo")
print("  sessão vencida: recusada mesmo com assinatura boa")

# trocar o segredo invalida tudo
os.environ["SESSAO_SECRETA"] = "outro-segredo"
ok(contas.ler_sessao(c) == "", "cookie continuou valendo com outro segredo")
os.environ["SESSAO_SECRETA"] = "segredo-de-teste-nao-usar"
print("  segredo diferente: cookies antigos deixam de valer")

# ── quem pode criar conta ──────────────────────────────────────────────────
os.environ["EMAILS_LIBERADOS"] = "vini@exemplo.com, Amigo@Time.com"
ok(contas.pode_criar_conta("VINI@exemplo.com"), "não reconhece quem está na lista")
ok(contas.pode_criar_conta(" amigo@time.com "), "não tolera espaço e maiúscula")
ok(not contas.pode_criar_conta("estranho@fora.com"), "deixou entrar quem não está")
os.environ["EMAILS_LIBERADOS"] = ""
ok(not contas.pode_criar_conta("vini@exemplo.com"),
   "SEM LISTA CONFIGURADA, QUALQUER UM CRIA CONTA")
print("  lista de liberados: sem ela, ninguém entra")

# ── a saudação ─────────────────────────────────────────────────────────────
for email, nome, esperado in (
        ("vinisiupe@gmail.com", "", "Vinisiupe"),
        ("vini@x.com", "Vini Pereira", "Vini"),
        ("marcus.pereira@x.com", "", "Marcus"),
        ("a_b@x.com", "", "A")):
    got = contas.primeiro_nome(email, nome)
    ok(got == esperado, f"saudação de {email!r}/{nome!r}: {got!r} != {esperado!r}")
print("  saudação: primeiro nome, do nome ou do e-mail")

# ── o middleware não pode trancar o gravador ───────────────────────────────
src = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
for caminho in ("/api/clipe/", "/api/gravador/"):
    ok(f'"{caminho}"' in src, f"{caminho} não está entre os caminhos livres — "
                              "isso derruba a gravação no meio de um jogo")
ok('"/entrar"' in src and '"/api/entrar"' in src,
   "a própria tela de login ficaria trancada")
print("  gravador e tela de login continuam livres")

# ── o cookie tem as três travas ────────────────────────────────────────────
for trava, porque in (("httponly=True", "JavaScript conseguiria ler o cookie"),
                      ("secure=True", "o cookie viajaria em http"),
                      ('samesite="lax"', "o cookie iria junto em requisição de outro site")):
    ok(trava in src, f"falta {trava}: {porque}")
print("  cookie: httponly, secure e samesite")

# ── mensagem de erro não pode contar quem tem conta ────────────────────────
ok(src.count('"e-mail ou senha não conferem"') == 1,
   "mensagens diferentes para e-mail inexistente e senha errada contam quem tem conta")
print("  login: uma mensagem só, não revela quem tem conta")

print()
print("FALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
sys.exit(1 if falhas else 0)
