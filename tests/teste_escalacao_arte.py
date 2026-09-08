"""
O PNG baixado tem que ser a MESMA escalação que está na tela.

O RISCO QUE ESTE ARQUIVO EXISTE PARA COBRIR
    A guia Elencos posiciona os jogadores com um projetar() escrito em
    JavaScript, dentro da página. O arquivo que o Vini baixa é montado por
    outro projetar(), escrito em Python, no escalacao_arte.py. São as mesmas
    seis constantes e a mesma conta — em duas linguagens.

    Duas cópias de uma conta divergem. E o jeito como esta ia divergir é o pior
    possível: sem erro nenhum. O Vini arrasta o lateral para a ponta, vê na
    tela do jeito que quer, baixa, e o arquivo traz o lateral três metros mais
    para dentro. Só comparando as duas imagens lado a lado dá para perceber, e
    a essa altura a arte já foi postada.

    Então este teste roda o projetar() DE VERDADE da página (no node) e o
    projetar() DE VERDADE do módulo (em Python), com as mesmas 77 casas das
    sete formações, e exige que batam.

O RESTO
    Que a arte saia com o tamanho certo, que ela aguente jogador sem foto e sem
    bandeira (é o caso comum de quem subiu da base), e que nenhuma placa vaze
    para fora da imagem.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import escalacao_arte

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _tem_node() -> str:
    for nome in ("node", "nodejs"):
        try:
            if subprocess.run([nome, "--version"], capture_output=True,
                              timeout=20).returncode == 0:
                return nome
        except Exception:
            continue
    return ""


def _formacoes() -> dict:
    """As casas, lidas da ÚNICA tabela que deve existir.

    Existiram duas — a da guia Elencos e uma grade regular escondida no
    elenco_tm — e o teste olhava só para a primeira. Agora lê o formacoes.py e
    confere, abaixo, que os dois consumidores realmente usam ele."""
    import formacoes
    return formacoes.QUADROS


def _projetar_no_navegador(node: str, pedidos: list) -> list:
    ini = FONTE.find("const PROJ = {")
    marca = FONTE.find("function projetar(", ini)
    fim = FONTE.find("\n}\n", marca)
    codigo = FONTE[ini:fim + 3] if ini >= 0 and fim > 0 else ""
    if not codigo:
        falhas.append("não achei o projetar() da página de Elencos")
        return []
    script = (codigo + "\nconsole.log(JSON.stringify(" + json.dumps(pedidos)
              + ".map(function(p){ return projetar(p[0], p[1]); })));\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        caminho = f.name
    try:
        r = subprocess.run([node, caminho], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 else []
    finally:
        try:
            os.unlink(caminho)
        except Exception:
            pass


def testar():
    falhas.clear()

    # ── 1. tela e arquivo põem o jogador no MESMO lugar ──────────────────────
    node = _tem_node()
    formacoes = _formacoes()
    ok(len(formacoes) >= 5, "sumiram formações de _ELENCOS_FORMACOES")
    if node and formacoes:
        pedidos, rotulos = [], []
        for nome, casas in formacoes.items():
            for x, y, g in casas:
                pedidos.append([x, y])
                rotulos.append(f"{nome} {g} ({x},{y})")
        do_navegador = _projetar_no_navegador(node, pedidos)
        ok(len(do_navegador) == len(pedidos),
           "o projetar() da página não rodou — não dá para comparar")
        for rotulo, (x, y), na_tela in zip(rotulos, pedidos, do_navegador):
            no_png = escalacao_arte.projetar(x, y)
            for i, campo in enumerate(("x", "y", "e")):
                diferenca = abs(na_tela[campo] - no_png[i])
                ok(diferenca < 0.01,
                   f"{rotulo}: a tela põe {campo}={na_tela[campo]:.3f} e a arte "
                   f"baixada põe {no_png[i]:.3f} — o arquivo não é o que o Vini "
                   "viu quando arrastou")
    elif not node:
        print("  (sem node — pulando a comparação tela x arquivo)")

    # ── 2. a arte monta, no tamanho certo, com dados pobres ──────────────────
    # De propósito sem foto e sem bandeira: é o jogador da base, e era aqui que
    # um None viraria exceção e um 500 no meio do dia de jogo.
    casas = formacoes.get("4-3-3") or []
    jogadores = [{"nome": "AL-DAWSARI", "x": x, "y": y, "foto": None,
                  "bandeira": None} for x, y, _ in casas]
    try:
        png = escalacao_arte.montar({"jogadores": jogadores})
    except Exception as e:
        falhas.append(f"a arte nem monta com jogador sem foto: {type(e).__name__}: {e}")
        png = b""

    if png:
        from io import BytesIO

        from PIL import Image
        img = Image.open(BytesIO(png))
        ok(img.size == (escalacao_arte.LARGURA, escalacao_arte.ALTURA),
           f"a arte saiu {img.size}, e o formato de post é "
           f"{escalacao_arte.LARGURA}x{escalacao_arte.ALTURA}")

        # ── 3. nenhuma placa vaza para fora da imagem ────────────────────────
        # TODAS as formações, e não só a 4-3-3: quem chega perto da borda é o
        # ala do 3-5-2, em x=8 e x=92, que não existe na 4-3-3. Testar uma só
        # deixava o teste passar verde com a placa 60% maior — medi.
        from PIL import ImageDraw, ImageFont
        d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        f_nome = os.path.join(escalacao_arte.FONTES, "WorkSans-SemiBold-latin.ttf")
        for nome_form, quadro in formacoes.items():
            for x, y, g in quadro:
                px, _, esc = escalacao_arte.projetar(x, y)
                fonte = ImageFont.truetype(f_nome,
                                           int(escalacao_arte.NOME_CORPO * esc))
                larg = (escalacao_arte.PLACA_PAD * 2 * esc
                        + d.textlength("ABDULHAMID", font=fonte))
                centro = px * escalacao_arte.LARGURA / 100
                ok(centro - larg / 2 >= 0
                   and centro + larg / 2 <= escalacao_arte.LARGURA,
                   f"{nome_form}: a placa de ({x},{y}) sai da imagem com um "
                   "nome comprido")

    # ── 3b. a placa do PNG tem o tamanho da placa da TELA ────────────────────
    # Mesma armadilha da projeção, um andar abaixo: o CSS mede em cqw (% da
    # largura do campo) e o módulo mede em CQ (% da largura da arte). São a
    # mesma unidade escrita em dois lugares. Mexer só num deles não quebra
    # nada — só faz o arquivo baixado ter a placa de um tamanho e a tela de
    # outro, e ninguém compara os dois com régua.
    import re
    for rotulo, padrao, valor in (
            ("diâmetro da foto", r"width:calc\(([\d.]+)cqw\*var\(--e",
             escalacao_arte.FOTO_DIAM),
            ("anel da foto", r"\.slot\.ocupado \.disco\{border:max\(2px,([\d.]+)cqw",
             escalacao_arte.FOTO_ANEL),
            ("altura da placa", r"height:calc\(([\d.]+)cqw\*var\(--e,1\)\);min-height:15px",
             escalacao_arte.PLACA_ALT),
            ("altura da bandeira", r"\.slot \.band\{height:calc\(([\d.]+)cqw",
             escalacao_arte.BANDEIRA_ALT),
            ("sobreposição da placa", r"top:calc\(100% - ([\d.]+)cqw\*var\(--e",
             escalacao_arte.PLACA_SOBE),
            ("respiro da placa", r"padding:0 calc\(([\d.]+)cqw\*var\(--e",
             escalacao_arte.PLACA_PAD),
            ("espaço bandeira-nome", r"gap:calc\(([\d.]+)cqw\*var\(--e",
             escalacao_arte.PLACA_GAP),
            ("corpo do nome", r"font-size:max\(8px,([\d.]+)cqw\*var\(--e,1\)\);pointer-events",
             escalacao_arte.NOME_CORPO)):
        m = re.search(padrao, FONTE)
        ok(m is not None,
           f"não achei no CSS da guia Elencos a regra do {rotulo} — o teste "
           "perdeu de vista o número que ele devia comparar")
        if m:
            ok(abs(float(m.group(1)) - valor / escalacao_arte.CQ) < 0.005,
               f"{rotulo}: a tela usa {m.group(1)}cqw e o PNG usa "
               f"{valor / escalacao_arte.CQ:.2f} — o que o Vini vê e o que ele "
               "baixa deixaram de ter o mesmo tamanho")

    # ── 3c. a foto do jogador PRECISA do Referer ─────────────────────────────
    # O defeito que o Vini pegou olhando a arte baixada: os onze círculos
    # vazios. O Transfermarkt responde 403 para quem não vem da página dele, e
    # o _baixar() ia sem cabeçalho nenhum. Nada quebrava — a imagem simplesmente
    # não vinha, e o PNG saía com o cinza de fundo no lugar do rosto.
    #
    # Rodo o _baixar() DE VERDADE, arrancado do main.py, com um cliente de
    # mentira que só anota o que foi pedido. Conferir o texto do arquivo
    # ("tem a palavra Referer?") passaria verde com o cabeçalho montado e nunca
    # enviado.
    import asyncio
    import types

    corpo_baixar = ""
    arvore = ast.parse(FONTE)
    for no in ast.walk(arvore):
        if isinstance(no, ast.AsyncFunctionDef) and no.name == "_baixar":
            corpo_baixar = "\n".join(FONTE.split("\n")[no.lineno - 1:no.end_lineno])
    ok(bool(corpo_baixar), "sumiu o _baixar() que busca as fotos")

    if corpo_baixar:
        escopo = {"TM_HEADERS_UA": "agente-de-teste"}
        exec(corpo_baixar, escopo)

        class ClienteFalso:
            def __init__(self):
                self.pedidos = []

            async def get(self, url, timeout=None, headers=None):
                self.pedidos.append((url, headers or {}))
                return types.SimpleNamespace(status_code=200, content=b"x")

        cliente = ClienteFalso()
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            escopo["_baixar"](cliente,
                              "https://img.a.transfermarkt.technology/portrait/1.jpg"))
        ok(cliente.pedidos and "transfermarkt" in cliente.pedidos[0][1].get("Referer", ""),
           "a foto do Transfermarkt voltou a ser pedida SEM Referer — o TM "
           "responde 403 e a arte sai com os onze círculos vazios, sem erro "
           "nenhum aparecer")
        ok(cliente.pedidos and cliente.pedidos[0][1].get("User-Agent"),
           "a foto do Transfermarkt está indo sem User-Agent")

    # ── 4. a sigla do país sai do próprio emoji ──────────────────────────────
    for emoji, esperado in (("\U0001F1E7\U0001F1F7", "br"),
                            ("\U0001F1F8\U0001F1E6", "sa"),
                            ("\U0001F1F5\U0001F1F9", "pt"),
                            (None, None), ("", None), ("x", None)):
        deu = escalacao_arte.iso_da_bandeira(emoji)
        ok(deu == esperado,
           f"escalacao_arte.iso_da_bandeira({emoji!r}) devolveu {deu!r}, esperava {esperado!r}")
    # A da Inglaterra não é um par de indicadores regionais, é uma sequência de
    # tags. Tem que voltar None: placa sem bandeira é melhor que placa com a
    # bandeira de outro país.
    ok(escalacao_arte.iso_da_bandeira("\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E"
                        "\U000E0067\U000E007F") is None,
       "a bandeira da Inglaterra virou uma sigla de país — ia sair a bandeira errada")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ arte da escalação: mesma posição da tela, monta sem foto, "
          "nada vaza da imagem")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
