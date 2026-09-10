"""
Reler uma partida tem que SUBSTITUIR o que estava gravado sobre ela.

O QUE ACONTECEU (10/09/26)
    O Vini tocou em "Reler tudo" e o Óscar Rodríguez continuou sem o alerta de
    conduta violenta, mesmo com a explicação nova já no rodapé da tela.

    A causa foi uma decisão minha que parecia conservadora. `registrar_cartao`
    grava com ON CONFLICT DO NOTHING, no princípio de que "cartão é um fato de
    um instante e não deve ser reescrito". O princípio está certo. A conclusão
    estava errada, porque o que muda na releitura não é o fato — é o que eu
    sei sobre ele.

    Quando o acréscimo entrou na chave única, o vermelho dele, gravado antes
    como (minuto 90, extra 0, motivo vazio), deixou de colidir com o mesmo
    cartão relido como (minuto 90, extra 6, motivo "Violent conduct"). Não
    havia conflito, então o DO NOTHING não fez nada: ele INSERIU o segundo ao
    lado do primeiro.

    Dois registros do mesmo cartão. E como a regra lia o primeiro vermelho da
    partida em ordem de minuto e acréscimo, quem respondia era a linha velha,
    sem motivo. O alerta não aparecia — e, pior, os amarelos em acréscimo
    passaram a contar em dobro.

A REGRA QUE FICA
    A lista de eventos de uma partida ENCERRADA é a verdade sobre ela. Esta
    tabela é um espelho dessa lista, não um acúmulo de tudo que já achei sobre
    ela. Por isso a releitura apaga os cartões daquela partida antes de
    gravar: assim ela é idempotente — dá para rodar dez vezes e o resultado é
    o mesmo — e assim uma correção no jeito de LER alcança o que já foi lido.

    A ordem é parte da regra: apagar só DEPOIS de a chamada à API ter dado
    certo. Invertido, uma falha de rede viraria perda de dado.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
BANCO = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _corpo(fonte: str, nome: str) -> str:
    for n in ast.walk(ast.parse(fonte)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome:
            return ast.get_source_segment(fonte, n) or ""
    return ""


def testar():
    falhas.clear()
    coletor = _corpo(FONTE, "_coletar_cartoes")
    apagar = _corpo(BANCO, "apagar_cartoes_da_partida")

    ok(coletor, "sumiu o coletor de cartões")
    ok(apagar, "sumiu a função que zera os cartões de uma partida")

    # ── 0. a função apaga MESMO ──────────────────────────────────────────
    # Não basta o coletor chamá-la: ela precisa mandar o DELETE. Rodo a função
    # de verdade contra um banco de mentira que só anota o SQL recebido — a
    # primeira versão deste arquivo checava só o texto do código e passava
    # com o corpo da função trocado por `pass`.
    if apagar:
        executados = []

        class _Cursor:
            rowcount = 3

            def execute(self, sql, params=None):
                executados.append((" ".join(sql.split()), params))

            def fetchall(self):
                return []

        class _Conn:
            def cursor(self, *a, **k):
                return _Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        ns = {"get_conn": lambda: _Conn(), "_cria_cartao": lambda c: None}
        exec(compile(ast.Module(body=[ast.parse(apagar).body[0]],
                                type_ignores=[]), "<apagar>", "exec"), ns)
        n = ns["apagar_cartoes_da_partida"](12345)

        deletes = [sql for sql, _ in executados if sql.upper().startswith("DELETE")]
        ok(deletes,
           "apagar_cartoes_da_partida não manda DELETE nenhum. O coletor "
           "chama, o contador sobe, a tela diz que substituiu — e o registro "
           "velho continua lá")
        ok(any("FROM cartao" in s and "fixture_id" in s for s in deletes),
           f"o DELETE não é o esperado: {deletes}")
        ok(any(p == [12345] for _, p in executados),
           "o DELETE não recebeu o id da partida — ou apaga a tabela inteira, "
           "ou não apaga nada")
        ok(n == 3, f"a função devia devolver quantas linhas apagou, devolveu {n!r}")

    # ── 1. a releitura substitui ─────────────────────────────────────────
    ok("apagar_cartoes_da_partida(fid)" in coletor,
       "o coletor voltou a só INSERIR. Com ON CONFLICT DO NOTHING e uma chave "
       "que mudou, a releitura empilha em vez de corrigir: foi assim que o "
       "vermelho do Óscar Rodríguez ficou gravado duas vezes, e quem "
       "respondia era a linha velha, sem o motivo")

    # ── 2. a ORDEM: só apaga depois de a chamada dar certo ───────────────
    # Esta é a parte que, se sair do lugar, transforma uma falha de rede em
    # perda de dado — e de um jeito que só aparece no dia em que a API cai.
    i_chamada = coletor.find('await _af_get("fixtures/events"')
    i_erro = coletor.find('diag["erros"].append(f"jogo {fid}', i_chamada)
    i_apaga = coletor.find("apagar_cartoes_da_partida(fid)")
    ok(-1 < i_chamada < i_erro < i_apaga,
       "o apagar saiu de lugar. Ele TEM que vir depois da chamada à API e "
       "depois do tratamento de erro: apagando antes, uma falha de rede "
       "apaga os cartões da partida e não grava nada no lugar")
    ok("continue" in coletor[i_erro:i_apaga],
       "sumiu o `continue` que interrompe a partida quando a chamada falha — "
       "sem ele o fluxo segue e apaga mesmo com erro")

    # ── 3. o motivo é lido do vermelho que TEM motivo ────────────────────
    regra = _corpo(FONTE, "_situacao_dos_cartoes")
    ok('if x == "vermelho") if m), "")' in regra,
       "a busca do motivo voltou a pegar o primeiro vermelho da lista em vez "
       "do primeiro que tem motivo. É a segunda linha de defesa do mesmo "
       "problema: se por qualquer razão houver uma linha antiga sem motivo "
       "antes da boa, o alerta some de novo")

    # ── 4. o botão vai até o fim sozinho ─────────────────────────────────
    ok("PD_MAX_PASSADAS" in FONTE,
       "sumiu o teto de passadas da releitura — um erro de contagem meu "
       "viraria um laço consumindo a assinatura sem ninguém olhando")
    ok("for (passada = 1; passada <= PD_MAX_PASSADAS" in FONTE,
       "o 'Reler tudo' voltou a fazer UMA passada. Ele lê um punhado de jogos "
       "por vez; com uma passada só, o jogo que o Vini foi conferir "
       "provavelmente não entrou — foi exatamente o que aconteceu, e ele "
       "concluiu, com razão, que o botão não tinha funcionado")
    ok("if (!d.faltam || !d.partidas_lidas) break;" in FONTE,
       "a releitura perdeu a condição de parada. Sem ela, ou ela para cedo "
       "demais ou roda o teto inteiro à toa")
    ok("passada === 1 ? '?refazer=1' : ''" in FONTE,
       "o refazer=1 saiu da PRIMEIRA passada, ou passou a ir em todas. Se for "
       "em todas, cada passada apaga as marcas que a anterior acabou de "
       "gravar e a releitura nunca termina")

    # ── 5. e o resultado aparece na tela ─────────────────────────────────
    ok("cartoes_apagados" in FONTE and "substituído(s)" in FONTE,
       "a tela não diz quantos registros antigos foram substituídos — é o "
       "número que responde 'a releitura fez alguma coisa?'")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ releitura: espelha a partida, apaga só depois de a API "
          "responder, e o botão vai até o fim")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
