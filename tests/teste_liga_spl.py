"""
liga_spl.temporada() — achar a temporada em curso quando a API não diz mais
quando ela começa e termina.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR
    Você reportou, com o gravador rodando e vendo "1 no ar" no canal, que a
    guia Clipes dizia "o canal não está transmitindo nada agora". As duas
    coisas eram verdade ao mesmo tempo porque a página filtra as
    transmissões disponíveis pelas que são "da liga" (`da_liga`), e essa
    marca vem de casar o título da transmissão contra os jogos de hoje —
    jogos que vêm de `liga_spl.temporada()` primeiro.

    Fui direto na API real (api-sdp.spl.com.sa) em 01/09/2026 conferir, e a
    temporada em curso ("2026/2027") veio com `startDateUtc` e `endDateUtc`
    NULOS. `temporada()` só aceitava um casamento quando as duas datas
    existiam e o dia caía entre elas — com as duas nulas, o "if ini and fim"
    nunca era verdadeiro, a função devolvia "", `jogos_da_temporada` nunca
    rodava, `_jogos_de_hoje_da_liga()` ficava vazia, TODA transmissão do dia
    saía com `da_liga: False`, e o filtro padrão (esconder o que não é da
    liga) escondia o Al Hilal x Al Ahli que estava ao vivo.

    A correção: quando a API não dá as duas datas, uso o NOME da temporada
    ("2026/2027" cobre 01/ago/2026 a 31/jul/2027, que é como a Roshn Saudi
    League sempre organizou o calendário) — só como segunda tentativa,
    depois de tentar com data de verdade, que continua valendo mais quando
    existe.

Os dados abaixo (ids, nomes, o par de datas nulas) são uma cópia do que a
API respondeu de verdade nessa consulta — não inventei a forma do bug.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import liga_spl  # noqa: E402

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


# Cópia fiel do que a API devolveu para as competições/temporadas em
# 01/09/2026 — as duas temporadas mais recentes SEM data, e uma antiga COM
# data, para conferir que dado de verdade continua sendo preferido a chute.
_COMPETICAO = "spl::Football_Competition::47d9987fd5044e0dba6c6c1df7d6cfa8"
_TEMPORADA_ATUAL = "spl::Football_Season::3677a75aaa514e43b2840e7fa367c91d"
_TEMPORADA_ANTERIOR = "spl::Football_Season::0de9cda0d297418699a8357a8825d46c"
_TEMPORADA_COM_DATA = "spl::Football_Season::0865193328eb4736b571cd3af4f70ce5"

_COMPS = {"competitions": [{"competitionId": _COMPETICAO}]}
_SEASONS = {"seasons": [
    {"seasonId": _TEMPORADA_ATUAL, "startDateUtc": None, "endDateUtc": None,
     "seasonName": "2026/2027"},
    {"seasonId": _TEMPORADA_ANTERIOR, "startDateUtc": None, "endDateUtc": None,
     "seasonName": "2025/2026"},
    {"seasonId": _TEMPORADA_COM_DATA, "startDateUtc": "2019-08-22T00:00:00Z",
     "endDateUtc": "2020-09-09T00:00:00Z", "seasonName": "2019/2020"},
]}


class _Resposta:
    def __init__(self, dado):
        self._dado = dado

    def json(self):
        return self._dado

    def raise_for_status(self):
        pass


class _ClienteFalso:
    """Fica no lugar do httpx.Client — nunca sai para a rede."""

    def get(self, url, **_kw):
        if "/seasons?" in url:
            return _Resposta(_SEASONS)
        return _Resposta(_COMPS)


def testar():
    falhas.clear()
    cli = _ClienteFalso()

    # ── 1. o caso real: temporada em curso, datas nulas ─────────────────
    liga_spl._CACHE.clear()
    achado = liga_spl.temporada("2026-09-01", cli)
    ok(achado == _TEMPORADA_ATUAL,
       f"01/09/2026 (o dia que você reportou) deveria cair em 2026/2027, "
       f"veio {achado!r} — é este casamento que faltou e escondeu o Al "
       "Hilal x Al Ahli da guia Clipes")
    print("  temporada em curso sem data (o bug real): resolve por 2026/2027")

    # ── 2. fronteira agosto/julho, só com o nome ────────────────────────
    liga_spl._CACHE.clear()
    ok(liga_spl.temporada("2026-07-31", cli) == _TEMPORADA_ANTERIOR,
       "31/07/2026 deveria cair na temporada anterior (2025/2026)")
    liga_spl._CACHE.clear()
    ok(liga_spl.temporada("2026-08-01", cli) == _TEMPORADA_ATUAL,
       "01/08/2026 já deveria cair na temporada nova (2026/2027)")
    print("  fronteira ago/jul: 31/07 fica na temporada velha, 01/08 na nova")

    # ── 3. dado de verdade continua valendo mais que o nome ─────────────
    # 2019/2020 tem data REAL (esticada até setembro por causa da pandemia) —
    # se o casamento por nome rodasse primeiro, essa temporada pareceria
    # terminar em julho de 2020, e o teste abaixo pegaria a diferença.
    liga_spl._CACHE.clear()
    ok(liga_spl.temporada("2020-08-15", cli) == _TEMPORADA_COM_DATA,
       "15/08/2020 tem que casar pela DATA real da 2019/2020 (esticada até "
       "09/09/2020), não pelo nome, que sugeriria que ela já tinha acabado")
    print("  temporada com data real: data de verdade vence o chute pelo nome")

    # ── 4. fora de qualquer temporada conhecida ─────────────────────────
    liga_spl._CACHE.clear()
    ok(liga_spl.temporada("2010-01-01", cli) == "",
       "dia fora de qualquer temporada listada tem que devolver vazio, "
       "não a primeira da lista")
    print("  dia sem temporada nenhuma: devolve vazio, não chuta a mais recente")

    # ── 5. temporada com data real não pode ser recasada pelo NOME ──────
    # 2019/2020 tem data real começando em 22/08/2019. 10/08/2019 é ANTES
    # disso, mas cai dentro da janela ago-jul que o chute pelo nome usaria
    # para essa mesma temporada. Se o código voltar a checar pelo nome as
    # temporadas que JÁ tinham data real (perdendo o "continue" que pula
    # quem já foi julgada com dado de verdade), esse dia casaria por engano
    # com 2019/2020 — a data real, que diz que a temporada ainda não tinha
    # começado, seria ignorada em favor de um chute mais fraco sobre a
    # MESMA temporada.
    liga_spl._CACHE.clear()
    ok(liga_spl.temporada("2019-08-10", cli) == "",
       "10/08/2019 é antes do início real da 2019/2020 (22/08) — não pode "
       "casar por nome com uma temporada que já tem data real dizendo outra "
       "coisa; tem que devolver vazio")
    print("  temporada com data real: o nome não pode recasá-la fora da data de verdade")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ liga_spl.temporada: resolve mesmo com a API sem começo/fim")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
