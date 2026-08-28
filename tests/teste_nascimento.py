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

    Então a regra é: data única dos dois lados, casa. Data repetida, a
    NACIONALIDADE precisa desempatar sozinha. Se não desempatar, ninguém casa.
    Continuo preferindo o vazio ao acerto plausível.
"""
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
        self.liga = liga          # (spl_id, nome, nacionalidade, af_id, nascimento)
        self.deles = deles        # (af_id, nome, primeiro, ultimo, nac, nascimento)
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

    # ── 1. o caso simples: data única dos dois lados ───────────────────────
    # O nome está escrito diferente de propósito. É exatamente o que a data
    # resolve e o casamento por nome não resolvia.
    r, gravados = rodar(
        liga=[("spl1", "Ali Al Hussain", "Saudi Arabia", None, "1997-04-30")],
        deles=[(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                "1997-04-30")])
    conferir("casou apesar da grafia diferente", r.get("casados"), 1)
    conferir("e ligou o id certo", gravados, {101: "spl1"})

    # ── 2. dois nascidos no mesmo dia, nacionalidade diferente ─────────────
    r, gravados = rodar(
        liga=[("spl1", "Ali Al Hussain", "Saudi Arabia", None, "1997-04-30"),
              ("spl2", "Marco Silva", "Brazil", None, "1997-04-30")],
        deles=[(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                "1997-04-30"),
               (102, "M. Silva", "Marco", "Silva", "Brazil", "1997-04-30")])
    conferir("a nacionalidade desempatou os dois", r.get("casados"), 2)
    conferir("cada um com o seu", gravados, {101: "spl1", 102: "spl2"})
    conferir("e isso foi contado como desempate",
             r.get("desempatados_pela_nacionalidade"), 2)

    # ── 3. mesmo dia E mesma nacionalidade: ninguém casa ───────────────────
    # É aqui que mora o erro que eu não quero cometer. Dois sauditas nascidos
    # no mesmo dia são indistinguíveis por esta chave. Escolher um seria
    # acertar por sorte metade das vezes — e errar calado a outra metade.
    r, gravados = rodar(
        liga=[("spl1", "Ali Al Hussain", "Saudi Arabia", None, "1997-04-30"),
              ("spl2", "Fahad Al Otaibi", "Saudi Arabia", None, "1997-04-30")],
        deles=[(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                "1997-04-30"),
               (102, "F. Al-Otaibi", "Fahad", "Al Otaibi", "Saudi Arabia",
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
        liga=[("spl1", "Ali Al Hussain", "Saudi Arabia", None, "1997-04-30"),
              ("spl2", "Fahad Al Otaibi", "Saudi Arabia", None, "1997-04-30")],
        deles=[(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                "1997-04-30")])
    conferir("dois meus para um deles não casa ninguém", r.get("casados"), 0)
    conferir("nada gravado no sorteio", gravados, {})

    # ── 4. o nome não escolhe, mas veta ────────────────────────────────────
    # Mesma data, uma pessoa de cada lado — e nenhuma palavra em comum no
    # nome. É muito mais provável que sejam duas pessoas que fazem aniversário
    # no mesmo dia do que a mesma pessoa com o nome inteiro trocado.
    r, gravados = rodar(
        liga=[("spl1", "Ali Al Hussain", "Saudi Arabia", None, "1997-04-30")],
        deles=[(101, "Cristiano Ronaldo", "Cristiano", "Ronaldo", "Portugal",
                "1997-04-30")])
    conferir("nome sem nada em comum é recusado", r.get("casados"), 0)
    conferir("e o motivo é registrado", r.get("recusados_pelo_nome"), 1)
    conferir("nada gravado", gravados, {})

    # ── 5. uma palavra em comum basta ──────────────────────────────────────
    r, _ = rodar(
        liga=[("spl1", "Mohammed Al Dawsari", "Saudi Arabia", None, "1991-08-19")],
        deles=[(101, "S. Al-Dawsari", "Salem", "Al Dawsari", "Saudi Arabia",
                "1991-08-19")])
    conferir("sobrenome em comum passa", r.get("casados"), 1)

    # ── 6. um id da API-Football não serve a duas pessoas ──────────────────
    r, gravados = rodar(
        liga=[("spl2", "Outro Sujeito", "Saudi Arabia", None, "1997-04-30")],
        deles=[(101, "O. Sujeito", "Outro", "Sujeito", "Saudi Arabia",
                "1997-04-30")],
        ligados={101: "spl1"})
    conferir("id já usado por outra pessoa não é reaproveitado",
             r.get("casados"), 0)
    conferir("nada gravado", gravados, {})

    # ── 7. quem já tem id não é mexido ─────────────────────────────────────
    r, gravados = rodar(
        liga=[("spl1", "Ali Al Hussain", "Saudi Arabia", 999, "1997-04-30")],
        deles=[(101, "A. Al-Hussain", "Ali", "Al Hussain", "Saudi Arabia",
                "1997-04-30")])
    conferir("quem já tinha id fica como está", r.get("casados"), 0)
    conferir("contado como já tinha", r.get("ja_tinham"), 1)
    conferir("nada gravado", gravados, {})

    # ── 8. sem data dos dois lados, sem cruzamento ─────────────────────────
    r, gravados = rodar(
        liga=[("spl1", "Ali Al Hussain", "Saudi Arabia", None, "1997-04-30")],
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
                   "CREATE TABLE IF NOT EXISTS af_jogador"):
        ok(pedaco in fonte, f"faltou no banco: {pedaco}")
    conferir("uma tabela af_jogador só",
             fonte.count("CREATE TABLE IF NOT EXISTS af_jogador"), 1)

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ nascimento: casa pela data, e recusa quando a data empata")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
