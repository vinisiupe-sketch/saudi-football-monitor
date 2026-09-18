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
    # O AVISO DO TOPO TEM DE DIZER A VERDADE (18/09/26)
    #
    # Ele dizia "Base paralela · não está ligada ao app" e "alterações feitas
    # aqui ainda não afetam notícias, mercado, lesões ou escalações". Era
    # verdade até 14/09, quando o glossário passou a mandar em todas elas. O
    # aviso ficou, e o Vini leu aquilo enquanto me perguntava por que uma
    # notícia não obedecia ao glossário. A tela estava mentindo para ele.
    #
    # Guardo a frase NOVA pelo mesmo motivo que guardava a antiga: se alguém
    # trocar o texto do topo, que seja de propósito.
    assert "é ela que manda no app" in tela, \
        "o aviso do topo voltou a dizer que o glossário é uma base paralela"
    assert "Base paralela" not in tela, \
        "voltou o aviso de 'base paralela'; ele é falso desde 14/09"
    assert "abrirBuscaFonte" in tela
    assert "Pesquisar e vincular nesta fonte" in tela
    assert "Cada vínculo é salvo automaticamente" in tela
    assert "desvincularFonte" in tela
    assert "af_bloqueado" in banco and "tm_bloqueado" in banco
    assert "resumo_clube" in main + banco + tela
    assert '"players/profiles"' in main
    assert "colunasComVazio" in tela and "data-ordem=\"api_football\"" in tela
    assert "CAST(g.af_id AS TEXT) = %s" in banco
    assert "g.spl_id = %s" in banco and "g.tm_id = %s" in banco
    assert "ID interno, SPL, API-Football ou Transfermarkt" in tela
    assert "data-ordem=\"tm_ar\"" in tela and "com_tm_arabe" in banco + tela
    assert "capturarNomeTM" in tela
    with open(os.path.join(RAIZ, "elenco_tm.py"), encoding="utf-8") as f:
        tm = f.read()
    assert "def _parse_nome_pais_origem" in tm
    assert "name in home country" in tm
    assert 'soup.find_all(["span", "th", "dt"])' in tm
    assert "def _parse_busca_jogadores" in tm
    assert "def _parse_perfil_para_busca" in tm
    assert "async def buscar_jogadores" in tm
    assert "schnellsuche/ergebnis/schnellsuche" in tm
    assert 'r"\\b(Al|El)\\s+"' in tm
    assert "inclui categorias de base" in main + tela
    assert "'player': int(identificador)" in main
    assert '"id_exato": True' in banco
    assert '"info-table__content--bold" not in classes' in tm
    assert "'informacoes e fatos'" in banco
    for coluna in ("SPL em inglês", "SPL em árabe", "API-Football",
                   "Transfermarkt", "TM em árabe", "PDF", "Notícias árabes"):
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
