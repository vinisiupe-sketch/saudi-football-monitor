"""
O cruzamento pela data de nascimento.

POR QUE TROCAR O NOME PELA DATA
    Nome é grafia. 'Al Hussain', 'Al-Hussain' e 'A. Al Hussain' são a mesma
    pessoa escrita por três redações, e nenhuma das três está errada. Casar
    por nome é adivinhar a intenção de quem digitou.

    Data é fato. 1996-05-04 é 1996-05-04 em árabe, em latim, no Transfermarkt
    e na API-Football. Não tem variante, não tem abreviação, não tem 'Al'.

O QUE A DATA NÃO RESOLVE
    Coincidência. Com ~500 pessoas e 365 dias, ter dois jogadores nascidos no
    mesmo dia não é exceção: é esperado. Se eu casasse "o único da data" sem
    olhar mais nada, o primeiro par de aniversariantes viraria uma troca de
    identidade silenciosa — e o sintoma apareceria meses depois, numa
    estatística que ninguém sabe explicar.

    Então a regra é: data única dos dois lados, casa. Data repetida, o CLUBE
    ou a NACIONALIDADE precisam desempatar sozinhos. Se nenhum desempatar,
    ninguém casa. Continuo preferindo o vazio ao acerto plausível.

    O clube entrou depois, medindo: ele é o único sinal aqui que é fato e não
    grafia. Duas fontes discordam sobre como se escreve 'Hamdallah'; nenhuma
    discorda sobre em que time o sujeito joga.
"""
import ast as _ast_mod
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

# O `database` importa psycopg2 no topo, e o driver não está instalado aqui —
# nem deveria: este teste não fala com banco nenhum. Ponho um talo no lugar
# para conseguir importar o módulo e trocar o `get_conn` por um falso.
if "psycopg2" not in sys.modules:
    talo = types.ModuleType("psycopg2")
    talo.extras = types.ModuleType("psycopg2.extras")
    talo.extras.RealDictCursor = object
    talo.Error = Exception
    sys.modules["psycopg2"] = talo
    sys.modules["psycopg2.extras"] = talo.extras

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def conferir(nome, deu, esperado):
    if deu != esperado:
        falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")


class CursorFalso:
    """Responde às consultas de `cruzar_por_nascimento` e anota os UPDATEs."""

    def __init__(self, liga, deles, ligados):
        self.liga = liga          # (spl, nome, nac, af_id, nascimento, clube)
        self.deles = deles        # (af, nome, pri, ult, nac, nascimento, clube)
        self.ligados = ligados    # af_id -> spl_id já gravados
        self.gravados = {}
        self._resposta = []

    def execute(self, sql, args=None):
        s = " ".join(sql.split())
        if "FROM jogador WHERE nascimento IS NOT NULL" in s:
            self._resposta = list(self.liga)
        elif "FROM af_jogador" in s:
            self._resposta = list(self.deles)
        elif s.startswith("SELECT 1 FROM jogador WHERE af_id"):
            af, spl = args
            dono = self.ligados.get(af) or self.gravados.get(af)
            self._resposta = [(1,)] if (dono and dono != spl) else []
        elif s.startswith("UPDATE jogador SET af_id"):
            af, spl = args
            self.gravados[af] = spl
            self._resposta = []
        else:
            self._resposta = []

    def fetchall(self):
        return self._resposta

    def fetchone(self):
        return self._resposta[0] if self._resposta else None


class ConexaoFalsa:
    def __init__(self, cursor):
        self._c = cursor

    def cursor(self, *a, **k):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def rodar(liga, deles, ligados=None):
    import database
    cur = CursorFalso(liga, deles, ligados or {})
    original = database.get_conn
    database.get_conn = lambda *a, **k: ConexaoFalsa(cur)
    try:
        r = database.cruzar_por_nascimento()
    finally:
        database.get_conn = original
    return r, cur.gravados


def testar():
    falhas.clear()

    # Atalhos: as tuplas vêm do banco na ordem do SELECT, e escrever isso
    # dezoito vezes esconde o que cada caso quer dizer.
    def meu(spl, nome, nac, nasc, clube="", af=None):
        return (spl, nome, nac, af, nasc, clube)

    def seu(af, nome, pri, ult, nac, nasc, clube=""):
        return (af, nome, pri, ult, nac, nasc, clube)

    # ── 1. o caso simples: data única dos dois lados ───────────────────────
    # O nome está escrito diferente de propósito. É exatamente o que a data
    # resolve e o casamento por nome não resolvia.
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30")],
        deles=[seu(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                   "1997-04-30")])
    conferir("casou apesar da grafia diferente", r.get("casados"), 1)
    conferir("e ligou o id certo", gravados, {101: "spl1"})

    # ── 2. dois nascidos no mesmo dia, nacionalidade diferente ─────────────
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30"),
              meu("spl2", "Marco Silva", "Brazil", "1997-04-30")],
        deles=[seu(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                   "1997-04-30"),
               seu(102, "M. Silva", "Marco", "Silva", "Brazil", "1997-04-30")])
    conferir("a nacionalidade desempatou os dois", r.get("casados"), 2)
    conferir("cada um com o seu", gravados, {101: "spl1", 102: "spl2"})
    conferir("e isso foi contado como desempate", r.get("desempatados"), 2)

    # ── 2b. mesma data, mesma nacionalidade, CLUBES diferentes ─────────────
    # O clube é o desempate mais forte que existe aqui, e por um motivo que
    # não é opinião: ele é fato, não grafia. Duas fontes discordam sobre como
    # se escreve 'Hamdallah', mas não sobre em que time o sujeito joga.
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30",
                  "Al Hilal"),
              meu("spl2", "Fahad Al Otaibi", "Saudi Arabia", "1997-04-30",
                  "Al Nassr")],
        deles=[seu(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                   "1997-04-30", "Al Hilal"),
               seu(102, "F. Al-Otaibi", "Fahad", "Al Otaibi", "Saudi Arabia",
                   "1997-04-30", "Al Nassr")])
    conferir("o clube desempatou onde a nacionalidade não desempataria",
             r.get("casados"), 2)
    conferir("e cada um foi para o seu", gravados, {101: "spl1", 102: "spl2"})

    # ── 3. mesmo dia, mesma nacionalidade, sem clube: ninguém casa ─────────
    # É aqui que mora o erro que eu não quero cometer. Dois sauditas nascidos
    # no mesmo dia, sem clube em nenhum dos lados, são indistinguíveis por
    # esta chave. Escolher um seria acertar por sorte metade das vezes — e
    # errar calado a outra metade.
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30"),
              meu("spl2", "Fahad Al Otaibi", "Saudi Arabia", "1997-04-30")],
        deles=[seu(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                   "1997-04-30"),
               seu(102, "F. Al-Otaibi", "Fahad", "Al Otaibi", "Saudi Arabia",
                   "1997-04-30")])
    conferir("empate sem desempate não casa ninguém", r.get("casados"), 0)
    conferir("nada foi gravado", gravados, {})
    ok(r.get("ambiguos", 0) >= 1, "o empate não foi nem contado")

    # ── 3b. dois do MEU lado para um do lado de lá ─────────────────────────
    # Variação do mesmo empate, e a que eu quase deixei passar: a liga tem os
    # dois sauditas nascidos no dia, a API-Football só cadastrou um. Contar
    # apenas quantos candidatos existem do lado DELES daria "um só, é esse" —
    # e o par sairia por sorteio, decidido pela ordem em que o banco devolveu
    # as linhas. Por isso a unicidade é exigida nos dois lados.
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30"),
              meu("spl2", "Fahad Al Otaibi", "Saudi Arabia", "1997-04-30")],
        deles=[seu(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                   "1997-04-30")])
    conferir("dois meus para um deles não casa ninguém", r.get("casados"), 0)
    conferir("nada gravado no sorteio", gravados, {})

    # ── 4. o nome veta quando o clube não sabe ─────────────────────────────
    # Mesma data, uma pessoa de cada lado, sem clube — e nenhuma palavra em
    # comum no nome. É muito mais provável que sejam duas pessoas que fazem
    # aniversário no mesmo dia do que a mesma pessoa com o nome inteiro
    # trocado.
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30")],
        deles=[seu(101, "Cristiano Ronaldo", "Cristiano", "Ronaldo", "Portugal",
                   "1997-04-30")])
    conferir("nome sem nada em comum é recusado", r.get("casados"), 0)
    conferir("e o motivo é registrado", r.get("recusados_pelo_nome"), 1)
    conferir("nada gravado", gravados, {})

    # ── 4b. mas o clube manda mais que o nome ──────────────────────────────
    # Caso real, tirado do diagnóstico: 'Abderrazak Hamdallah' e
    # 'A. Hamed Allah' são a mesma pessoa e não têm UMA palavra em comum
    # depois de normalizados. O veto por nome recusava esse par. O clube
    # concorda — e clube que concorda vale mais que grafia que discorda.
    r, gravados = rodar(
        liga=[meu("spl1", "Abderrazak Hamdallah", "Morocco", "1990-12-17",
                  "Al Ittihad")],
        deles=[seu(101, "A. Hamed Allah", "Abderrazak", "Hamed Allah",
                   "Morocco", "1990-12-17", "Al Ittihad")])
    conferir("clube que concorda passa por cima da grafia", r.get("casados"), 1)
    conferir("e fica registrado que foi o clube",
             r.get("confirmados_pelo_clube"), 1)
    conferir("ligou certo", gravados, {101: "spl1"})

    # ── 4c. e o clube que DISCORDA veta, mesmo com o nome igual ────────────
    # O outro lado da mesma regra. Nome idêntico e data idêntica não superam
    # clubes diferentes: é o caso clássico de dois homônimos, e o diagnóstico
    # mostrou que ele existe de verdade nesta liga.
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Majrashi", "Saudi Arabia", "1999-03-03",
                  "Al Ahli")],
        deles=[seu(101, "Ali Majrashi", "Ali", "Majrashi", "Saudi Arabia",
                   "1999-03-03", "Al Wehda")])
    conferir("clube que discorda veta mesmo com nome igual",
             r.get("casados"), 0)
    conferir("e o motivo é o clube", r.get("recusados_pelo_clube"), 1)
    conferir("nada gravado", gravados, {})

    # ── 5. uma palavra em comum basta, quando não há clube ─────────────────
    r, _ = rodar(
        liga=[meu("spl1", "Mohammed Al Dawsari", "Saudi Arabia", "1991-08-19")],
        deles=[seu(101, "S. Al-Dawsari", "Salem", "Al Dawsari", "Saudi Arabia",
                   "1991-08-19")])
    conferir("sobrenome em comum passa", r.get("casados"), 1)

    # ── 6. um id da API-Football não serve a duas pessoas ──────────────────
    r, gravados = rodar(
        liga=[meu("spl2", "Outro Sujeito", "Saudi Arabia", "1997-04-30")],
        deles=[seu(101, "O. Sujeito", "Outro", "Sujeito", "Saudi Arabia",
                   "1997-04-30")],
        ligados={101: "spl1"})
    conferir("id já usado por outra pessoa não é reaproveitado",
             r.get("casados"), 0)
    conferir("nada gravado", gravados, {})

    # ── 7. quem já tem id não é mexido ─────────────────────────────────────
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30",
                  af=999)],
        deles=[seu(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                   "1997-04-30")])
    conferir("quem já tinha id fica como está", r.get("casados"), 0)
    conferir("contado como já tinha", r.get("ja_tinham"), 1)
    conferir("nada gravado", gravados, {})

    # ── 8. sem data dos dois lados, sem cruzamento ─────────────────────────
    r, gravados = rodar(
        liga=[meu("spl1", "Ali Al Hussain", "Saudi Arabia", "1997-04-30")],
        deles=[])
    conferir("lado de lá vazio não inventa par", r.get("casados"), 0)
    conferir("nada gravado", gravados, {})

    # ── 9. a coluna existe mesmo ───────────────────────────────────────────
    # A função lê jogador.nascimento e af_jogador.nascimento. Se a migração
    # sumir, isto aqui vira um erro de SQL em produção — e a função devolve
    # {"erro": ...} calada, porque ela captura tudo.
    fonte = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    for pedaco in ("ALTER TABLE jogador ADD COLUMN IF NOT EXISTS nascimento",
                   "ALTER TABLE jogador ADD COLUMN IF NOT EXISTS altura",
                   "ALTER TABLE jogador ADD COLUMN IF NOT EXISTS perfil_em",
                   "CREATE TABLE IF NOT EXISTS af_jogador"):
        ok(pedaco in fonte, f"faltou no banco: {pedaco}")
    conferir("uma tabela af_jogador só",
             fonte.count("CREATE TABLE IF NOT EXISTS af_jogador"), 1)

    # ── 9b. nacionalidade em árabe não serve para desempatar ───────────────
    # Foi o defeito que o diagnóstico revelou: a varredura lia o jogo em dois
    # idiomas e gravava a nacionalidade nas duas passadas. A árabe rodava
    # depois e vencia. Aí o desempate comparava 'السعودية' com 'Saudi Arabia',
    # nunca batia, e empates que tinham solução eram recusados como se não
    # tivessem. A limpeza tem que existir, e a leitura não pode reintroduzir.
    ok("def limpar_campos_em_arabe" in fonte,
       "sumiu a limpeza dos campos gravados em árabe")
    liga_fonte = open(os.path.join(RAIZ, "liga_spl.py"), encoding="utf-8").read()
    pessoa = next((n for n in _ast_mod.walk(_ast_mod.parse(liga_fonte))
                   if isinstance(n, _ast_mod.FunctionDef) and n.name == "_pessoa"),
                  None)
    ok(pessoa is not None, "não achei _pessoa no liga_spl")
    if pessoa:
        corpo = "\n".join(liga_fonte.split("\n")[pessoa.lineno - 1:pessoa.end_lineno])
        comum = corpo[corpo.find("base = {"):corpo.find("if arabe:")]
        for campo in ("nacionalidade", "posicao"):
            ok(f'"{campo}"' not in comum,
               f"{campo} voltou para o bloco comum das duas passadas — "
               f"a versão em árabe vai sobrescrever a latina de novo")
    # ── 10. o que a colheita PREENCHE e quem ela PROCURA têm que casar ─────
    # Errei isto duas vezes seguidas, do mesmo jeito: acrescentei um campo ao
    # que a colheita grava (primeiro o clube, depois a foto) e esqueci de
    # acrescentá-lo ao critério de quem ainda vale a pena visitar. Nos dois
    # casos o número simplesmente parava de subir, sem erro nenhum: a coluna
    # existia, a gravação funcionava, e ninguém era visitado para gravá-la.
    #
    # Enquanto as duas listas forem escritas à mão em lugares diferentes, elas
    # vão se separar de novo. Este teste é o que impede a terceira vez.
    import ast as _ast
    import database
    fonte = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    fn = next((n for n in _ast.walk(_ast.parse(fonte))
               if isinstance(n, _ast.FunctionDef) and n.name == "salvar_perfis"), None)
    ok(fn is not None, "não achei salvar_perfis")
    if fn:
        # O texto ORIGINAL da função, não o `ast.unparse`: o unparse devolve a
        # string SQL como literal escapado, e aí `\s` não casa mais com as
        # quebras de linha de dentro dela.
        corpo = "\n".join(fonte.split("\n")[fn.lineno - 1:fn.end_lineno])
        # O WHERE tem que ser procurado DEPOIS do UPDATE: a função também tem
        # um `SELECT 1 ... WHERE spl_id` antes, e recortar até a primeira
        # ocorrência devolvia um pedaço vazio — que passaria como "nenhum
        # campo escrito", exatamente o contrário do que este teste quer ver.
        i = corpo.find("UPDATE jogador")
        trecho = corpo[i:corpo.find("WHERE spl_id", i)]
        import re
        escritos = {m.group(1) for m in
                    re.finditer(r"(?:SET|,)\s*(\w+)\s*=", trecho)}
        # Colunas de controle: não são dado colhido, são carimbo.
        escritos -= {"atualizado_em", "perfil_em"}
        # chave_ar e chave_ar_colada são derivadas de nome_ar, não campos
        # próprios da fonte.
        escritos -= {"chave_ar", "chave_ar_colada"}
        procurados = {c for c, _ in database.CAMPOS_DA_COLHEITA}
        sobrando = escritos - procurados
        ok(not sobrando,
           f"a colheita preenche {sorted(sobrando)}, mas não procura quem está "
           f"sem — o número vai travar sem dar erro")
        faltando = procurados - escritos
        ok(not faltando,
           f"a colheita procura quem está sem {sorted(faltando)}, mas não "
           f"preenche esse campo — visita à toa, para sempre")

    # ── 11. e a colheita precisa ter fim ───────────────────────────────────
    # Nem todo jogador tem altura ou foto na fonte. Sem a marca de visita,
    # esses ficariam candidatos eternos e cada clique reabriria as mesmas
    # dezoito páginas atrás de um dado que não existe.
    alvo = next((n for n in _ast.walk(_ast.parse(fonte))
                 if isinstance(n, _ast.FunctionDef)
                 and n.name == "jogadores_a_completar"), None)
    ok(alvo is not None, "não achei jogadores_a_completar")
    if alvo:
        c = _ast.unparse(alvo)
        ok("perfil_em IS NULL" in c,
           "a busca de candidatos não olha a marca de visita — nunca termina")
        ok("_falta_alguma_coisa()" in c,
           "o critério voltou a ser escrito à mão em vez de sair da lista")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ nascimento: casa pela data, e recusa quando a data empata")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
