"""
O jogador tem que cair no gramado da arte, e não ao lado dele.

POR QUE ISTO PRECISA DE TESTE
    O campinho da guia Elencos deixou de ser um retângulo montado com divs e
    passou a ser uma ARTE em perspectiva (public/masks/campo-perspectiva.png).
    Enquanto era retângulo, `left: x%` bastava: a coordenada do jogador era a
    coordenada da tela. Agora não é mais — cada ponto passa por projetar(), que
    carrega seis medidas tiradas a régua da imagem (as duas linhas de fundo, o
    meio-campo, o eixo central).

    Isso cria um acoplamento que não está escrito em lugar nenhum: se alguém
    recortar a arte de novo, trocar o PNG por outro enquadramento ou mexer numa
    constante, os onze jogadores vão para o preto em volta do campo. E não
    quebra nada — nenhum erro, nenhum log. A tela só fica errada, e só quem
    abrir a guia vai ver.

O QUE ESTE ARQUIVO FAZ
    Roda o projetar() DE VERDADE (o mesmo JavaScript da página, executado no
    node) para cada casa de cada formação, e confere no PNG se o pixel de
    destino é grama. Reimplementar a conta aqui em Python seria o teste
    conferindo a si mesmo: uma constante errada estaria errada nos dois lados e
    passaria verde.
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

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
ARTE = os.path.join(RAIZ, "public", "masks", "campo-perspectiva.png")

# A arte com que as constantes de projetar() foram medidas. Está aqui para que
# trocar o template por outro de enquadramento diferente falhe ALTO, em vez de
# silenciosamente empurrar os jogadores para fora da grama.
TAMANHO_ESPERADO = (1080, 1350)

# As três linhas que dão as constantes, em % da arte. Repetidas aqui de
# propósito: se alguém mexer em PROJ sem remedir a imagem, os dois números
# discordam e o teste fala. Ler PROJ do main.py seria conferir a conta contra
# ela mesma.
MARCOS = (("linha de fundo de longe", 0, 29.19),
          ("meio-campo", 50, 42.15),
          ("linha de fundo de perto", 100, 70.59))

# À esquerda a arte tem a faixa dos escudos, e o primeiro bloco dela é verde.
# Medir o meio do gramado sem ignorar essa faixa dá um centro deslocado ~9%
# para a esquerda — e o teste passaria a exigir que a formação ficasse torta.
X_MIN_GRAMADO = 200

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


def _codigo_da_projecao() -> str:
    """O trecho de projeção como ele está na página, sem cópia."""
    ini = FONTE.find("const PROJ = {")
    if ini < 0:
        return ""
    marca = FONTE.find("function projetar(", ini)
    if marca < 0:
        return ""
    fim = FONTE.find("\n}\n", marca)
    return FONTE[ini:fim + 3] if fim > 0 else ""


def _formacoes() -> dict:
    """As casas, lidas da ÚNICA tabela que deve existir.

    Existiram duas — a da guia Elencos e uma grade regular escondida no
    elenco_tm — e o teste olhava só para a primeira. Agora lê o formacoes.py e
    confere, abaixo, que os dois consumidores realmente usam ele."""
    import formacoes
    return formacoes.QUADROS


def _rodar(codigo: str, pedidos: list) -> list:
    """Executa o projetar() da página no node e devolve o que ele respondeu."""
    script = (codigo + "\nconst PEDIDOS = " + json.dumps(pedidos) + ";\n"
              "console.log(JSON.stringify(PEDIDOS.map(function(p){"
              "return projetar(p[0], p[1]); })));\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        caminho = f.name
    try:
        r = subprocess.run([NODE, caminho], capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0:
            falhas.append("o projetar() da página nem roda: "
                          + (r.stderr or "").strip().splitlines()[-1:][0]
                          if (r.stderr or "").strip() else "erro sem mensagem")
            return []
        return json.loads(r.stdout)
    finally:
        try:
            os.unlink(caminho)
        except Exception:
            pass


def _e_grama(px, x: int, y: int, larg: int, alt: int) -> bool:
    """Verde da arte, tolerando cair em cima de uma linha do campo.

    A vizinhança de 2px existe por causa das linhas: o ponto do meia-central
    cai exatamente sobre o círculo central, que é escuro. O que importa é
    estar DENTRO do gramado, e não a cor exata do pixel sorteado.
    """
    for dx in (-2, 0, 2):
        for dy in (-2, 0, 2):
            i, j = min(max(x + dx, 0), larg - 1), min(max(y + dy, 0), alt - 1)
            r, g, b = px[i, j][:3]
            if g > 120 and g > r + 40 and g > b + 40:
                return True
    return False


def testar():
    falhas.clear()
    global NODE
    NODE = _tem_node()
    if not NODE:
        print("  (sem node neste ambiente — pulando a checagem da projeção)")
        return 0

    codigo = _codigo_da_projecao()
    ok(bool(codigo), "não achei o bloco const PROJ / function projetar na "
                     "página de Elencos")
    formacoes = _formacoes()
    ok(len(formacoes) >= 5, "sumiram formações de _ELENCOS_FORMACOES")
    if not codigo or not formacoes:
        for f in falhas:
            print("  ✗", f)
        return len(falhas)

    ok(os.path.exists(ARTE), "sumiu public/masks/campo-perspectiva.png — sem "
                             "a arte o campo fica preto e os jogadores boiam")
    if not os.path.exists(ARTE):
        print("  ✗", falhas[-1])
        return len(falhas)

    from PIL import Image
    img = Image.open(ARTE).convert("RGB")
    larg, alt = img.size
    px = img.load()
    ok((larg, alt) == TAMANHO_ESPERADO,
       f"a arte do campo mudou de tamanho ({larg}x{alt}, esperava "
       f"{TAMANHO_ESPERADO[0]}x{TAMANHO_ESPERADO[1]}). As constantes de "
       "projetar() foram medidas no recorte antigo: ou o enquadramento novo "
       "bate com elas, ou os jogadores vão cair fora do gramado")

    # ── 0a. UMA tabela de posições, e não duas ──────────────────────────────
    # O defeito de 08/09: eu abri as sete formações da guia Elencos e o Vini
    # continuou vendo a 4-2-3-1 apertada. A escalação carregada do último jogo
    # não passava por esta tabela — passava por uma grade regular escondida
    # dentro do elenco_tm, que eu nem sabia que existia. Nada quebrou; a tela
    # só ficou certa por um caminho e errada pelo outro.
    fonte_tm = open(os.path.join(RAIZ, "elenco_tm.py"), encoding="utf-8").read()
    ok("formacoes.coordenadas(" in fonte_tm,
       "o elenco_tm voltou a decidir posição por conta própria — a escalação "
       "carregada do último jogo vai ignorar o desenho das formações, e a guia "
       "fica certa quando você escolhe a formação e errada quando ela vem do "
       "jogo")
    ok("_ELENCOS_FORMACOES = formacoes.QUADROS" in FONTE,
       "a guia Elencos voltou a ter a própria cópia da tabela de posições")
    for arquivo, texto in (("elenco_tm.py", fonte_tm), ("main.py", FONTE)):
        ok('(c + 1) / (n + 1)' not in texto,
           f"{arquivo} voltou a espalhar as casas em (c+1)/(n+1) — é a grade "
           "regular que punha os quatro zagueiros em 20/40/60/80, colados")

    # ── 0. a fonte do nome existe onde o CSS diz que existe ─────────────────
    # Um @font-face apontando para arquivo inexistente não dá erro nenhum: o
    # navegador cai calado na fonte do sistema e a tela fica só um pouco
    # diferente. Ninguém percebe, e a diferença é justamente o que o Vini
    # escolheu a dedo.
    for trecho in FONTE.split("@font-face{")[1:]:
        decl = trecho.split("}")[0]
        if "url('/fonts/" not in decl:
            continue
        arq = decl.split("url('/fonts/")[1].split("'")[0]
        ok(os.path.exists(os.path.join(RAIZ, "public", "fonts", arq)),
           f"o CSS pede /fonts/{arq} e esse arquivo não existe em "
           "public/fonts — o navegador cairia na fonte do sistema sem avisar")

    # ── 1. os marcos: a projeção passa pelas linhas que ela diz passar ───────
    marcos = _rodar(codigo, [[50, m[1]] for m in MARCOS] + [[50, 92], [50, 16]])
    if len(marcos) == 5:
        goleiro, atacante = marcos[3], marcos[4]
        for (nome, _, esperado), p in zip(MARCOS, marcos):
            ok(abs(p["y"] - esperado) < 0.6,
               f"a projeção deixou de cair no {nome} da arte: deu "
               f"{p['y']:.2f}%, a linha está em {esperado}%")

        # Orientação. O ataque é para CIMA (y=16 no ataque, y=92 no gol) desde
        # que a guia existe; inverter isso põe o goleiro na área adversária e
        # nenhuma outra checagem daqui perceberia.
        ok(goleiro["y"] > atacante["y"],
           "o campo virou de cabeça para baixo: o goleiro (y=92) ficou mais "
           "ALTO na tela que o atacante (y=16)")
        # E quem está no fundo tem que ser menor, senão a perspectiva não
        # existe — foi por isso que o disco ganhou a variável --e.
        ok(atacante["e"] < goleiro["e"] - 0.02,
           "o jogador do fundo parou de ser desenhado menor que o de perto")

    # ── 1b. o eixo central está no eixo central ─────────────────────────────
    # Cair na grama não basta: o gramado é largo, e a formação inteira pode
    # escorregar 10% para o lado com os onze jogadores ainda em cima dele.
    # Descobri isso trocando cx de 49,53 para 60 — o teste passou verde.
    # Aqui a conta é conferida contra a própria arte: na metade de cima da
    # imagem o verde é ladeado por preto, então o meio da faixa verde é, por
    # construção, o meio do campo.
    for v in (2, 12, 26, 40):
        p = _rodar(codigo, [[50, v]])
        if not p:
            break
        linha = round(p[0]["y"] * alt / 100)
        if not 0 <= linha < alt * 0.72:     # embaixo o verde vaza do gramado
            continue
        verdes = [x for x in range(X_MIN_GRAMADO, larg)
                  if px[x, linha][1] > 120
                  and px[x, linha][1] > px[x, linha][0] + 40
                  and px[x, linha][1] > px[x, linha][2] + 40]
        if not verdes:
            continue
        centro = (verdes[0] + verdes[-1]) / 2 * 100 / larg
        ok(abs(p[0]["x"] - centro) < 1.5,
           f"o eixo do campo saiu do lugar: em y={v} a projeção põe o meio em "
           f"{p[0]['x']:.1f}% e o gramado tem o meio em {centro:.1f}% — a "
           "formação inteira fica torta em relação à arte")

    # ── 2. as onze casas de cada formação caem na grama ─────────────────────
    pedidos, rotulos = [], []
    for nome, casas in formacoes.items():
        for x, y, g in casas:
            pedidos.append([x, y])
            rotulos.append(f"{nome} {g} ({x},{y})")

    for rotulo, p in zip(rotulos, _rodar(codigo, pedidos)):
        cx, cy = round(p["x"] * larg / 100), round(p["y"] * alt / 100)
        ok(_e_grama(px, cx, cy, larg, alt),
           f"{rotulo} caiu FORA do gramado da arte, em {p['x']:.1f}% x "
           f"{p['y']:.1f}% (pixel {cx},{cy})")

    # ── 3. as placas não se encavalam, e os setores respiram ────────────────
    # Era isto que faltava aqui: a checagem de "cai na grama" está satisfeita
    # com os onze empilhados no meio-campo. Foi o Vini quem viu ("tá tudo muito
    # junto"), olhando a tela, o que um teste devia ter visto antes.
    #
    # A largura da placa é medida com o nome MAIS COMPRIDO de cada setor. Um
    # elenco não tem onze "Abdulhamid", mas basta um numa posição apertada.
    from PIL import ImageDraw, ImageFont
    import escalacao_arte
    desenho = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    PIOR_NOME = {"G": "AL-OWAIS", "D": "ABDULHAMID",
                 "M": "MILINKOVIC", "A": "AL-DAWSARI"}
    # Distância mínima, em unidades de campo, entre as medianas de dois
    # setores vizinhos. A folga mais apertada hoje é 17 (defesa para goleiro).
    # Em 14 o teste passava verde com o meio-campo puxado 10 para trás — testei
    # a mutação; por isso o piso é 16 e não um número redondo qualquer.
    FAIXA_MINIMA = 16

    for nome, casas in formacoes.items():
        pontos = _rodar(codigo, [[x, y] for x, y, _ in casas])
        if len(pontos) != len(casas):
            continue
        placas = []
        for (x, y, g), p in zip(casas, pontos):
            esc = p["e"]
            fonte = ImageFont.truetype(
                os.path.join(RAIZ, "public", "fonts", "WorkSans-SemiBold-latin.ttf"),
                max(1, int(escalacao_arte.NOME_CORPO * esc)))
            cx, cy = p["x"] * larg / 100, p["y"] * alt / 100
            raio = escalacao_arte.FOTO_DIAM * esc / 2
            largura = (escalacao_arte.PLACA_PAD * 2 * esc
                       + escalacao_arte.BANDEIRA_ALT * 1.5 * esc
                       + escalacao_arte.PLACA_GAP * esc
                       + desenho.textlength(PIOR_NOME[g], font=fonte))
            topo = cy + raio - escalacao_arte.PLACA_SOBE * esc
            placas.append(dict(g=g, x=x, y=y, cy=cy, raio=raio,
                               x0=cx - largura / 2, x1=cx + largura / 2,
                               y0=topo, y1=topo + escalacao_arte.PLACA_ALT * esc))

        for i in range(len(placas)):
            a = placas[i]
            ok(a["x0"] >= 0 and a["x1"] <= larg,
               f"{nome}: a placa de ({a['x']},{a['y']}) sai da imagem")
            for b in placas[i + 1:]:
                if (a["x0"] < b["x1"] and b["x0"] < a["x1"]
                        and a["y0"] < b["y1"] and b["y0"] < a["y1"]):
                    ok(False, f"{nome}: a placa de ({a['x']},{a['y']}) encavala "
                              f"a de ({b['x']},{b['y']})")

        # Setores em faixas SEPARADAS, do ataque para o gol.
        #
        # Comparado pela mediana de y de cada setor, e não pela borda da placa
        # mais funda contra a foto mais alta do setor seguinte. Tentei assim
        # primeiro e dez formações "falharam" sem ter defeito nenhum: dentro de
        # um setor as posições são escalonadas de propósito (o lateral sobe, o
        # zagueiro recua), e dois jogadores em colunas opostas do campo podem
        # se cruzar na vertical sem encostar em nada. A sobreposição real já é
        # medida logo acima, placa contra placa.
        alturas = {}
        for g in "GDMA":
            ys = sorted(p["y"] for p in placas if p["g"] == g)
            if ys:
                alturas[g] = ys[len(ys) // 2]
        for antes, depois in (("A", "M"), ("M", "D"), ("D", "G")):
            if antes not in alturas or depois not in alturas:
                continue
            ok(alturas[depois] - alturas[antes] >= FAIXA_MINIMA,
               f"{nome}: o setor {depois} está a {alturas[depois] - alturas[antes]:.0f} "
               f"de {antes} — abaixo de {FAIXA_MINIMA} os setores deixam de ser "
               "faixas e a arte vira um amontoado, que foi como o Vini "
               "descreveu a versão anterior")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          f"  ✓ campo em perspectiva: {len(pedidos)} casas na grama, nenhuma "
          "placa encavalada, setores separados")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
