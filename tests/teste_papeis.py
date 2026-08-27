"""
Quem pode o quê, e os convites.

Este é o teste que eu mais quero que exista. Errar para o lado de bloquear
demais gera uma reclamação; errar para o lado de liberar demais entrega
Configurações e a lista de usuários para quem só devia ler notícia — e
ninguém reclama, porque funciona.

Por isso quase todo caso aqui é escrito na forma negativa: o que a pessoa NÃO
pode alcançar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contas


def testar():
    falhas = []

    def ok(condicao, mensagem):
        if not condicao:
            falhas.append(mensagem)

    def conferir(nome, deu, esperado):
        if deu != esperado:
            falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")

    # ── a lista de proibidos tem que casar com as rotas de verdade ──────
    # Eu escrevi "/configuracoes" e a rota é "/config". A regra não pegava
    # nada, e o teste passava porque conferia a minha grafia contra ela mesma.
    # Este bloco lê o main.py e cobra as rotas que existem de fato.
    import re
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fonte = open(os.path.join(raiz, "main.py"), encoding="utf-8").read()
    rotas = set(re.findall(r'@app\.(?:get|post)\("([^"]+)"', fonte))
    for sensivel in ("/config", "/api/ajustes", "/api/usuarios", "/api/convites"):
        ok(any(r == sensivel or r.startswith(sensivel + "/") for r in rotas),
           f"{sensivel} não existe no main — a regra está protegendo o vazio")
        ok(not contas.pode_ver("gerente", sensivel),
           f"gerente alcança {sensivel}, que é rota real e sensível")
        ok(not contas.pode_ver("leitor", sensivel),
           f"leitor alcança {sensivel}, que é rota real e sensível")

    # ── o adm alcança tudo ──────────────────────────────────────────────
    for rota in ("/", "/config", "/usuarios", "/api/ajustes", "/previa",
                 "/api/convites", "/api/posts/1/aprovar", "/noticias"):
        ok(contas.pode_ver("adm", rota), f"adm deveria alcançar {rota}")

    # ── gerente: tudo, menos ajustes e contas ───────────────────────────
    for negado in ("/config", "/api/ajustes", "/usuarios",
                   "/api/usuarios", "/api/convites"):
        ok(not contas.pode_ver("gerente", negado),
           f"gerente NÃO pode alcançar {negado}")
    for liberado in ("/", "/previa", "/arbitragem", "/posts", "/clipes",
                     "/api/posts/1/aprovar", "/api/previa/gerar", "/noticias"):
        ok(contas.pode_ver("gerente", liberado),
           f"gerente deveria alcançar {liberado}")

    # ── leitor: as guias, sem a home e sem nada que decida ──────────────
    # A home é "/" e "/" é prefixo de tudo. Se a comparação fosse por prefixo,
    # o leitor perderia o app inteiro — e o sintoma seria "não abre nada",
    # sem pista nenhuma da causa.
    conferir("leitor não entra na home", contas.pode_ver("leitor", "/"), False)
    for liberado in ("/noticias", "/mercado", "/aspas", "/previa", "/arbitragem",
                     "/lesoes", "/janela", "/elencos", "/numeros", "/clipes",
                     "/api/previa", "/api/arbitragem"):
        ok(contas.pode_ver("leitor", liberado),
           f"leitor deveria alcançar {liberado}")
    for negado in ("/config", "/usuarios", "/api/ajustes",
                   "/api/aprovacao", "/api/posts/1/aprovar", "/api/clipe/9",
                   "/api/previa/gerar", "/api/arbitragem/buscar",
                   "/api/arbitragem/nome"):
        ok(not contas.pode_ver("leitor", negado),
           f"leitor NÃO pode alcançar {negado}")
    # Ler a prévia sim, mandar gerar não — a leitura não gasta, a geração sim.
    ok(contas.pode_ver("leitor", "/api/previa")
       and not contas.pode_ver("leitor", "/api/previa/gerar"),
       "leitor lê prévia mas não manda gerar")

    # ── papel desconhecido cai no MENOR acesso, nunca no maior ──────────
    for lixo in ("", None, "root", "administrador", "gerente;--", "adm gerente"):
        conferir(f"papel {lixo!r} vira leitor", contas.papel_valido(lixo), "leitor")
    # Caixa e espaço sobrando são digitação, não papel diferente. Aceito os
    # dois porque o contrário rebaixaria um adm por causa de um espaço — e o
    # sintoma seria "sumiu o Configurações", sem explicação nenhuma.
    conferir("papel bom sobrevive", contas.papel_valido("Gerente"), "gerente")
    conferir("caixa e espaço não rebaixam", contas.papel_valido(" ADM "), "adm")
    ok(not contas.pode_ver("chutado", "/config"),
       "papel inventado não pode ver Configurações")

    # ── convites ────────────────────────────────────────────────────────
    codigo, resumo = contas.novo_convite()
    ok(len(codigo) >= 20, "código de convite curto demais")
    conferir("resumo é reprodutível", contas.resumo_do_convite(codigo), resumo)
    ok(codigo not in resumo, "o código não pode aparecer dentro do resumo")
    ok(len(resumo) == 64, "resumo não parece um sha-256")
    # Dois convites seguidos têm que ser diferentes. Se o gerador repetisse,
    # um convite queimado abriria a porta do seguinte.
    outro, resumo2 = contas.novo_convite()
    ok(codigo != outro and resumo != resumo2, "convites repetidos")
    # Código errado não pode bater no resumo do certo.
    ok(contas.resumo_do_convite(codigo + "x") != resumo,
       "código alterado não pode gerar o mesmo resumo")
    ok(contas.resumo_do_convite("") != resumo, "código vazio bateu com um válido")

    validade = contas.validade_do_convite(7)
    from datetime import datetime, timezone
    ok(validade > datetime.now(timezone.utc), "convite já nasce vencido")

    # ── para onde cada um vai ao entrar ─────────────────────────────────
    conferir("adm vai para a home", contas.CASA_DO_PAPEL["adm"], "/")
    conferir("leitor não cai numa tela que não pode ver",
             contas.pode_ver("leitor", contas.CASA_DO_PAPEL["leitor"]), True)
    for p in contas.PAPEIS:
        ok(contas.pode_ver(p, contas.CASA_DO_PAPEL[p]),
           f"{p} cairia numa tela que ele não pode abrir")

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    print("  ✓ papéis: adm, gerente e leitor, e convites de uso único")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
