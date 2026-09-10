"""
Filtro por clube na guia Lesões, e a sub-aba que confere na API.

POR QUE A SUB-ABA EXISTE
    O monitor de lesões lê NOTÍCIA. Ele é bom no que a imprensa cobre — o
    titular do Al-Hilal que rompeu o ligamento sai em todo lugar — e cego no
    que ela não cobre: o reserva do Al-Fayha que ninguém noticiou não existe
    para ele. A API-Football vê a lista oficial de ausentes, sem passar pelo
    interesse editorial de ninguém.

    Nenhuma das duas manda na outra, então a tela mostra as duas e marca a
    diferença. Fonte que discorda da outra é informação, não defeito.

A ARMADILHA QUE ESTE ARQUIVO VIGIA DE PERTO
    A API-Football só devolve ausências onde `coverage.injuries` é verdadeiro.
    Se a liga saudita não estiver coberta, a chamada volta com sucesso e lista
    VAZIA. Na tela, "a API não cobre isto" e "ninguém está machucado" seriam a
    mesma tela em branco — e a segunda leitura é a que o Vini faria, porque é
    a que faz sentido numa guia de lesões. Publicar uma escalação confiando
    nisso é o estrago.

    Por isso a rota devolve `cobertura` e a tela diz qual dos dois casos é.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _corpo(nome_da_funcao: str) -> str:
    """O código-fonte de uma função só, para não varrer o main.py inteiro."""
    mod = ast.parse(FONTE)
    for n in ast.walk(mod):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name == nome_da_funcao:
            return ast.get_source_segment(FONTE, n) or ""
    return ""


def testar():
    falhas.clear()
    tela = _corpo("_page_lesoes_impl")
    rota = _corpo("api_ausencias_af")

    ok(tela, "sumiu a função que monta a guia Lesões")
    ok(rota, "sumiu a rota que consulta as ausências na API-Football")

    # ── 1. o filtro por clube ────────────────────────────────────────────
    ok('data-clube="' in tela,
       "o card de lesão perdeu o data-clube — é por ele que o filtro esconde "
       "e mostra")
    ok("_html.escape(club" in tela,
       "o nome do clube entra no atributo sem escapar. Ele vem de notícia "
       "raspada: um nome com aspas fecha o atributo cedo e quebra o card")
    ok('id="filtroClube"' in tela and "filtrarPorClube()" in tela,
       "sumiu o seletor de clube da guia Lesões")
    ok("opcoes_clube" in tela,
       "as opções do filtro deixaram de ser montadas no servidor")
    # A lista sai das lesões que ESTÃO na tela. Clube sem ninguém machucado
    # como opção é uma opção que só devolve tela vazia.
    ok("for i in injuries" in tela and 'i.get("club")' in tela,
       "a lista de clubes do filtro não vem mais das lesões carregadas")
    ok("contaAtivas" in tela and "conta.textContent" in tela,
       "a contagem ao lado do título não acompanha mais o filtro — a tela "
       "mostraria três cards com o título dizendo 'Ativas (37)'")
    # Os DOIS lados: criar o recado e reencontrá-lo na volta seguinte. Sem o
    # querySelector, cada troca de clube empilharia um recado novo; sem a
    # criação, não há recado nenhum. A primeira versão deste teste só
    # procurava o nome da classe, e passava com o querySelector arrancado —
    # porque o nome continuava escrito na linha que cria o elemento.
    ok("querySelector('.lsn-filtro-vazio')" in tela,
       "o filtro parou de reencontrar o recado de seção vazia — cada troca "
       "de clube passa a empilhar um recado novo embaixo do anterior")
    ok("'empty-state lsn-filtro-vazio'" in tela,
       "sumiu a criação do recado de seção vazia: filtrar por um clube sem "
       "ninguém machucado devolveria um branco com cara de tela quebrada")

    # ── 2. as sub-abas ───────────────────────────────────────────────────
    ok("mostrarLesoes(" in tela and "lsnPainel-api" in tela,
       "sumiu a sub-aba que confere as ausências na API")
    ok("_lsnApiCarregada" in tela,
       "a busca na API perdeu a trava de uma vez só. Ela gasta chamada da "
       "assinatura, e recarregar a cada toque na aba gasta à toa")
    ok("if (qual === 'api' && !_lsnApiCarregada)" in tela,
       "a consulta à API deixou de esperar você abrir a aba")

    # ── 3. cobertura: o modo de falhar que engana ────────────────────────
    ok('"leagues"' in rota and "coverage" in rota,
       "a rota parou de conferir o coverage.injuries da liga. Sem isso, "
       "'a API não cobre' e 'ninguém machucado' viram a mesma tela vazia")
    ok('"cobertura"' in rota,
       "a resposta da rota não traz mais o campo `cobertura`")
    ok("d.cobertura === false" in tela,
       "a tela parou de distinguir lista vazia por falta de cobertura de "
       "lista vazia por não haver ninguém fora")
    ok("NÃO quer dizer" in tela,
       "sumiu o aviso que explica que a lista vazia sem cobertura não "
       "significa que não há ninguém fora")

    # ── 4. suspensão vem junto, e o tipo cru não se perde ────────────────
    ok("suspend" in rota and "Suspensão" in rota,
       "a rota parou de reconhecer suspensão. O mesmo endpoint da API "
       "devolve lesão E suspensão, e a suspensão é metade do valor dele")
    ok('"tipo_bruto"' in rota,
       "sumiu o tipo_bruto. A API também escreve 'Missing Fixture' e "
       "'Questionable'; traduzir só o que eu previ apaga o resto")

    # ── 5. cruzar com o nosso monitor sem inventar ───────────────────────
    ok("no_nosso_monitor" in rota and "no_nosso_monitor" in tela,
       "sumiu a marca de quem só a API tem — que é o motivo da aba existir")
    # A normalização de nome, exercitada de verdade — e não procurada no
    # texto. Rodo só ESTA função, num espaço com re e unicodedata, porque ela
    # é pura e o main.py inteiro não sobe sem banco.
    chave_src = _corpo("_chave_de_nome")
    ok(chave_src, "sumiu a normalização de nome usada para cruzar as fontes")
    if chave_src:
        import re as _re
        import unicodedata as _ud
        ns = {"re": _re, "unicodedata": _ud}
        exec(compile(ast.Module(body=[ast.parse(chave_src).body[0]],
                                type_ignores=[]), "<chave>", "exec"), ns)
        chave = ns["_chave_de_nome"]

        ok(chave("Cristiano  RONALDO ") == chave("cristiano ronaldo"),
           "caixa e espaço sobrando voltaram a ser diferença de pessoa")
        ok(chave("Ângelo") == chave("Angelo"),
           "acento voltou a ser diferença: a API escreve 'Angelo' e o "
           "matchsheet escreve 'Ângelo'")
        ok(chave("A. Boulbina") == chave("A Boulbina"),
           "a pontuação do nome abreviado voltou a contar")
        # E o limite: casar por pedaço do nome poria o jogador errado na tela.
        ok(chave("N. Fekir") != chave("Nabil Fekir"),
           "a comparação passou a casar nome abreviado com nome completo. "
           "'N. Fekir' e 'Nabil Fekir' são provavelmente a mesma pessoa — mas "
           "'N. Silva' e 'Neymar Silva' também seriam, e aí a tela marca como "
           "conferido um jogador que ninguém conferiu")
        ok(chave("") == "" and chave(None) == "",
           "nome vazio deixou de virar chave vazia e pode casar com qualquer "
           "outro nome vazio")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ Lesões: filtro por clube com contagem viva, e a aba da API "
          "sabendo a diferença entre 'ninguém fora' e 'a API não sabe'")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
