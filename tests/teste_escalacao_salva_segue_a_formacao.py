"""A escalação salva guarda QUEM joga, não onde fica o círculo.

O QUE ELE VIU (18/09/26)
    Logo depois de o trio da 4-3-3 ser invertido:

        "Quando eu clico, por exemplo, no Al Hilal, carrega errado primeiro, e
         aí eu troco pra qualquer uma e quando eu volto pra 4-3-3 tá certa,
         como eu queria."

    A escalação salva dele guardava o x e o y de cada casa — uma CÓPIA da
    tabela de formações, congelada no dia em que ele salvou. A tabela mudou; a
    cópia não. Abrir o clube trazia o desenho velho; trocar de formação e
    voltar recalculava pela tabela e acertava.

    É a mesma doença que este projeto já tratou no glossário (duas telas com
    dois nomes), nos ajustes (uma segunda lista na página) e nas formações (uma
    grade regular escondida no elenco_tm). Segunda cópia apodrece — e apodrece
    em silêncio, porque nada quebra: a tela só fica errada.

POR QUE DERIVAR É SEGURO AQUI
    Arrastar no campinho TROCA JOGADOR DE VAGA; nunca move a vaga. O x e o y
    de uma escalação salva, portanto, nunca foram escolha dele — são sempre o
    que a tabela disse naquele dia. O que só ele sabe é quem ocupa cada uma.

A GUARDA QUE IMPEDE O ESTRAGO
    Uma escalação salva a partir do jogo real traz as posições da API-Football,
    que NÃO saem desta tabela. Por isso o recálculo só vale quando o molde bate
    casa a casa no setor; fora disso, o que está salvo manda, como antes. Sem
    essa guarda, um zagueiro poderia ir parar na vaga de um atacante.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

PAGINA = open(os.path.join(RAIZ, "public", "campinho.html"),
              encoding="utf-8").read()

falhas = []


def ok(cond, msg):
    if not cond:
        falhas.append(msg)


def _node():
    for nome in ("node", "nodejs"):
        try:
            if subprocess.run([nome, "--version"], capture_output=True,
                              timeout=20).returncode == 0:
                return nome
        except Exception:
            continue
    return ""


# ─────────────────────────────────────────────────────────────────────────
# 1. A FUNÇÃO DE VERDADE, RECORTADA DA PÁGINA E EXECUTADA
# ─────────────────────────────────────────────────────────────────────────
# Recorto o `aplicarSalva` do arquivo e rodo no node. Reescrever a lógica aqui
# seria o teste conferindo a si mesmo — a regra do teste_campo_perspectiva, que
# nasceu do mesmo tipo de engano.
NODE = _node()
if not NODE:
    print("  (sem node neste ambiente — pulando a execução)")
else:
    _i = PAGINA.index("function aplicarSalva(){")
    _corpo = PAGINA[_i:PAGINA.index("\nfunction ", _i + 10)]
    # SÓ O MIOLO QUE MONTA OS SLOTS. O resto da função mexe no DOM, que não
    # existe no node — e o cabeçalho `function aplicarSalva(){` sozinho deixa
    # uma chave aberta que derruba o script inteiro com um erro de sintaxe que
    # não tem nada a ver com o que se quer medir.
    _monta = _corpo[_corpo.index("  const molde"):
                    _corpo.index("  if (SALVA.formacao)")]

    QUADRO_NOVO = [{"x": 50, "y": 99, "g": "G"},
                   {"x": 4, "y": 88, "g": "D"}, {"x": 96, "y": 88, "g": "D"},
                   {"x": 12, "y": 20.4, "g": "A"}, {"x": 50, "y": 4, "g": "A"},
                   {"x": 88, "y": 20.4, "g": "A"}]
    # O que ficou salvo no banco: o desenho ANTIGO, com o trio achatado.
    SALVO_VELHO = [{"x": 50, "y": 99, "g": "G", "id": "gk"},
                   {"x": 4, "y": 88, "g": "D", "id": "z1"},
                   {"x": 96, "y": 88, "g": "D", "id": "z2"},
                   {"x": 12, "y": 4, "g": "A", "id": "pe"},
                   {"x": 50, "y": 20.4, "g": "A", "id": "ca"},
                   {"x": 88, "y": 4, "g": "A", "id": "pd"}]

    def rodar(salva, formacoes):
        script = (
            "const FORMACOES = " + json.dumps(formacoes) + ";\n"
            "const SALVA = " + json.dumps(salva) + ";\n"
            "let SLOTS = [];\n" + _monta + "\n"
            "console.log(JSON.stringify(SLOTS));\n")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(script)
            caminho = f.name
        try:
            r = subprocess.run([NODE, caminho], capture_output=True, text=True,
                               timeout=30)
            if r.returncode != 0:
                falhas.append("o aplicarSalva nem roda: "
                              + (r.stderr or "").strip()[-200:])
                return []
            return json.loads(r.stdout)
        finally:
            try:
                os.unlink(caminho)
            except Exception:
                pass

    # ── O CASO DELE ──────────────────────────────────────────────────────
    saida = rodar({"formacao": "4-3-3", "slots": SALVO_VELHO},
                  {"4-3-3": QUADRO_NOVO})
    if saida:
        por_id = {s["id"]: (s["x"], s["y"]) for s in saida}
        ok(por_id.get("ca") == (50, 4),
           f"o centroavante da escalação salva ficou em {por_id.get('ca')} e "
           f"não em (50, 4). A tela abriu com o desenho congelado no dia em "
           f"que ele salvou — é exatamente o que ele viu ao clicar no Al Hilal")
        ok(por_id.get("pe") == (12, 20.4) and por_id.get("pd") == (88, 20.4),
           f"as pontas não recuaram: {por_id.get('pe')} e {por_id.get('pd')}")
        # E OS JOGADORES NÃO PODEM TER TROCADO DE LUGAR ENTRE SI.
        ok([s["id"] for s in saida] == [s["id"] for s in SALVO_VELHO],
           "a ordem dos jogadores mudou ao recalcular as posições. Quem está "
           "em cada vaga é a única coisa que a escalação salva realmente sabe")

    # ── A GUARDA: SETOR DIFERENTE, NÃO MEXE ──────────────────────────────
    #
    # Uma escalação salva a partir do jogo real vem com as posições da
    # API-Football. Se eu recalculasse por índice sem conferir o setor, um
    # zagueiro poderia ir parar na vaga de um atacante — o estrago seria maior
    # que o defeito.
    DO_JOGO = [dict(s) for s in SALVO_VELHO]
    DO_JOGO[1]["g"] = "M"
    DO_JOGO[1]["x"], DO_JOGO[1]["y"] = 33, 61
    saida2 = rodar({"formacao": "4-3-3", "slots": DO_JOGO},
                   {"4-3-3": QUADRO_NOVO})
    if saida2:
        ok((saida2[1]["x"], saida2[1]["y"]) == (33, 61),
           f"a guarda de setor não segurou: a casa veio de um jogo real, com "
           f"setor diferente do molde, e foi recalculada assim mesmo "
           f"({saida2[1]['x']},{saida2[1]['y']})")

    # ── FORMAÇÃO QUE NÃO ESTÁ NA TABELA ──────────────────────────────────
    saida3 = rodar({"formacao": "4-6-0 do jogo", "slots": SALVO_VELHO},
                   {"4-3-3": QUADRO_NOVO})
    if saida3:
        ok((saida3[4]["x"], saida3[4]["y"]) == (50, 20.4),
           "uma formação fora da tabela foi recalculada com o molde de outra")

    # ── TAMANHO DIFERENTE NÃO PODE QUEBRAR ───────────────────────────────
    saida4 = rodar({"formacao": "4-3-3", "slots": SALVO_VELHO[:4]},
                   {"4-3-3": QUADRO_NOVO})
    ok(len(saida4) == 4,
       "com o molde e a escalação de tamanhos diferentes a tela quebrou, em "
       "vez de ficar com o que estava salvo")


# ─────────────────────────────────────────────────────────────────────────
# 2. E A FORMA, para o dia em que alguém desfizer isto sem querer
# ─────────────────────────────────────────────────────────────────────────
_bloco = PAGINA[PAGINA.index("function aplicarSalva(){"):]
_bloco = _bloco[:_bloco.index("\nfunction ", 10)]
_sem_comentario = "\n".join(l for l in _bloco.split("\n")
                            if not l.strip().startswith("//"))
ok("FORMACOES[SALVA.formacao]" in _sem_comentario,
   "o carregamento da escalação salva parou de consultar a tabela de "
   "formações. Ele volta a mostrar as coordenadas congeladas no banco, e a "
   "próxima vez que um arranjo mudar o Vini vai ver o desenho velho de novo")
ok(re.search(r"c\.g\s*===?\s*SALVA\.slots\[i\]\.g", _sem_comentario),
   "sumiu a guarda que compara o setor casa a casa. Sem ela, uma escalação "
   "vinda do jogo real seria remontada pelo molde e um zagueiro poderia ir "
   "parar na vaga de um atacante")


if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print("✅ a escalação salva segue a formação de hoje, e não a do dia em que "
      "foi salva")
