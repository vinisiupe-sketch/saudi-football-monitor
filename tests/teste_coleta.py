"""
O que a coleta considera sucesso.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR
    O RSSHub ficou quatro dias devolvendo tweets de 2025 no lugar da timeline.
    Feed válido, sem erro de rede, cinquenta itens dentro — e nenhum deles
    sobrevivia ao corte de idade do `parse_entries`.

    Pela contagem antiga, isso era `sources_ok = 45`. O app se declarava
    saudável enquanto nada entrava, e o boletim que eu abri para diagnosticar
    repetia a mentira de volta para mim.

    E havia uma segunda consequência, pior que a primeira. O `lookback_hours()`
    estica a janela de coleta quando `sources_ok == 0` — é o mecanismo de
    recuperação de queda, escrito depois de uma queda anterior. Ele ficou
    desligado durante a queda inteira, porque a contagem dizia que não havia
    queda. O marcador de "última coleta boa" foi avançando sozinho, a janela
    ficou grudada em duas horas, e quando a fonte voltou não havia mais como
    alcançar o buraco. Dois dias de notícia ficaram fora de alcance.

    Uma fonte que responde e não traz nada NÃO é uma fonte que funcionou.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


def _contagem(resultados):
    """Roda o trecho REAL de contagem do collect_all sobre resultados falsos.

    Extraio o laço do código de produção em vez de reescrevê-lo aqui. Já me
    queimei uma vez hoje escrevendo um teste que reimplementava a lógica que
    devia estar vigiando: ele passou verde com sete defeitos plantados, porque
    conferia a minha cópia e não o original.
    """
    fonte = open(os.path.join(RAIZ, "collector.py"), encoding="utf-8").read()
    arvore = ast.parse(fonte)
    fn = next((n for n in ast.walk(arvore)
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
               and n.name == "collect_all"), None)
    if fn is None:
        falhas.append("não achei collect_all")
        return {}
    laco = next((n for n in ast.walk(fn)
                 if isinstance(n, ast.For)
                 and isinstance(n.iter, ast.Name) and n.iter.id == "results"), None)
    if laco is None:
        falhas.append("não achei o laço que conta as fontes em collect_all")
        return {}
    escopo = {"results": resultados, "all_articles": [],
              "stats": {"sources_ok": 0, "sources_fail": 0, "sources_vazias": 0},
              "isinstance": isinstance, "Exception": Exception}
    exec(compile(ast.Module(body=[laco], type_ignores=[]), "<laco>", "exec"), escopo)
    return {**escopo["stats"], "artigos": len(escopo["all_articles"])}


def testar():
    falhas.clear()

    # ── 1. fonte que traz artigo é sucesso ─────────────────────────────────
    r = _contagem([[{"id": "a"}, {"id": "b"}], [{"id": "c"}]])
    conferir("duas fontes trouxeram", r.get("sources_ok"), 2)
    conferir("três artigos", r.get("artigos"), 3)
    conferir("nenhuma vazia", r.get("sources_vazias"), 0)

    # ── 2. fonte que responde VAZIA não é sucesso ──────────────────────────
    # É o caso do feed de 2025: responde, não erra, e não traz nada que
    # sobreviva ao corte de idade. Contar isso como OK foi o que escondeu
    # quatro dias de queda.
    r = _contagem([[], [], []])
    conferir("três vazias não são três sucessos", r.get("sources_ok"), 0)
    conferir("e são contadas como vazias", r.get("sources_vazias"), 3)
    conferir("nenhuma falha", r.get("sources_fail"), 0)

    # ── 3. erro continua sendo erro ────────────────────────────────────────
    r = _contagem([Exception("timeout"), None, [{"id": "x"}]])
    conferir("duas falhas", r.get("sources_fail"), 2)
    conferir("uma trouxe", r.get("sources_ok"), 1)

    # ── 4. o misto ─────────────────────────────────────────────────────────
    r = _contagem([[{"id": "1"}], [], Exception("x"), [], [{"id": "2"}]])
    conferir("mistura: trouxeram", r.get("sources_ok"), 2)
    conferir("mistura: vazias", r.get("sources_vazias"), 2)
    conferir("mistura: falhas", r.get("sources_fail"), 1)

    # ── 5. a janela precisa esticar quando ninguém trouxe nada ─────────────
    # Este é o elo que faltava. Não adianta contar direito se o mecanismo de
    # recuperação não estiver preso a essa contagem.
    fonte_s = open(os.path.join(RAIZ, "scheduler.py"), encoding="utf-8").read()
    ok("if log[\"sources_ok\"] > 0:" in fonte_s,
       "o marcador de última coleta boa deixou de depender de sources_ok — "
       "sem isso a janela nunca mais estica depois de uma queda")
    arvore_s = ast.parse(fonte_s)
    fn_look = next((n for n in ast.walk(arvore_s)
                    if isinstance(n, ast.FunctionDef) and n.name == "lookback_hours"), None)
    ok(fn_look is not None, "sumiu o lookback_hours")
    if fn_look:
        corpo = ast.unparse(fn_look)
        ok("LAST_COLLECT_KEY" in corpo,
           "a janela deixou de ser calculada a partir da última coleta boa")

    # ── 6. o boletim precisa guardar os dois números novos ─────────────────
    # Sem eles, a próxima vez que isto acontecer eu vou de novo ficar rodadas
    # inteiras adivinhando se a origem secou ou se o filtro daqui descartou.
    fonte_d = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    for pedaco in ("sources_vazias", "articles_raw"):
        ok(f"ADD COLUMN IF NOT EXISTS {pedaco}" in fonte_d,
           f"o boletim não guarda {pedaco}")
        ok(fonte_d.count(pedaco) >= 2,
           f"{pedaco} existe como coluna mas não é gravado")
    ok('log["articles_raw"] = len(' in fonte_s,
       "o número de artigos que a COLETA produziu não está sendo registrado — "
       "é ele que separa 'a fonte secou' de 'o filtro daqui descartou'")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ coleta: fonte que não traz nada não conta como fonte que funcionou")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
