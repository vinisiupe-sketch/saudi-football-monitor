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

# O recorte com que as constantes de projetar() foram medidas. Está aqui para
# que trocar a arte por outra de enquadramento diferente falhe ALTO, em vez de
# silenciosamente empurrar os jogadores para fora da grama.
TAMANHO_ESPERADO = (860, 635)

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
    """_ELENCOS_FORMACOES lido do próprio main.py, sem importar o módulo."""
    for no in ast.walk(ast.parse(FONTE)):
        if (isinstance(no, ast.Assign)
                and any(getattr(a, "id", "") == "_ELENCOS_FORMACOES"
                        for a in no.targets)):
            return ast.literal_eval(no.value)
    return {}


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

    # ── 1. os marcos: a projeção passa pelas linhas que ela diz passar ───────
    marcos = _rodar(codigo, [[50, 0], [50, 50], [50, 100], [50, 92], [50, 16]])
    if len(marcos) == 5:
        longe, meio, perto, goleiro, atacante = marcos
        for nome, deu, esperado in (("linha de fundo de longe", longe["y"], 5.98),
                                    ("meio-campo", meio["y"], 32.91),
                                    ("linha de fundo de perto", perto["y"], 89.92)):
            ok(abs(deu - esperado) < 0.6,
               f"a projeção deixou de cair no {nome} da arte: deu {deu:.2f}%, "
               f"a linha está em {esperado}%")

        # Orientação. O ataque é para CIMA (y=16 no ataque, y=92 no gol) desde
        # que a guia existe; inverter isso põe o goleiro na área adversária e
        # nenhuma outra checagem daqui perceberia.
        ok(goleiro["y"] > atacante["y"],
           "o campo virou de cabeça para baixo: o goleiro (y=92) ficou mais "
           "ALTO na tela que o atacante (y=16)")
        # E quem está no fundo tem que ser menor, senão a perspectiva não
        # existe — foi por isso que o disco ganhou a variável --e.
        ok(atacante["e"] < goleiro["e"] - 0.05,
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
        if not 0 <= linha < alt * 0.6:      # embaixo o verde vaza do gramado
            continue
        verdes = [x for x in range(larg)
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

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          f"  ✓ campo em perspectiva: {len(pedidos)} casas, todas na grama")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
