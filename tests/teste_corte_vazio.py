"""
O gravador não pode cortar um trecho que ainda não existe no arquivo.

O QUE ACONTECEU (08/09/26, Al Ittihad x Al Fayha)
    Vários clipes seguidos do MESMO jogo voltaram com

        "o corte saiu com 261 bytes; provavelmente não havia vídeo
         naquele trecho"

    enquanto a outra partida da mesma tarde ia bem.

    A causa: `Gravacao.posicao()` responde "quantos segundos se passaram no
    RELÓGIO desde que abri o ffmpeg", e o código tratava esse número como se
    fosse "quantos segundos de vídeo existem no arquivo". São a mesma coisa só
    quando o fluxo chega em tempo real e sem falha. Quando a transmissão
    engasga, o relógio anda e o arquivo não — e a diferença ACUMULA, que é por
    que uma vez que aquele jogo começou a atrasar, todos os clipes seguintes
    dele caíram no mesmo buraco.

    O ffmpeg então buscava num segundo inexistente, escrevia um mp4 só com
    cabeçalho e SAÍA COM CÓDIGO 0 — do ponto de vista dele nada deu errado.
    Nada na corrente reclamava até a conferência de tamanho lá no fim, que só
    sabia dizer "provavelmente".

O QUE ESTE ARQUIVO VIGIA
    Que a decisão de cortar (e a espera antes dela) olhe o ARQUIVO, e não o
    relógio. Rodo o atender() de verdade, com um pedaço cuja duração real é
    menor que o tempo de relógio, e exijo que ele recuse ANTES de chamar o
    ffmpeg — dizendo o quanto está atrasado, que é a informação que faltava.
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

import gravador

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _montar(duracao_real, segundos_de_relogio=600):
    """Um gravador com UM jogo, gravando há 10 minutos de relógio.

    `duracao_real` é o que o arquivo tem de verdade — o número que o ffprobe
    devolveria. Passar None é o ffprobe não respondendo.
    """
    g = gravador.Gravador.__new__(gravador.Gravador)
    g.ffmpeg = "ffmpeg"
    g.jogos = {}
    registro = {"falhou": None, "cortou": False, "entregou": False}

    inicio = datetime.now(timezone.utc) - timedelta(seconds=segundos_de_relogio)
    jogo = gravador.Jogo("live1", "http://x", "AL ITTIHAD X AL FAYHA")
    # Um caminho que NÃO existe, de propósito — e montado pela pasta temporária
    # do sistema em vez de "/tmp", que só existe no Linux. Aqui ele nunca é
    # aberto, então funcionaria nos dois; escrevo certo assim mesmo para o
    # hábito não voltar num lugar onde importe.
    import tempfile
    pedaco = gravador.Gravacao(
        os.path.join(tempfile.gettempdir(), "nao_existe.ts"), inicio, None)
    jogo.pedacos.append(pedaco)
    g.jogos["live1"] = jogo

    g._gravado_de_verdade = lambda caminho: duracao_real
    g._falhou = lambda cid, motivo: registro.__setitem__("falhou", motivo)
    g._http = lambda *a, **k: (None, None)

    def _cortar_falso(origem, inicio_, dur, saida):
        # Escreve um arquivo de tamanho plausível: o atender() lê o resultado
        # logo depois, e um corte "bem-sucedido" que não deixa arquivo faria o
        # teste morrer por um motivo que não é o que ele investiga.
        registro["cortou"] = True
        os.makedirs(os.path.dirname(saida), exist_ok=True)
        with open(saida, "wb") as f:
            f.write(b"\0" * 20000)
        registro["saida"] = saida
        return None
    g._cortar = _cortar_falso
    return g, registro


def _pedido(alvo_atras_de_segundos):
    return {"id": 99, "live_id": "live1", "antes_seg": 20, "depois_seg": 20,
            "alvo_em": (datetime.now(timezone.utc)
                        - timedelta(seconds=alvo_atras_de_segundos)).isoformat()}


def testar():
    falhas.clear()

    # ── 1. o arquivo está muito atrás do relógio: recusa ANTES do ffmpeg ─────
    # 10 minutos de relógio, 3 minutos de vídeo. O lance de 60s atrás está, no
    # relógio, no segundo 540 — e o arquivo tem 180.
    g, reg = _montar(duracao_real=180.0)
    g.atender(_pedido(60))
    ok(not reg["cortou"],
       "o gravador chamou o ffmpeg para cortar um trecho que o arquivo não "
       "tem — é exatamente isso que devolve 261 bytes")
    ok(reg["falhou"] is not None, "não recusou o pedido impossível")
    if reg["falhou"]:
        ok("atrás do relógio" in reg["falhou"] or "só tem" in reg["falhou"],
           f"recusou sem dizer que a gravação está atrasada: {reg['falhou']!r}")
        ok("180" in reg["falhou"],
           "a recusa não diz quantos segundos o arquivo tem de verdade — sem "
           f"esse número não dá para entender o que houve: {reg['falhou']!r}")

    # ── 2. o arquivo tem o trecho: corta normalmente ─────────────────────────
    g, reg = _montar(duracao_real=600.0)
    g.atender(_pedido(60))
    ok(reg["cortou"],
       "com o vídeo todo gravado o corte deixou de acontecer — a conferência "
       "nova está recusando pedido bom")
    ok(reg["falhou"] is None,
       f"recusou um pedido que cabia no arquivo: {reg['falhou']!r}")

    # ── 3. sem ffprobe, volta a confiar no relógio ───────────────────────────
    # Máquina sem ffprobe não pode ficar sem clipe nenhum: a conta antiga é
    # pior, mas é melhor que nada.
    g, reg = _montar(duracao_real=None)
    g.atender(_pedido(60))
    ok(reg["cortou"],
       "sem resposta do ffprobe o gravador parou de cortar — a reserva pelo "
       "relógio sumiu, e uma máquina sem ffprobe fica sem clipe nenhum")

    # ── 4. a espera olha o arquivo, e não o relógio ──────────────────────────
    fonte = open(os.path.join(RAIZ, "gravador.py"), encoding="utf-8").read()
    ini = fonte.find("        espera = 0")
    trecho = fonte[ini:ini + 900]
    ok("_gravado_de_verdade" in trecho,
       "a espera do fim da janela voltou a se basear só no relógio — ela dava "
       "por satisfeita com um trecho que não existia")

    # ── 5. a versão subiu ────────────────────────────────────────────────────
    # O gravador roda na máquina do Vini e na do amigo, e se atualiza sozinho
    # comparando a versão com a que o app espera. Mexer no arquivo sem subir a
    # versão é deixar as duas máquinas rodando o defeito para sempre.
    principal = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
    ok(f'VERSAO_GRAVADOR = "{gravador.VERSAO}"' in principal,
       f"o app espera outra versão do gravador — o gravador diz "
       f"{gravador.VERSAO!r} e o main.py não concorda")

    # Limpa o que os cortes de mentira deixaram para trás.
    for nome in ("clipe_99.mp4",):
        alvo = os.path.join(RAIZ, "gravacoes", nome)
        if os.path.exists(alvo):
            os.remove(alvo)

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ corte vazio: o gravador confere o arquivo antes de cortar")
    return len(falhas)


# ═════════════════════════════════════════════════════════════════════════
# O ffprobe QUE NUNCA ERA ENCONTRADO (19/10/26)
# ═════════════════════════════════════════════════════════════════════════
#
# Ele mandou um print com "o corte saiu com 261 bytes" — e SEM o complemento
# que diz quantos segundos o arquivo tinha. O complemento faltava porque a
# medida tinha falhado, e a medida falhava porque o caminho do ffprobe era
# montado com `self.ffmpeg.replace("ffmpeg", "ffprobe")`.
#
# O `replace` troca TODAS as ocorrências, e a instalação normal no Windows tem
# a palavra duas vezes:
#
#     C:\ffmpeg\bin\ffmpeg.exe  ->  C:\ffprobe\bin\ffprobe.exe
#
# Caminho inexistente, FileNotFoundError, `except Exception: return None`. As
# TRÊS conferências que dependem do ffprobe passaram a responder "não sei" em
# silêncio: a duração real, o casamento som/imagem e a guarda que impede o
# corte de buscar num segundo que ainda não existe.
#
# Toda a proteção que este arquivo testa estava desligada no computador dele.
def testar_ffprobe():
    import os as _os
    import gravador as _g

    falhas2 = []

    def ok2(c, m):
        if not c:
            falhas2.append(m)

    for caminho, esperado in (
            # O caso dele: a palavra aparece na PASTA e no arquivo.
            (r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffprobe.exe"),
            (r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
             r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
            # SÓ CAMINHOS DE WINDOWS AQUI. Eu tinha posto dois exemplos com
            # barra de Linux e o teste_roda_no_windows acusou: caminho POSIX
            # escrito à mão num teste que roda na máquina DELE vira erro que
            # não fala em sistema operacional. E eram enfeite — o defeito mora
            # no Windows, que é onde o gravador roda.
            (r"D:\Apps\ffmpeg\ffmpeg.exe", r"D:\Apps\ffmpeg\ffprobe.exe"),
    ):
        corte = max(caminho.rfind("/"), caminho.rfind("\\"))
        vizinho = (caminho[:corte + 1]
                   + caminho[corte + 1:].replace("ffmpeg", "ffprobe", 1))
        ok2(vizinho == esperado,
            f"de {caminho!r} o ffprobe sairia em {vizinho!r} e devia ser "
            f"{esperado!r}. Trocar a palavra no caminho INTEIRO renomeia a "
            f"pasta junto, e o arquivo não existe — foi assim que três "
            f"conferências viraram silêncio")
        ok2(caminho.replace("ffmpeg", "ffprobe") == esperado
            or caminho.count("ffmpeg") > 1,
            f"o caso {caminho!r} não exercita nada: a palavra aparece uma vez "
            f"só, e aí o jeito errado e o certo dão no mesmo")

    # A FUNÇÃO DE VERDADE, com o PATH vazio para ela cair no vizinho.
    import shutil as _sh
    guardado = _sh.which
    try:
        _sh.which = lambda n: None
        ok2(_g.achar_ffprobe("") == "",
            "sem ffmpeg e sem PATH o ffprobe deveria sair vazio")
        ok2(_g.achar_ffprobe(r"C:\ffmpeg\bin\ffmpeg.exe") == "",
            "um vizinho que NÃO existe no disco foi devolvido como se "
            "existisse; aí o erro só aparece na hora de cortar")
        # UM CAMINHO NEUTRO, e não "/usr/bin/...". O `which` está trocado,
        # então o valor é só um crachá — mas escrever caminho de Linux num
        # teste que roda no Windows dele vira FileNotFoundError travando o
        # push, e o teste_roda_no_windows existe para pegar exatamente isso.
        # Pegou.
        import tempfile as _tf0
        do_path = _os.path.join(_tf0.gettempdir(), "ffprobe-de-mentira")
        _sh.which = lambda n: do_path if n == "ffprobe" else None
        ok2(_g.achar_ffprobe(r"C:\qualquer\ffmpeg.exe") == do_path,
            "o ffprobe do PATH deveria ganhar do palpite pelo vizinho")

        # ── A PASTA DE VERDADE, no disco ────────────────────────────────
        #
        # Sem isto a conferência não media nada: eu só testava caminho
        # INEXISTENTE, e aí o jeito certo e o errado devolvem vazio igual.
        # Plantei o `replace` no caminho inteiro e passou verde.
        #
        # Aqui a pasta existe e tem a palavra "ffmpeg" no nome — o layout
        # normal de instalação no Windows, que é onde o gravador roda.
        # ── O CAMINHO DE WINDOWS, interceptando o que ela PROCURA ──────
        #
        # Este teste roda no Linux, onde não dá para criar uma pasta cujo
        # separador é `\`. Então em vez de montar o disco eu escuto a
        # pergunta: para `C:\ffmpeg\bin\ffmpeg.exe`, a função tem de ir
        # conferir `C:\ffmpeg\bin\ffprobe.exe` — e não outro lugar.
        #
        # Sem isto, trocar o `max(rfind("/"), rfind("\\"))` por só a barra do
        # Linux passava verde: o resultado é vazio de qualquer jeito, porque
        # nada existe neste disco.
        # O PATH precisa estar vazio aqui: a linha acima deixou o `which`
        # respondendo com um ffprobe, e aí a função devolve cedo e nunca
        # chega a perguntar pelo vizinho — foi o que fez esta conferência
        # nascer medindo uma lista vazia.
        _sh.which = lambda n: None
        perguntas = []
        guardado_exists = _g.os.path.exists
        try:
            _g.os.path.exists = lambda c: (perguntas.append(c), False)[1]
            _g.achar_ffprobe(r"C:\ffmpeg\bin\ffmpeg.exe")
        finally:
            _g.os.path.exists = guardado_exists
        ok2(perguntas == [r"C:\ffmpeg\bin\ffprobe.exe"],
            f"com um caminho de Windows ela foi procurar em {perguntas} e "
            f"devia procurar em ['C:\\ffmpeg\\bin\\ffprobe.exe']. "
            f"Reconhecer só a barra do Linux faz o nome do arquivo virar o "
            f"caminho inteiro — e o gravador roda no Windows dele")

        import tempfile as _tf
        _sh.which = lambda n: None
        with _tf.TemporaryDirectory() as tmp:
            bin_ = _os.path.join(tmp, "ffmpeg", "bin")
            _os.makedirs(bin_)
            alvo = _os.path.join(bin_, "ffprobe")
            open(_os.path.join(bin_, "ffmpeg"), "w").close()
            open(alvo, "w").close()
            achado = _g.achar_ffprobe(_os.path.join(bin_, "ffmpeg"))
            ok2(achado == alvo,
                f"com o ffprobe AO LADO do ffmpeg, numa pasta chamada "
                f"'ffmpeg', ele devolveu {achado!r} em vez de {alvo!r}. "
                f"Trocar a palavra no caminho inteiro renomeia a pasta junto "
                f"e aponta para um lugar que não existe — era esse o defeito "
                f"na máquina dele")
    finally:
        _sh.which = guardado

    # E A FALTA DELE PRECISA SER DITA. Era o silêncio que fazia o Vini receber
    # uma mensagem pela metade e não ter como saber que faltava uma peça.
    # SEM OS COMENTÁRIOS: a explicação dentro do `achar_ffprobe` CITA o
    # código errado para contar o que mudou, e procurar no texto todo
    # encontrava a minha própria explicação. Quinta vez nesta suíte.
    bruto = open(_os.path.join(RAIZ, "gravador.py"), encoding="utf-8").read()
    fonte = "\n".join(l for l in bruto.split("\n")
                      if not l.strip().startswith("#"))
    ok2("NÃO ACHEI O ffprobe" in bruto,
        "a falta do ffprobe voltou a ser silenciosa. Três conferências "
        "dependem dele, e elas morrem sem avisar")
    # A FORMA DO CÓDIGO, PELA ÁRVORE SINTÁTICA — e não pelo texto.
    #
    # Minha conferência anterior procurava a string no arquivo sem os
    # comentários, e falhava: a explicação dentro do `achar_ffprobe` cita o
    # código errado dentro de uma DOCSTRING, que não começa com `#`. Na
    # árvore, docstring é uma constante e chamada é uma chamada — não há como
    # confundir as duas.
    import ast as _ast
    arvore = _ast.parse(bruto)
    culpadas = []
    for no in _ast.walk(arvore):
        if not isinstance(no, _ast.Call):
            continue
        f2 = no.func
        if (isinstance(f2, _ast.Attribute) and f2.attr == "replace"
                and len(no.args) == 2
                and all(isinstance(a, _ast.Constant) for a in no.args)
                and [a.value for a in no.args] == ["ffmpeg", "ffprobe"]):
            # Dois argumentos = sem limite de trocas. O jeito certo passa um
            # terceiro (`, 1`) e aplica só no nome do arquivo.
            culpadas.append(no.lineno)
    ok2(not culpadas,
        f"voltou o `self.ffmpeg.replace(...)` sem limite de trocas, nas "
        f"linhas {culpadas}. Ele renomeia a PASTA junto com o arquivo, e o "
        f"caminho que sai não existe")

    for f in falhas2:
        print("  ✗", f)
    print("  ✓ o ffprobe é encontrado mesmo com 'ffmpeg' no nome da pasta"
          if not falhas2 else f"\nFALHAS: {len(falhas2)}")
    return len(falhas2)


if __name__ == "__main__":
    sys.exit(1 if (testar() + testar_ffprobe()) else 0)
