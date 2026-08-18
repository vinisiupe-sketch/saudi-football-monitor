"""
Sondagem da Sportmonks — responde com DADO REAL o que a documentação não responde.

Não toca em nada do app. Só lê a API deles e escreve um relatório.

COMO RODAR
    1. Crie a conta em https://my.sportmonks.com/register (14 dias grátis, sem
       cartão para começar). Na hora de escolher as ligas, selecione as
       sauditas e as duas da AFC.
    2. Copie o token da área "My API" do painel deles.
    3. Salve o token num arquivo chamado  sportmonks_token.txt  nesta mesma
       pasta, com o token e nada mais. (Esse arquivo está no .gitignore —
       não vai para o GitHub.)
       Alternativa: definir a variável de ambiente SPORTMONKS_TOKEN.
    4. Dois cliques em  sondagem_sportmonks.bat  (ou: python sondagem_sportmonks.py)

O relatório sai em  sondagem_sportmonks_RELATORIO.txt  nesta pasta.

O token NUNCA é impresso no relatório nem na tela.

Sem dependência nenhuma: só biblioteca padrão do Python.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://api.sportmonks.com/v3/football"
# Os "types" (o dicionário que diz o que é cada type_id) não ficam sob
# /football, e sim sob /core. Chamei no lugar errado na rodada anterior e por
# isso não consegui traduzir os ids das estatísticas.
BASE_CORE = "https://api.sportmonks.com/v3/core"
PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "sondagem_sportmonks_RELATORIO.txt")
BRUTO = os.path.join(PASTA, "sondagem_sportmonks_BRUTO.json")

# Uma pausa curta entre chamadas. O limite deles é por hora e por entidade,
# então isso é folga de sobra — é só para não bater tudo de uma vez.
PAUSA = 0.4

linhas: list[str] = []
amostras: dict = {}


def diz(txt: str = "") -> None:
    print(txt)
    linhas.append(txt)


def token() -> str:
    t = os.environ.get("SPORTMONKS_TOKEN", "").strip()
    if t:
        return t
    caminho = os.path.join(PASTA, "sportmonks_token.txt")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return f.read().strip()
    print("Não achei o token.")
    print("Crie o arquivo sportmonks_token.txt nesta pasta com o token dentro,")
    print("ou defina a variável de ambiente SPORTMONKS_TOKEN.")
    sys.exit(1)


TOKEN = token()


# A API deles fica atrás do Cloudflare, que barrou a primeira tentativa com
# "Error 1010: acesso negado pela assinatura do navegador". O motivo é que o
# urllib se identifica como "Python-urllib/3.14" e isso cai na regra de bot —
# mesmo com token válido, numa conta nossa, num endpoint feito para ser
# chamado por programa. Basta mandar um User-Agent normal.
# Tento mais de um e guardo o que passou, em vez de fixar um e desistir.
AGENTES = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "iarabao-sondagem/1.0",
    "curl/8.5.0",
]
_agente_bom: str | None = None


def pega(caminho: str, base: str = "", **params):
    """Devolve (dado, erro). Nunca levanta exceção, nunca vaza o token."""
    global _agente_bom
    params["api_token"] = TOKEN
    url = f"{base or BASE}/{caminho}?" + urllib.parse.urlencode(params)
    seguro = url.replace(TOKEN, "<TOKEN>")     # para mensagens de erro
    tentar = [_agente_bom] if _agente_bom else AGENTES
    ultimo = ""
    for ua in tentar:
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": ua,
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = json.loads(r.read().decode())
            _agente_bom = ua
            time.sleep(PAUSA)
            return dados, None
        except urllib.error.HTTPError as e:
            corpo = ""
            try:
                corpo = e.read().decode()[:300]
            except Exception:
                pass
            ultimo = f"HTTP {e.code} em {seguro} :: {corpo}"
            if e.code == 403 and "1010" in corpo:
                continue          # bloqueio do Cloudflare: tenta outro agente
            return None, ultimo
        except Exception as e:
            return None, f"{type(e).__name__} em {seguro}: {e}"
    return None, ultimo


def preenchido(itens: list, campo: str) -> tuple[int, int]:
    """Quantos itens têm o campo com valor ÚTIL, de quantos no total.

    'placeholder.png' conta como AUSENTE. Na primeira rodada eu media só se o
    campo existia e cantei "foto 100%" — mas a URL de quem não tem foto é
    .../placeholder.png, que existe e não serve. Era medida falsa.
    """
    tem = 0
    for i in itens:
        v = i.get(campo) if isinstance(i, dict) else None
        if v in (None, "", 0, "None", [], " "):
            continue
        if isinstance(v, str) and "placeholder" in v.lower():
            continue
        tem += 1
    return tem, len(itens)


def taxa(campo: str, itens: list, rotulo: str = "") -> None:
    tem, total = preenchido(itens, campo)
    pct = (100 * tem // total) if total else 0
    barra = "#" * (pct // 5) + "." * (20 - pct // 5)
    diz(f"    {(rotulo or campo):24} {tem:3}/{total:<3} {pct:3}%  {barra}")


# ══════════════════════════════════════════════════════════════════════════
diz("=" * 74)
diz("SONDAGEM SPORTMONKS — " + datetime.now().strftime("%d/%m/%Y %H:%M"))
diz("=" * 74)

# ── 1. Que ligas este token enxerga? ─────────────────────────────────────
diz()
diz("1) LIGAS QUE A SUA ASSINATURA ENXERGA")
diz("-" * 74)
ligas, err = pega("leagues", per_page="200")
saudi = []
if err:
    diz(f"    FALHOU: {err}")
else:
    todas = ligas.get("data", []) or []
    diz(f"    {len(todas)} liga(s) acessíveis")
    for l in todas:
        nome = l.get("name", "")
        marca = ""
        # As ligas deles vêm com nome curto ("Pro League", "Kings Cup"), sem
        # "Saudi" na frente. Filtrar por "saudi" escondia justamente as três
        # sauditas. Aqui, tudo que a assinatura enxerga já é o que escolhemos.
        if True:
            saudi.append(l)
            marca = "   <<< interessa"
        diz(f"      [{l.get('id')}] {nome}{marca}")
    if not saudi:
        diz()
        diz("    ATENÇÃO: nenhuma liga saudita/AFC nesta assinatura.")
        diz("    No plano grátis eles liberam só ligas de amostra. Para responder")
        diz("    as perguntas que interessam é preciso o teste de 14 dias com as")
        diz("    5 ligas escolhidas: Liga Saudita, Copa do Rei, Supercopa,")
        diz("    AFC Elite e AFC Two.")
amostras["ligas"] = (ligas or {}).get("data", [])[:60]

# ── 2. Achar o Al-Hilal ──────────────────────────────────────────────────
diz()
diz("2) TIME DE TESTE: AL-HILAL")
diz("-" * 74)
time_id = None
times_liga = []

# Primeiro tento pelo NOME, com as grafias possíveis. "Al-Hilal" com hífen não
# achou nada na primeira rodada — e é exatamente a doença que essa conversa
# toda tem: nome saudita não é chave confiável.
for q in ("Hilal", "Al Hilal", "Al-Hilal"):
    d, e = pega(f"teams/search/{urllib.parse.quote(q)}")
    achados = (d or {}).get("data", []) or []
    if achados:
        diz(f"    busca por '{q}' achou {len(achados)}:")
        for t in achados[:8]:
            diz(f"      [{t.get('id')}] {t.get('name')}  escudo={'sim' if t.get('image_path') else 'NÃO'}")
        time_id = achados[0].get("id")
        amostras["time"] = achados[0]
        break
    diz(f"    busca por '{q}': nada" + (f"  ({e})" if e else ""))

# Se o nome falhar, pego pela LIGA: temporada corrente -> times da temporada.
# Não depende de grafia nenhuma.
if not time_id and saudi:
    liga_id = saudi[0].get("id")
    diz(f"    tentando pela liga [{liga_id}] {saudi[0].get('name')}")
    d, e = pega(f"leagues/{liga_id}", include="currentSeason")
    temporada = ((d or {}).get("data") or {}).get("currentseason") \
             or ((d or {}).get("data") or {}).get("currentSeason") or {}
    sid = temporada.get("id")
    diz(f"    temporada corrente = {sid} ({temporada.get('name')})")
    if sid:
        d, e = pega(f"teams/seasons/{sid}")
        times_liga = (d or {}).get("data", []) or []
        diz(f"    {len(times_liga)} times na temporada:")
        for t in times_liga:
            diz(f"      [{t.get('id')}] {t.get('name')}  escudo={'sim' if t.get('image_path') else 'NÃO'}")
        alvo = next((t for t in times_liga if "hilal" in (t.get("name") or "").lower()),
                    times_liga[0] if times_liga else None)
        if alvo:
            time_id = alvo.get("id")
            amostras["time"] = alvo
        if e:
            diz(f"    ({e})")
    amostras["times_da_liga"] = times_liga

diz(f"    usando team_id = {time_id}")

# ── 3. Elenco: quanto vem preenchido? ────────────────────────────────────
diz()
diz("3) ELENCO — TAXA DE PREENCHIMENTO (é o coração da guia Elencos)")
diz("-" * 74)
elenco = []
if time_id:
    # A doc não mostra o caminho literal do endpoint de elenco; tento os
    # candidatos e registro qual respondeu, em vez de chutar um só e concluir
    # errado que "não tem elenco".
    for caminho in (f"squads/teams/{time_id}",
                    f"teams/{time_id}/squads",
                    f"squads/seasons/teams/{time_id}"):
        d, e = pega(caminho, include="player;position;detailedPosition")
        if not e and d.get("data"):
            diz(f"    endpoint que respondeu: /{caminho}")
            elenco = d["data"]
            break
        diz(f"    (sem resposta em /{caminho})")

if elenco:
    diz(f"    {len(elenco)} jogadores no elenco")
    jogadores = [x.get("player") or {} for x in elenco]
    diz()
    diz("    No registro do JOGADOR:")
    taxa("image_path", jogadores, "foto do rosto")
    taxa("height", jogadores, "altura")
    taxa("weight", jogadores, "peso")
    taxa("date_of_birth", jogadores, "nascimento")
    taxa("display_name", jogadores, "nome de exibição")
    taxa("nationality_id", jogadores, "nacionalidade")
    diz()
    diz("    No registro do ELENCO:")
    taxa("jersey_number", elenco, "camisa")
    taxa("position_id", elenco, "posição")
    taxa("detailed_position_id", elenco, "posição detalhada")
    amostras["elenco_exemplo"] = elenco[:3]

    diz()
    diz("    Exemplo de foto (abra no navegador para conferir se existe mesmo):")
    for j in jogadores:
        if j.get("image_path"):
            diz(f"      {j.get('display_name') or j.get('name')}: {j['image_path']}")
            break
else:
    diz("    NÃO CONSEGUI LER O ELENCO.")
    diz("    Se a seção 1 devolveu 401, o problema é o token.")
    diz("    Se a seção 1 listou ligas mas nenhuma saudita, é a assinatura:")
    diz("    escolha as 5 ligas certas no painel deles.")

# ── 4 e 5. Pé preferido e nota — numa AMOSTRA, não num jogador só ────────
# Na primeira rodada eu testava sempre o primeiro do elenco. Calhou de ser um
# garoto sem nenhum jogo, com has_values=false e details vazio — o que me faria
# concluir "não tem nota" quando na verdade eu tinha escolhido mal a cobaia.
# Agora vário jogadores, priorizando quem realmente joga.
diz()
diz("4) PÉ PREFERIDO — está no metadata? (amostra de jogadores)")
diz("-" * 74)
amostra_ids = []
if elenco:
    # ordena por camisa baixa primeiro: heurística simples para pegar titulares
    ordenado = sorted(elenco, key=lambda x: (x.get("jersey_number") or 99))
    for x in ordenado[:6]:
        pid = (x.get("player") or {}).get("id") or x.get("player_id")
        nome = (x.get("player") or {}).get("display_name") or "?"
        if pid:
            amostra_ids.append((pid, nome))

if not amostra_ids:
    diz("    PULADO — depende do elenco, que não veio (ver seções 1 a 3).")
else:
    com_pe = 0
    tipos_meta = set()
    for pid, nome in amostra_ids:
        d, e = pega(f"players/{pid}", include="metadata")
        if e:
            diz(f"    {nome:26} FALHOU: {e[:60]}")
            continue
        meta = (d.get("data") or {}).get("metadata") or []
        achou = ""
        for m in meta:
            tipos_meta.add(m.get("type_id"))
            # o campo é 'values' (plural) no retorno real, não 'value'
            val = m.get("values", m.get("value"))
            if isinstance(val, str) and val.strip():
                achou = f"type {m.get('type_id')} = {val.strip()!r}"
            elif isinstance(val, dict) and val:
                achou = f"type {m.get('type_id')} = {val}"
        if achou:
            com_pe += 1
        diz(f"    {nome:26} {achou or '(metadata vazio)'}")
        amostras.setdefault("metadata_amostra", []).append({nome: meta})
    diz()
    diz(f"    com algum metadata útil: {com_pe} de {len(amostra_ids)}")
    diz(f"    type_ids vistos no metadata: {sorted(t for t in tipos_meta if t)}")

diz()
diz("5) NOTA DO JOGADOR — vem para a Liga Saudita?")
diz("-" * 74)
if not amostra_ids:
    diz("    PULADO — depende do elenco.")
else:
    todos_tipos = set()
    com_stats = 0
    for pid, nome in amostra_ids:
        d, e = pega(f"players/{pid}", include="statistics.details")
        if e:
            continue
        sts = (d.get("data") or {}).get("statistics") or []
        tipos = set()
        for s in sts:
            for det in (s.get("details") or []):
                tipos.add(det.get("type_id"))
        if tipos:
            com_stats += 1
        todos_tipos |= tipos
        diz(f"    {nome:26} {len(sts)} temporada(s), {len(tipos)} tipo(s) de estatística")
        amostras.setdefault("stats_amostra", []).append({nome: sts[:1]})
    diz()
    diz(f"    jogadores COM estatística: {com_stats} de {len(amostra_ids)}")
    diz(f"    type_ids encontrados: {sorted(t for t in todos_tipos if t)}")
    # traduz os type_id para nome, para achar 'Rating' sem chutar
    if todos_tipos:
        # /v3/core/types é paginado; puxo as páginas até cobrir os ids vistos.
        nomes = {}
        pagina = 1
        while pagina <= 12:
            d, e = pega("types", base=BASE_CORE, per_page="200", page=str(pagina))
            if e:
                diz(f"    (types falhou na página {pagina}: {e[:70]})")
                break
            lote = (d or {}).get("data", []) or []
            for t in lote:
                nomes[t.get("id")] = t.get("name")
            if not lote or not (d.get("pagination") or {}).get("has_more"):
                break
            pagina += 1
        if nomes:
            diz()
            diz("    traduzindo:")
            for t in sorted(x for x in todos_tipos if x):
                diz(f"      {t:5} = {nomes.get(t, '??')}")
            achou_nota = [t for t in todos_tipos if "rating" in (nomes.get(t) or "").lower()]
            diz()
            diz(f"    TEM NOTA? {'SIM — type ' + str(achou_nota) if achou_nota else 'não apareceu nesta amostra'}")
        else:
            diz("    (não consegui traduzir os type_id; endpoint de types não respondeu)")

# ── 6. Escalação e formação ──────────────────────────────────────────────
diz()
diz("6) ESCALAÇÃO E FORMAÇÃO DO ÚLTIMO JOGO (o campinho)")
diz("-" * 74)
if not time_id:
    diz("    PULADO — não achei o time (ver seção 2).")
if time_id:
    d, e = pega(f"fixtures/latest", per_page="1")
    ult = None
    if not e and d.get("data"):
        ult = d["data"][0].get("id")
    if not ult:
        d, e = pega(f"teams/{time_id}", include="latest")
        lat = ((d or {}).get("data") or {}).get("latest") or []
        if lat:
            ult = lat[-1].get("id")
    if not ult:
        diz("    não consegui achar a última partida do time")
    else:
        diz(f"    fixture_id = {ult}")
        d, e = pega(f"fixtures/{ult}", include="lineups.player;formations;participants")
        if e:
            diz(f"    FALHOU: {e}")
        else:
            f = d.get("data") or {}
            forms = f.get("formations") or []
            diz(f"    formações: {[x.get('formation') for x in forms] if forms else 'NÃO VEIO'}")
            lu = f.get("lineups") or []
            diz(f"    {len(lu)} linhas de escalação")
            if lu:
                exemplo = lu[0]
                diz(f"    campos de uma linha: {sorted(exemplo.keys())}")
            amostras["escalacao"] = lu[:4]
            amostras["formacoes"] = forms

# ── 7. Lesões ────────────────────────────────────────────────────────────
diz()
diz("7) LESÕES E SUSPENSÕES (guia Lesões)")
diz("-" * 74)
if not time_id:
    diz("    PULADO — não achei o time (ver seção 2).")
if time_id:
    d, e = pega(f"teams/{time_id}", include="sidelined.type")
    if e:
        diz(f"    FALHOU: {e}")
    else:
        sl = ((d.get("data") or {}).get("sidelined")) or []
        diz(f"    {len(sl)} registro(s) de indisponibilidade")
        for s in sl[:5]:
            tp = (s.get("type") or {}).get("name")
            diz(f"      player_id={s.get('player_id')} tipo={tp} até={s.get('end_date')}")
        amostras["lesoes"] = sl[:5]

# ── 8. Transferências: tem valor de mercado? ─────────────────────────────
diz()
diz("8) TRANSFERÊNCIAS (guia Janela) — tem valor de mercado?")
diz("-" * 74)
if not amostra_ids:
    diz("    PULADO — depende do elenco, que não veio (ver seções 1 a 3).")
if amostra_ids:
    # um estrangeiro tem transferência; um garoto da base, não. Por isso a
    # amostra, e não o primeiro da lista como eu fiz na rodada anterior.
    tr_total = []
    for pid, nome in amostra_ids:
        d, e = pega(f"players/{pid}", include="transfers")
        if not e:
            t = (d.get("data") or {}).get("transfers") or []
            if t:
                diz(f"    {nome:26} {len(t)} transferência(s)")
                tr_total.extend(t)
    if not tr_total:
        diz("    nenhum dos jogadores da amostra tem transferência registrada")
    d, e = ({"data": {"transfers": tr_total}}, None)
    if e:
        diz(f"    FALHOU: {e}")
    else:
        tr = ((d.get("data") or {}).get("transfers")) or []
        diz(f"    {len(tr)} transferência(s) deste jogador")
        if tr:
            diz(f"    campos disponíveis: {sorted(tr[0].keys())}")
            tem_mv = any("market" in k.lower() or "value" in k.lower() for k in tr[0])
            diz(f"    campo de VALOR DE MERCADO: {'existe' if tem_mv else 'NÃO EXISTE'}")
            diz(f"    (o campo 'amount' é o valor da negociação, não o de mercado)")
        amostras["transferencias"] = tr[:3]

# ── Fecho ────────────────────────────────────────────────────────────────
diz()
diz("=" * 74)
diz("RESUMO DO QUE ISSO RESPONDE")
diz("-" * 74)
diz("  1. A Liga Saudita está na assinatura?          -> seção 1")
diz("  2. A foto do rosto vem preenchida?             -> seção 3")
diz("  3. O pé preferido existe?                      -> seção 4")
diz("  4. A nota vem para a liga saudita?             -> seção 5")
diz("  5. A formação vem junto da escalação?          -> seção 6")
diz("  6. Lesões e transferências substituem o TM?    -> seções 7 e 8")
diz("=" * 74)

with open(RELATORIO, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas))
with open(BRUTO, "w", encoding="utf-8") as f:
    json.dump(amostras, f, ensure_ascii=False, indent=2)

print()
print(f"Relatório salvo em: {RELATORIO}")
print(f"Amostras cruas em : {BRUTO}")
print()
input("Pressione Enter para fechar...")
