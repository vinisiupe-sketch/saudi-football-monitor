"""Contrato do laboratório: estrutura completa e zero consumo pelo app atual."""
import ast
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def testar():
    with open(os.path.join(RAIZ, "database.py"), encoding="utf-8") as f:
        banco = f.read()
    with open(os.path.join(RAIZ, "main.py"), encoding="utf-8") as f:
        main = f.read()
    with open(os.path.join(RAIZ, "public", "glossario-lab.html"), encoding="utf-8") as f:
        tela = f.read()

    ast.parse(banco)
    ast.parse(main)

    assert "CREATE TABLE IF NOT EXISTS glossario_lab_jogador" in banco
    assert "CREATE TABLE IF NOT EXISTS glossario_lab_nome" in banco
    assert "CREATE TABLE IF NOT EXISTS glossario_lab_candidato" in banco
    assert "id              SERIAL PRIMARY KEY" in banco
    assert "spl_id          TEXT UNIQUE" in banco
    assert "ON CONFLICT (jogador_id, fonte, idioma, tipo, nome) DO NOTHING" in banco
    assert "def listar_glossario_lab" in banco
    assert "def adicionar_nome_glossario_lab" in banco
    assert "def buscar_na_fonte_glossario_lab" in banco
    assert "def vincular_fonte_glossario_lab" in banco
    assert "def desvincular_fonte_glossario_lab" in banco
    assert "def salvar_candidatos_glossario_lab" in banco
    assert "def salvar_nome_pais_origem_transfermarkt_lab" in banco
    assert '@app.get("/glossario-lab"' in main
    assert '@app.get("/api/glossario-lab"' in main
    assert 'fontes/{fonte}/buscar' in main
    assert 'fontes/vincular' in main
    assert 'fontes/{fonte}' in main
    assert 'transfermarkt/nome-origem' in main
    assert "Base paralela · não está ligada ao app" in tela
    assert "abrirBuscaFonte" in tela
    assert "Pesquisar e vincular nesta fonte" in tela
    assert "Cada vínculo é salvo automaticamente" in tela
    assert "desvincularFonte" in tela
    assert "af_bloqueado" in banco and "tm_bloqueado" in banco
    assert "resumo_clube" in main + banco + tela
    assert '"players/profiles"' in main
    assert "colunasComVazio" in tela and "data-ordem=\"api_football\"" in tela
    assert "capturarNomeTM" in tela
    with open(os.path.join(RAIZ, "elenco_tm.py"), encoding="utf-8") as f:
        tm = f.read()
    assert "def _parse_nome_pais_origem" in tm
    assert "name in home country" in tm
    assert 'soup.find_all(["span", "th", "dt"])' in tm
    assert '"info-table__content--bold" not in classes' in tm
    assert "'informacoes e fatos'" in banco
    for coluna in ("SPL em inglês", "SPL em árabe", "API-Football",
                   "Transfermarkt", "PDF", "Notícias árabes"):
        assert coluna in tela

    # A garantia mais importante desta fase: os motores atuais não conhecem
    # as tabelas do laboratório e, portanto, não podem consultá-las por acaso.
    for arquivo in ("elos.py", "mercado.py", "matchsheet.py", "injury_processor.py"):
        with open(os.path.join(RAIZ, arquivo), encoding="utf-8") as f:
            assert "glossario_lab_" not in f.read(), arquivo

    # A imagem enxuta de testes locais não traz o driver do PostgreSQL. Para
    # testar a função pura de normalização, basta um módulo vazio no import;
    # nenhuma conexão é aberta aqui.
    if "psycopg2" not in sys.modules:
        falso = types.ModuleType("psycopg2")
        falso_extras = types.ModuleType("psycopg2.extras")
        falso.extras = falso_extras
        sys.modules["psycopg2"] = falso
        sys.modules["psycopg2.extras"] = falso_extras
    import database
    assert database._normalizar_nome_do_lab("Théo Hernández", "lat") == "theo hernandez"
    assert database._normalizar_nome_do_lab("محمد الدَّوسري", "ar") == \
        database._normalizar_nome_do_lab("محمد الدوسري", "ar")

    print("  glossário lab: base paralela, fontes e tela conferidas")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
