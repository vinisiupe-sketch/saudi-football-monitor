"""
As chaves que o código lê têm que existir nas tabelas.

POR QUE ISTO EXISTE
    Escrevi `l.get("player")` onde a coluna é `player_name`, e
    `a.get("source")` onde é `source_name`. Nenhum dos dois levanta erro:
    `.get` devolve None, o campo vira "" e o programa segue.

    O resultado chegou até o relatório. Ele saiu dizendo "8 desfalques sem
    nomes divulgados" — uma frase perfeitamente coerente, tecnicamente
    verdadeira sobre os dados que EU mandei, e completamente inútil. Nenhum
    teste pegou porque não havia erro: havia um buraco.

    Este teste lê o CREATE TABLE de cada tabela e cobra que toda chave lida
    de uma linha dessa tabela exista de verdade.

O QUE ELE NÃO PEGA
    Só confere os acessos que consigo amarrar a uma tabela pela variável do
    laço. Não é cobertura completa — é a rede no lugar onde eu já caí duas
    vezes no mesmo dia.
"""
import ast
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

falhas = []


def colunas_das_tabelas(fonte: str) -> dict:
    """{tabela: {colunas}} lido dos CREATE TABLE e dos ADD COLUMN."""
    tabelas = {}
    for m in re.finditer(
            r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\s*\)", fonte, re.S):
        nome, corpo = m.group(1), m.group(2)
        cols = set()
        for linha in corpo.split("\n"):
            linha = linha.strip().strip(",")
            if not linha or linha.upper().startswith(("PRIMARY", "UNIQUE", "FOREIGN")):
                continue
            primeira = linha.split()[0]
            if re.fullmatch(r"\w+", primeira):
                cols.add(primeira)
        tabelas[nome] = cols
    for m in re.finditer(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", fonte):
        tabelas.setdefault(m.group(1), set()).add(m.group(2))
    return tabelas


# As funções que devolvem linhas de uma tabela, e de qual tabela. Escrito à
# mão porque adivinhar isso do código daria falso positivo — e teste que grita
# à toa é teste que a gente aprende a ignorar.
FONTES_DE_LINHA = {
    "get_injuries": "injuries",
    "get_recent_articles": "articles",
    "get_low_score_articles": "articles",
    "get_flagged_articles": "articles",
    "get_trashed_articles": "articles",
    "listar_posts": "post_fila",
    "previas_do_dia": "previa",
    "arbitragem_do_dia": "arbitragem",
    "listar_usuarios": "usuario",
    "listar_convites": "convite",
}

# Chaves que o próprio código acrescenta depois de ler do banco — não são
# colunas e não deveriam ser cobradas como tal.
ACRESCENTADAS = {
    "articles": {"flag", "comment"},
    "post_fila": {"escudos", "canais", "imagens"},
    "previa": {"chave", "suspeitos", "fatos"},
    "arbitragem": {"papeis"},
    "usuario": {"papel"},
}


def conferir(arquivo: str, tabelas: dict):
    caminho = os.path.join(RAIZ, arquivo)
    if not os.path.exists(caminho):
        return
    arvore = ast.parse(open(caminho, encoding="utf-8").read())
    for laco in ast.walk(arvore):
        if not isinstance(laco, ast.For):
            continue
        chamada = laco.iter
        # for x in funcao(...) — e também dentro de compreensão simples
        if not (isinstance(chamada, ast.Call) and isinstance(chamada.func, ast.Name)):
            continue
        tabela = FONTES_DE_LINHA.get(chamada.func.id)
        if not tabela or tabela not in tabelas:
            continue
        if not isinstance(laco.target, ast.Name):
            continue
        var = laco.target.id
        validas = tabelas[tabela] | ACRESCENTADAS.get(tabela, set())
        for n in ast.walk(laco):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == var
                    and n.args and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str)):
                chave = n.args[0].value
                if chave not in validas:
                    falhas.append(
                        f"{arquivo}: lê {var}.get({chave!r}) de {tabela}, "
                        f"que não tem essa coluna")


def testar():
    falhas.clear()
    fonte_db = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    tabelas = colunas_das_tabelas(fonte_db)

    # Sanidade do próprio leitor: se ele parar de achar as tabelas, o teste
    # passaria vazio e eu acharia que está tudo certo.
    for esperada in ("articles", "injuries", "post_fila", "usuario", "previa",
                     "arbitragem", "convite", "transmissao"):
        if esperada not in tabelas:
            falhas.append(f"não achei a tabela {esperada} no database.py")
    if tabelas.get("injuries") and "player_name" not in tabelas["injuries"]:
        falhas.append("o leitor de colunas não está lendo injuries direito")

    for arquivo in ("main.py", "processor.py", "scheduler.py", "injury_processor.py"):
        conferir(arquivo, tabelas)

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    print(f"  ✓ colunas: {len(tabelas)} tabelas, nenhuma chave lida que não exista")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
