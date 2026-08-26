"""
GRAVADOR DE CLIPES — fica ligado na máquina de quem estiver com o PC de pé.

COMO SE USA
    Dois cliques em  instalar.bat  , uma vez só. Depois disso ele sobe junto
    com o Windows e vive no ícone ao lado do relógio:

        cinza    ligado, nenhum jogo gravando
        verde    gravando
        vermelho deu problema — clique para ver o que foi

    Ninguém abre nada antes do jogo. Quem escolhe as partidas é o Vini, pelo
    celular, na guia Clipes.

O QUE ELE FAZ
    1. Olha o canal do parceiro e conta ao app quais transmissões estão no ar.
    2. Grava as que foram escolhidas — até quatro ao mesmo tempo.
    3. Quando alguém aperta GOL AGORA, recorta o trecho e devolve.

POR QUE ELE, E NÃO O SERVIDOR, OLHA O CANAL
    O Railway é IP de datacenter, e o YouTube barra esses com verificação de
    bot. Uma máquina doméstica passa. Então quem descobre as transmissões é
    ele, e o servidor só guarda o que ele contou.

O QUE ELE NÃO FAZ
    Não publica nada. Ele entrega o recorte para o app; quem publica é o Vini,
    apertando Publicar na tela, depois de assistir. A senha desta máquina não
    dá acesso à conta do X.

SOBRE ATUALIZAÇÃO
    Ele se atualiza sozinho: pergunta ao app qual versão deveria estar rodando
    e, se estiver velho, baixa o arquivo novo, confere que compila, guarda o
    antigo ao lado e reinicia. Quem está com a máquina não faz nada.

    E os números que mudam com frequência — qualidade, janela do clipe,
    atraso da transmissão — nem vivem aqui: vêm da guia Configurações do app.
    Por isso este arquivo tende a ficar parado por meses.

SOBRE QUEDAS
    Se uma transmissão cair, ele começa outro arquivo e continua. O trecho
    perdido fica registrado: se pedirem um corte que caia nesse buraco, ele
    avisa em vez de mandar vídeo errado.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PASTA = os.path.dirname(os.path.abspath(__file__))
GRAVACOES = os.path.join(PASTA, "gravacoes")

INTERVALO_CONSULTA = 4          # de quantos em quantos segundos falo com o app

# Quantas transmissões da aba /streams eu leio. Vou subindo enquanto não
# aparecer nenhuma ENCERRADA — sinal de que ainda não passei pela faixa das
# que estão no ar. Um número fixo não serve: no dia 24/08 o canal tinha doze
# jogos agendados, meu teto era doze, e o jogo que estava rolando ficou fora
# do corte. A tela dizia "nada no ar" com toda a convicção.
LIMITES_CANAL = (40, 90, 200)
MARGEM_SEG = 2                  # folga antes de cortar, para o trecho existir
ESPERA_MAX_SEG = 90             # até quando espero o fim da janela ser gravado


# Versão deste arquivo. O app compara com o que ele espera e avisa na tela
# quando estão diferentes.
#
# Isso existe por causa de um caso real: eu corrigi o corte às 13:43, e às
# 16:49 ainda saíam clipes com o defeito antigo. O arquivo estava certo — a
# janela do gravador continuava rodando o código carregado na memória desde
# antes. Editar arquivo não muda processo que já está de pé, e não havia nada
# na tela que denunciasse isso.
VERSAO = "2026-08-26a"


# Os ajustes que o app manda. Ficam aqui os PADRÕES, usados enquanto a
# primeira resposta não chega — e só. Quem manda é a guia de Configurações.
#
# É isto que faz este arquivo parar de precisar de atualização: quase tudo que
# eu mexi nas últimas semanas foi um destes números, e agora eles mudam na tela.
AJUSTES = {
    "gravador_altura_max": 720,
    "gravador_preset": "veryfast",
    "gravador_decodifica_antes": 30,
    "gravador_intervalo_canal": 90,
    "gravador_horas_gravacao": 12,
}

# O que a janela mostrou por último. O programa da bandeja lê daqui, e o
# último erro sobe para o app para você ver do celular.
ESTADO = {"linhas": [], "ultimo_erro": "", "gravando": 0}
LIMITE_LINHAS = 400


def diz(t: str = "", erro: bool = False) -> None:
    print(t, flush=True)
    try:
        with open(os.path.join(PASTA, "gravador_registro.txt"), "a",
                  encoding="utf-8") as f:
            f.write(datetime.now().strftime("%d/%m %H:%M:%S ") + t + "\n")
    except Exception:
        pass
    ESTADO["linhas"].append(t)
    del ESTADO["linhas"][:-LIMITE_LINHAS]
    if erro:
        ESTADO["ultimo_erro"] = t


def achar(nome: str) -> str:
    return shutil.which(nome) or shutil.which(nome + ".exe") or ""


def achar_ytdlp() -> list:
    """O executável some do PATH no Python 3.14; como módulo sempre funciona."""
    direto = achar("yt-dlp")
    if direto:
        return [direto]
    for interp in ("py", "python", "python3"):
        caminho = achar(interp)
        if not caminho:
            continue
        base = [caminho, "-3"] if interp == "py" else [caminho]
        try:
            r = subprocess.run(base + ["-m", "yt_dlp", "--version"],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                return base + ["-m", "yt_dlp"]
        except Exception:
            pass
    return []


def arquivo(nome: str) -> str:
    c = os.path.join(PASTA, nome)
    return open(c, encoding="utf-8").read().strip() if os.path.exists(c) else ""


def conferir_rede(app: str) -> bool:
    """Confere, na subida, que dá para chegar no app. Devolve se resolveu.

    Isto existe por causa de uma tarde inteira perdida: a janela do gravador
    ficou horas repetindo "[Errno 11001] getaddrinfo failed" enquanto a tela
    do app dizia que o canal não estava transmitindo nada. As duas coisas
    eram a mesma coisa — o app só sabe do canal o que este programa conta,
    e este programa não estava conseguindo contar nada — mas nada na tela
    ligava uma à outra, e a mensagem nem dizia qual endereço tinha falhado.

    Não impeço a subida se falhar: rede volta, e o programa tenta de novo
    sozinho. Só quero que a primeira linha da janela diga a verdade.
    """
    host = urllib.parse.urlsplit(app).hostname or ""
    proxies = urllib.request.getproxies()
    if proxies:
        # O Python obedece à configuração de proxy do Windows. Se o proxy não
        # existir mais, a falha aparece como se fosse DNS do app — e você fica
        # olhando para o endereço certo achando que ele está errado.
        diz(f"    proxy  : o Windows manda passar por {proxies}")
    try:
        ips = sorted({i[4][0] for i in socket.getaddrinfo(host, 443)})
        diz(f"    rede   : {host} resolve para {', '.join(ips)}")
        return True
    except Exception as e:
        diz(f"    rede   : NÃO CONSEGUI RESOLVER {host}")
        diz(f"             {type(e).__name__}: {e}")
        diz("             Enquanto isso não voltar, eu não falo com o app, e a")
        diz("             guia Clipes fica sem as transmissões do canal — ela")
        diz("             só mostra o que eu mandar. Confira internet, VPN e o")
        diz("             endereço dentro de app_url.txt.")
        return False


NOME_DA_MAQUINA = (os.environ.get("COMPUTERNAME")
                   or os.environ.get("HOSTNAME") or socket.gethostname() or "?")


def nao_durma(ligar: bool) -> None:
    """Pede ao Windows para não suspender enquanto estamos gravando.

    Sem isto, alguém precisa lembrar de mexer nas configurações de energia da
    máquina — e quando a máquina é de outra pessoa, ninguém lembra. O PC dorme
    no intervalo e a gravação morre sem erro nenhum.

    Só vale enquanto há gravação em curso; assim que acaba, eu solto e o
    computador volta a dormir normalmente. Fora do Windows, não faz nada.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        CONTINUO, SISTEMA = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            (CONTINUO | SISTEMA) if ligar else CONTINUO)
    except Exception:
        pass


def limpar_gravacoes_velhas() -> int:
    """Apaga os .ts antigos. Cada partida ocupa ~1,6 GB.

    Hoje isso não existia, e a pasta chegou a 196 arquivos. Na máquina de
    outra pessoa, encher o disco não é detalhe — é o fim do favor.
    """
    apagados = 0
    try:
        limite = time.time() - float(AJUSTES["gravador_horas_gravacao"]) * 3600
        for nome in os.listdir(GRAVACOES):
            caminho = os.path.join(GRAVACOES, nome)
            if not nome.endswith((".ts", ".mp4")):
                continue
            if os.path.getmtime(caminho) < limite:
                os.remove(caminho)
                apagados += 1
    except Exception:
        pass
    return apagados


class Gravacao:
    """Um arquivo contínuo, com a hora de relógio em que ele começou."""

    def __init__(self, caminho: str, inicio: datetime, processo):
        self.caminho, self.inicio, self.processo = caminho, inicio, processo
        self.fim: datetime | None = None
        self.conferida = False       # já medi a distância entre som e imagem?

    def vivo(self) -> bool:
        return self.processo is not None and self.processo.poll() is None

    def cobre(self, quando: datetime) -> bool:
        if quando < self.inicio:
            return False
        return self.fim is None or quando <= self.fim

    def posicao(self, quando: datetime) -> float:
        return (quando - self.inicio).total_seconds()


class Jogo:
    """Uma transmissão sendo gravada: seus pedaços e seu processo."""

    def __init__(self, live_id: str, url: str, titulo: str = ""):
        self.id, self.url, self.titulo = live_id, url, titulo
        self.pedacos: list[Gravacao] = []

    def gravando(self) -> bool:
        return bool(self.pedacos) and self.pedacos[-1].vivo()

    def desde(self) -> str:
        return self.pedacos[0].inicio.isoformat() if self.pedacos else ""

    def nome(self) -> str:
        return self.titulo or self.id


class Gravador:
    def __init__(self, app: str, token: str, ytdlp: list, ffmpeg: str):
        self.app, self.token = app, token
        self.host = urllib.parse.urlsplit(app).hostname or app
        self.ytdlp, self.ffmpeg = ytdlp, ffmpeg
        self.jogos: dict[str, Jogo] = {}
        self.canal = ""
        self.olhei_o_canal = 0.0
        # Para avisar quando o contato com o app cai e quando ele volta.
        self.falando_com_o_app = True
        self.ja_tentei_atualizar = False
        self.ultima_faxina = 0.0
        # A última lista de transmissões do canal. Guardo porque é dela que
        # sai o nome do jogo para o botão — sem isso, _nomear procurava numa
        # lista que nunca era preenchida e o botão ficava com o id do vídeo.
        self.ultimo_canal: list = []

    # ── conversa com o app ────────────────────────────────────────────────
    def _http(self, caminho: str, dados: bytes | None = None,
              tipo: str = "application/json"):
        """Uma chamada ao app. Devolve (dado, erro); nunca levanta."""
        req = urllib.request.Request(
            self.app + caminho, data=dados,
            headers={"X-Clipe-Token": self.token, "Content-Type": tipo},
            method="POST" if dados is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                corpo = r.read().decode()
            return json.loads(corpo) if corpo else {}, None
        except urllib.error.HTTPError as e:
            detalhe = ""
            try:
                detalhe = e.read().decode()[:200]
            except Exception:
                pass
            return None, f"HTTP {e.code}: {detalhe}"
        except urllib.error.URLError as e:
            # A mensagem crua do Python aqui é
            #   "<urlopen error [Errno 11001] getaddrinfo failed>"
            # e ela não diz QUAL endereço falhou. Rodei horas com a janela
            # repetindo isso e a linha não dava pista nenhuma de onde olhar.
            motivo = getattr(e, "reason", e)
            if isinstance(motivo, socket.gaierror):
                return None, (f"não consegui traduzir o endereço {self.host} "
                              f"para um IP ({motivo}). É DNS: internet caída, "
                              "VPN ligada, ou proxy do Windows apontando para "
                              "um servidor que não existe.")
            return None, f"não cheguei em {self.host}: {motivo}"
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ── olhar o canal ─────────────────────────────────────────────────────
    def _ler_aba_streams(self, quantos: int) -> tuple:
        """As N primeiras da aba /streams. Devolve (entradas, erro)."""
        alvo = self.canal.rstrip("/") + "/streams"
        try:
            r = subprocess.run(
                # O TÍTULO VEM POR ÚLTIMO, de propósito. Antes a ordem era
                # id|título|estado e eu partia a linha em todas as barras — só
                # que os títulos deste canal TÊM barra:
                #     "Náutico x River | AO VIVO E COM IMAGENS"
                # Então o campo 3 virava um pedaço do título, nunca batia com
                # "is_live", e as doze transmissões eram descartadas em
                # silêncio. Com o título no fim e maxsplit=2, ele pode ter
                # quantas barras quiser.
                self.ytdlp + ["--no-warnings", "--flat-playlist",
                              "--playlist-end", str(quantos),
                              "--print", "%(id)s|%(live_status)s|%(title)s",
                              alvo],
                capture_output=True, text=True, timeout=180,
                encoding="utf-8", errors="replace")
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"
        entradas = []
        for linha in (r.stdout or "").splitlines():
            partes = linha.split("|", 2)
            if len(partes) < 3 or not partes[0].strip():
                continue
            entradas.append((partes[0].strip(), partes[1].strip(),
                             partes[2].strip()))
        erro = "" if entradas else (r.stderr or "").strip()[:200]
        return entradas, erro

    def transmissoes_do_canal(self) -> list:
        """O que o canal está transmitindo agora.

        Uso --flat-playlist para não abrir cada vídeo: a aba /streams do canal
        traz o suficiente, e abrir um por um seria lento e chamaria atenção
        do YouTube sem necessidade.

        SOBRE QUANTAS EU LEIO
            A aba vem nesta ordem: primeiro as AGENDADAS, depois a que está no
            ar, depois as encerradas. Eu lia doze e parava. Num dia em que o
            canal tinha doze jogos marcados, as doze primeiras eram todas
            agendadas — e o jogo que estava rolando ficava do lado de fora do
            corte, sem nada indicando que houvesse mais lista adiante.

            Então o critério agora não é um número: é ler até APARECER UMA
            ENCERRADA. Passar por uma encerrada prova que já atravessei a
            faixa das que estão no ar, porque elas vêm antes. Se eu não
            atravessar, aumento e leio de novo.
        """
        if not self.canal:
            return []

        entradas, erro, teto = [], "", 0
        for teto in LIMITES_CANAL:
            entradas, erro = self._ler_aba_streams(teto)
            if erro and not entradas:
                diz(f"    não consegui olhar o canal: {erro}", erro=True)
                return []
            # Cheguei nas encerradas (logo, vi tudo que interessa) ou a lista
            # acabou antes do teto (logo, não há mais nada para ver).
            if any(e[1] == "was_live" for e in entradas) or len(entradas) < teto:
                break
            diz(f"    o canal tem mais de {teto} transmissões e nenhuma "
                "encerrada até aqui; lendo mais para não cortar o jogo que "
                "está no ar")

        itens, descartados = [], {}
        for vid, estado, titulo in entradas:
            # Só o que está no ar agora. Transmissão encerrada vira vídeo
            # comum e não serve para clipar ao vivo.
            if estado != "is_live":
                descartados[estado or "sem estado"] = \
                    descartados.get(estado or "sem estado", 0) + 1
                continue
            itens.append({"id": vid, "titulo": titulo, "estado": estado})

        # Digo em voz alta o que achei. Antes esta função era muda: quando ela
        # devolvia lista vazia, a tela dizia "o canal não está transmitindo
        # nada" e não havia como saber se ela tinha olhado e não visto, ou se
        # tinha falhado. Silêncio que parece resposta é pior que erro.
        total = len(itens) + sum(descartados.values())
        if not total:
            diz(f"    olhei o canal e não veio nada: {erro or 'lista vazia'}")
        elif itens:
            diz(f"    canal: {len(itens)} no ar de {total} — "
                + ", ".join(i["titulo"][:34] for i in itens))
        else:
            resto = ", ".join(f"{n} {e}" for e, n in sorted(descartados.items()))
            diz(f"    canal: nada no ar ({total} na lista: {resto or 'vazia'})")
        return itens

    # ── gravar ────────────────────────────────────────────────────────────
    def _urls_do_fluxo(self, url: str) -> list:
        """Vídeo e áudio vêm separados nesta transmissão; pego os dois."""
        alt = int(AJUSTES["gravador_altura_max"])
        try:
            r = subprocess.run(
                self.ytdlp + ["--no-warnings", "-f",
                              f"bv*[height<={alt}]+ba/b[height<={alt}]/bv*+ba/b",
                              "-g", url],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace")
        except Exception:
            return []
        return [l.strip() for l in (r.stdout or "").splitlines()
                if l.startswith("http")]

    def comecar_pedaco(self, jogo: Jogo) -> bool:
        fluxos = self._urls_do_fluxo(jogo.url)
        if not fluxos:
            diz(f"    [{jogo.nome()[:30]}] não consegui o fluxo. Ainda está no ar?")
            return False
        os.makedirs(GRAVACOES, exist_ok=True)
        agora = datetime.now(timezone.utc)
        caminho = os.path.join(
            GRAVACOES, f"{jogo.id}_{agora.strftime('%Y%m%d_%H%M%S')}.ts")
        # -copyts: NÃO mexa nos tempos que vieram da transmissão.
        #
        # Imagem e som chegam em dois endereços separados, e cada um entra na
        # janela ao vivo no ponto em que estiver quando eu abro. Sem -copyts o
        # ffmpeg zera o relógio de CADA entrada por conta própria — o que
        # parece alinhar, mas na verdade apaga a diferença e cola som de um
        # instante em cima da imagem de outro. O arquivo sai dizendo que está
        # sincronizado, e é por isso que eu não achava o defeito medindo o
        # arquivo: o número que eu media era o número que eu mesmo tinha
        # zerado.
        #
        # Medi num caso montado, com clarão e bipe disparados no mesmo
        # instante: do jeito antigo o bipe caía 1076 ms depois do clarão; com
        # -copyts, 54 ms — um quadro e meio. Os tempos originais vêm do mesmo
        # encoder da emissora, então guardá-los é o que deixa os dois casarem.
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-copyts"]
        for f in fluxos[:2]:
            cmd += ["-i", f]
        cmd += ["-c", "copy"]
        if len(fluxos) > 1:
            # Sem o -map o ffmpeg pegaria só a primeira entrada, que é o vídeo,
            # e o clipe sairia mudo — sem o grito do narrador, que é metade da
            # graça de um clipe de gol.
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        # Desloca as DUAS trilhas pelo mesmo tanto, para o arquivo não começar
        # num tempo enorme. Um deslocamento só, igual para as duas: a distância
        # entre elas — que é o que acabei de preservar — continua de pé.
        cmd += ["-avoid_negative_ts", "make_zero", caminho]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        jogo.pedacos.append(Gravacao(caminho, agora, proc))
        diz(f"    [{jogo.nome()[:30]}] gravando em {os.path.basename(caminho)}")
        return True

    def conferir_sincronia(self) -> None:
        """Uma vez por gravação, mede quanto o som e a imagem estão separados.

        Não corrijo nada aqui — o -copyts na hora de gravar já faz isso. Isto é
        para eu SABER. Passei duas rodadas achando que o descasamento nascia no
        corte, porque o número que eu media vinha de um arquivo cujos tempos eu
        mesmo tinha zerado. Agora o número é do arquivo de verdade, e aparece
        na tela enquanto o jogo corre, não depois.
        """
        for jogo in self.jogos.values():
            for p in jogo.pedacos:
                if p.conferida or not p.vivo():
                    continue
                if (datetime.now(timezone.utc) - p.inicio).total_seconds() < 25:
                    continue
                p.conferida = True
                d = self._inicio_do_video(p.caminho)
                if d is None:
                    diz(f"    [{jogo.nome()[:24]}] não consegui medir a "
                        "distância entre som e imagem nesta gravação")
                elif abs(d) <= 0.12:
                    diz(f"    [{jogo.nome()[:24]}] som e imagem entraram "
                        f"juntos ({d*1000:+.0f} ms)")
                else:
                    diz(f"    [{jogo.nome()[:24]}] a imagem entrou {d:+.2f}s em "
                        "relação ao som. A diferença está guardada no arquivo, "
                        "então o corte já sai casado.")

    def cuidar_das_gravacoes(self) -> None:
        """Se o ffmpeg de algum jogo morreu, fecha o pedaço e começa outro."""
        for jogo in self.jogos.values():
            if jogo.gravando():
                continue
            if jogo.pedacos:
                ultimo = jogo.pedacos[-1]
                if ultimo.fim is None:
                    ultimo.fim = datetime.now(timezone.utc)
                    diz("")
                    diz(f"    !! [{jogo.nome()[:30]}] a gravação caiu. "
                        "Recomeçando em outro arquivo.")
                    diz("    !! o trecho até religar está perdido.")
            self.comecar_pedaco(jogo)

    def parar_jogo(self, jogo: Jogo) -> None:
        for p in jogo.pedacos:
            if p.vivo():
                try:
                    p.processo.terminate()
                    p.processo.wait(timeout=10)
                except Exception:
                    pass
                p.fim = datetime.now(timezone.utc)

    def sincronizar(self, lives: list) -> None:
        """Alinha o que está gravando com o que você escolheu no app."""
        escolhidos = {l.get("id"): l for l in lives if l.get("id")}
        for live_id in list(self.jogos):
            if live_id not in escolhidos:
                jogo = self.jogos.pop(live_id)
                diz("")
                diz(f"    [{jogo.nome()[:30]}] saiu da lista no app. Encerrando.")
                self.parar_jogo(jogo)
        for live_id, l in escolhidos.items():
            if live_id in self.jogos:
                continue
            jogo = Jogo(live_id, l.get("url") or "", l.get("titulo") or "")
            self.jogos[live_id] = jogo
            diz("")
            diz(f"    [{jogo.nome()[:30]}] entrou na lista. Começando a gravar.")
            self.comecar_pedaco(jogo)

    # ── cortar ────────────────────────────────────────────────────────────
    def _comeco(self, caminho: str, fluxo: str) -> float | None:
        """Em que segundo a trilha começa, segundo o próprio arquivo."""
        try:
            r = subprocess.run(
                [self.ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "error",
                 "-select_streams", fluxo, "-show_entries", "stream=start_time",
                 "-of", "csv=p=0", caminho],
                capture_output=True, text=True, timeout=60)
            return float((r.stdout or "").strip().splitlines()[0])
        except Exception:
            return None

    def _inicio_do_video(self, caminho: str) -> float | None:
        """O quanto a imagem começa DEPOIS do som, em segundos.

        Antes eu lia só o início do vídeo e comparava com zero, porque a
        docstring dizia "o áudio começa em 0". Dizia — não media. Os dois
        números precisam sair do arquivo; supor um deles é como conferir uma
        conta olhando só metade dela.
        """
        v, a = self._comeco(caminho, "v:0"), self._comeco(caminho, "a:0")
        if v is None:
            return None
        return v - (a or 0.0)

    def _rodar_ffmpeg(self, entradas: list, saida: str, dur: float):
        """Recodifica no padrão do X. Copiar cru cortaria no keyframe errado."""
        cmd = [self.ffmpeg, "-y", "-loglevel", "error"] + entradas + [
            "-t", f"{dur:.2f}",
            # veryfast em vez do padrão: medi na gravação real e o corte caiu
            # de 34s para 14s, com semelhança de 0,992 contra o padrão — perda
            # que ninguém vê num clipe curto a 5 Mbps. E 20 segundos a menos de
            # espera importa: você está com o jogo rolando.
            "-c:v", "libx264", "-preset", str(AJUSTES["gravador_preset"]),
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-b:v", "5M", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart", saida]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                              encoding="utf-8", errors="replace")

    def _cortar(self, origem: str, inicio: float, dur: float, saida: str):
        """Corta e CONFERE. Devolve None se deu certo, ou o motivo da falha.

        A conferência existe porque não reproduzi a condição exata que atrasou
        o vídeo no primeiro clipe — ela só acontecia enquanto o arquivo ainda
        crescia. Em vez de confiar que a correção cobre um caso que não
        reproduzi, eu meço: se a imagem não começar junto com o som, refaço do
        jeito lento, que decodifica desde o começo e nunca desalinha.
        """
        grosso = max(0.0, inicio - float(AJUSTES["gravador_decodifica_antes"]))
        fino = inicio - grosso
        r = self._rodar_ffmpeg(["-ss", f"{grosso:.2f}", "-i", origem,
                                "-ss", f"{fino:.2f}"], saida, dur)
        if r.returncode != 0 or not os.path.exists(saida):
            return f"ffmpeg falhou: {(r.stderr or '')[:200]}"

        atraso = self._inicio_do_video(saida)
        if atraso is not None and atraso > 0.2:
            diz(f"        a imagem começaria {atraso:.1f}s depois do som; "
                "refazendo do jeito lento")
            r = self._rodar_ffmpeg(["-i", origem, "-ss", f"{inicio:.2f}"],
                                   saida, dur)
            if r.returncode != 0 or not os.path.exists(saida):
                return f"ffmpeg falhou na segunda tentativa: {(r.stderr or '')[:200]}"
            atraso2 = self._inicio_do_video(saida)
            if atraso2 is not None and atraso2 > 0.2:
                return (f"a imagem insiste em começar {atraso2:.1f}s depois do "
                        "som; não mando um clipe que abre em preto")
        return None

    def atender(self, clipe: dict) -> None:
        cid = clipe.get("id")
        # "or 20" transformaria ZERO em 20. Com a fita de corte, zero é um
        # valor legítimo — você pode terminar o clipe exatamente no lance — e
        # depois pode até ser negativo, se o trecho acabar antes dele.
        antes = clipe.get("antes_seg")
        depois = clipe.get("depois_seg")
        antes = 12 if antes is None else int(antes)
        depois = 10 if depois is None else int(depois)
        if antes + depois < 1:
            self._falhou(cid, "essa janela não tem duração")
            return
        live_id = clipe.get("live_id") or ""
        try:
            alvo = datetime.fromisoformat(clipe["alvo_em"])
        except Exception:
            self._falhou(cid, "não entendi o instante do clipe")
            return
        if alvo.tzinfo is None:
            alvo = alvo.replace(tzinfo=timezone.utc)

        jogo = self.jogos.get(live_id)
        if jogo is None:
            # Com vários jogos, cortar do arquivo errado seria pior que falhar:
            # sairia um clipe de outra partida, com cara de certo.
            self._falhou(cid, "não estou gravando esse jogo")
            return

        inicio_janela = alvo - timedelta(seconds=antes)
        fim_janela = alvo + timedelta(seconds=depois)

        pedaco = next((p for p in jogo.pedacos if p.cobre(inicio_janela)), None)
        if pedaco is None:
            self._falhou(cid, "esse instante não está em nenhuma gravação — "
                              "ou é anterior ao início, ou caiu num corte de sinal")
            return
        if not pedaco.cobre(fim_janela):
            self._falhou(cid, "a janela do clipe atravessa uma queda de sinal")
            return

        # O fim da janela pode ainda não ter sido gravado: você aperta o botão
        # no instante do lance, e os segundos seguintes ainda estão chegando.
        espera = 0
        while pedaco.vivo():
            gravado = (datetime.now(timezone.utc) - pedaco.inicio).total_seconds()
            if gravado >= pedaco.posicao(fim_janela) + MARGEM_SEG:
                break
            if espera >= ESPERA_MAX_SEG:
                self._falhou(cid, "esperei e o fim da janela não foi gravado")
                return
            time.sleep(1)
            espera += 1

        inicio = max(0.0, pedaco.posicao(inicio_janela))
        saida = os.path.join(GRAVACOES, f"clipe_{cid}.mp4")
        diz(f"    [{jogo.nome()[:24]}] clipe {cid}: cortando de {inicio:.0f}s "
            f"({antes}s antes até {depois}s depois)")
        erro = self._cortar(pedaco.caminho, inicio, antes + depois, saida)
        if erro:
            self._falhou(cid, erro)
            return
        dados = open(saida, "rb").read()
        if len(dados) < 10000:
            self._falhou(cid, f"o corte saiu com {len(dados)} bytes; "
                              "provavelmente não havia vídeo naquele trecho")
            return

        _, err = self._http(f"/api/clipe/{cid}/entregar", dados, "video/mp4")
        if err:
            diz(f"    clipe {cid}: não consegui entregar — {err}")
        else:
            diz(f"    clipe {cid}: entregue ({len(dados)/1024/1024:.1f} MB). "
                "Já está na sua tela.")

    def _falhou(self, cid, motivo: str) -> None:
        diz(f"    clipe {cid}: {motivo}", erro=True)
        self._http(f"/api/clipe/{cid}/falhou",
                   json.dumps({"erro": motivo}).encode())

    # ── laço principal ────────────────────────────────────────────────────
    def _relatar(self) -> tuple:
        """Uma chamada só: conto o que sei, recebo o que preciso fazer."""
        agora = time.time()
        disponiveis = None
        # O "self.canal and" não é enfeite: o endereço do canal chega na
        # PRIMEIRA resposta do app, então na primeira volta ele ainda é vazio.
        # Sem essa condição, eu carimbava o relógio sem ter olhado nada e
        # ainda mandava lista vazia — ou seja, apagava a lista do app dizendo
        # "não tem nada no ar" antes de ter olhado uma única vez.
        if self.canal and agora - self.olhei_o_canal >= float(AJUSTES["gravador_intervalo_canal"]):
            disponiveis = self.transmissoes_do_canal()
            self.ultimo_canal = disponiveis
            self.olhei_o_canal = agora
        corpo = {
            "versao": VERSAO,
            "nome": NOME_DA_MAQUINA,
            "ultimo_erro": ESTADO["ultimo_erro"],
            "gravando": {j.id: j.desde() for j in self.jogos.values()
                         if j.gravando()},
            "titulos": [{"id": j.id, "titulo": j.titulo}
                        for j in self.jogos.values() if j.titulo],
        }
        if disponiveis is not None:
            corpo["disponiveis"] = disponiveis
        return self._http("/api/clipe/pendentes",
                          json.dumps(corpo, ensure_ascii=False).encode())

    def _nomear(self, lives: list) -> None:
        """Descobre o título de quem entrou sem um, para o botão dizer o jogo."""
        for l in lives:
            jogo = self.jogos.get(l.get("id"))
            if jogo is None or jogo.titulo:
                continue
            achado = next((d for d in self.ultimo_canal
                           if d.get("id") == jogo.id), None)
            if achado and achado.get("titulo"):
                jogo.titulo = achado["titulo"]

    def rodar(self) -> None:
        diz("    Esperando você escolher os jogos na guia Clipes do app.")
        diz("    Deixe esta janela aberta. Ctrl+C para parar.")
        diz("")
        ultimo_aviso = 0.0
        while True:
            d, err = self._relatar()
            if err:
                # Não desisto por causa de uma falha de rede: o jogo continua.
                agora = time.time()
                if agora - ultimo_aviso > 60:
                    diz(f"    sem contato com o app: {err}", erro=True)
                    ultimo_aviso = agora
                self.falando_com_o_app = False
                time.sleep(INTERVALO_CONSULTA)
                continue

            if not self.falando_com_o_app:
                # Sem esta linha, a volta do contato é invisível: a janela
                # simplesmente para de reclamar, e "parou de reclamar" também é
                # o que ela faz quando você não está olhando.
                diz(f"    voltei a falar com o app às "
                    f"{datetime.now().strftime('%H:%M:%S')}.")
                self.falando_com_o_app = True

            # Os ajustes vêm na mesma resposta. Aplico antes de qualquer
            # outra coisa: se você mudou a qualidade na guia de Configurações,
            # a gravação que eu começar agora já vai no valor novo.
            for chave, valor in ((d or {}).get("ajustes") or {}).items():
                if chave in AJUSTES and valor is not None:
                    AJUSTES[chave] = valor
            esperada = (d or {}).get("versao_esperada") or ""
            if esperada and esperada != VERSAO:
                self.atualizar(esperada)

            if not self.canal:
                self.canal = (d or {}).get("canal") or ""
                if self.canal:
                    diz(f"    canal: {self.canal}")

            lives = (d or {}).get("lives") or []
            self.sincronizar(lives)
            self._nomear(lives)
            self.cuidar_das_gravacoes()
            self.conferir_sincronia()
            gravando = sum(1 for j in self.jogos.values() if j.gravando())
            ESTADO["gravando"] = gravando
            nao_durma(gravando > 0)
            if time.time() - self.ultima_faxina > 1800:
                self.ultima_faxina = time.time()
                n = limpar_gravacoes_velhas()
                if n:
                    diz(f"    apaguei {n} gravação(ões) antiga(s) do disco")
            for clipe in (d or {}).get("clipes", []):
                self.atender(clipe)
            time.sleep(INTERVALO_CONSULTA)

    def atualizar(self, esperada: str) -> None:
        """Baixa a versão nova do app, confere e reinicia com ela.

        Três cuidados, e cada um evita um jeito específico de estragar tudo:

        1. Só troco se o arquivo novo COMPILAR. Baixar um arquivo cortado pela
           metade e reiniciar em cima dele deixaria a máquina morta, e ela pode
           estar na casa de outra pessoa.
        2. Guardo o antigo ao lado. Se o novo não subir, o programa que iniciou
           volta para ele.
        3. Só tento uma vez por execução. Se a versão nova também não bate com
           a esperada — porque eu errei o número, por exemplo — isso viraria um
           laço de baixar-e-reiniciar para sempre.
        """
        if self.ja_tentei_atualizar:
            return
        self.ja_tentei_atualizar = True
        diz("")
        diz(f"    versão nova disponível ({VERSAO} -> {esperada}). Baixando.")
        try:
            req = urllib.request.Request(
                self.app + "/api/gravador/codigo",
                headers={"X-Clipe-Token": self.token})
            with urllib.request.urlopen(req, timeout=60) as r:
                codigo = r.read().decode("utf-8")
        except Exception as e:
            diz(f"    não consegui baixar a versão nova: {e}", erro=True)
            return
        if len(codigo) < 5000 or "VERSAO" not in codigo:
            diz("    o que veio não parece o gravador; fico na versão atual",
                erro=True)
            return
        try:
            compile(codigo, "gravador.py", "exec")
        except SyntaxError as e:
            diz(f"    a versão nova não compila ({e}); fico na atual", erro=True)
            return
        try:
            meu = os.path.abspath(__file__)
            with open(meu + ".anterior", "w", encoding="utf-8") as f:
                f.write(open(meu, encoding="utf-8").read())
            with open(meu + ".novo", "w", encoding="utf-8") as f:
                f.write(codigo)
            os.replace(meu + ".novo", meu)
        except Exception as e:
            diz(f"    não consegui trocar o arquivo: {e}", erro=True)
            return
        diz("    atualizado. Reiniciando com a versão nova.")
        self.parar()
        os.execv(sys.executable, [sys.executable, meu] + sys.argv[1:])

    def parar(self) -> None:
        for jogo in self.jogos.values():
            self.parar_jogo(jogo)


# ══════════════════════════════════════════════════════════════════════════
# O ÍCONE NA BANDEJA
#
# Sem janela preta. Isso não é enfeite: o console do Windows PAUSA o programa
# quando alguém clica dentro dele para selecionar texto, e o programa fica
# parado sem erro nenhum, sem aviso nenhum. Numa máquina emprestada, esse é o
# jeito mais provável de a gravação morrer no meio de um jogo.
#
# Se o pystray não estiver instalado, o programa roda igual, só sem ícone.
# Não quero que a falta de um enfeite impeça a gravação.
def _desenhar(cor):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=cor)
    d.polygon([(26, 20), (26, 44), (46, 32)], fill=(255, 255, 255, 235))
    return img


def bandeja(g) -> None:
    """Ícone ao lado do relógio: verde gravando, cinza parado, vermelho com erro."""
    try:
        import pystray
    except Exception:
        return
    VERDE, CINZA, VERMELHO = (34, 197, 94, 255), (120, 130, 140, 255), (239, 68, 68, 255)

    def dizer(_=None):
        n = ESTADO["gravando"]
        if ESTADO["ultimo_erro"] and not n:
            return "Gravador — " + ESTADO["ultimo_erro"][:70]
        return f"Gravador — gravando {n} jogo(s)" if n else "Gravador — parado"

    def abrir_registro(_=None):
        try:
            os.startfile(os.path.join(PASTA, "gravador_registro.txt"))
        except Exception:
            pass

    def abrir_app(_=None):
        try:
            import webbrowser
            webbrowser.open(g.app + "/clipes")
        except Exception:
            pass

    icone = pystray.Icon("gravador", _desenhar(CINZA), "Gravador", pystray.Menu(
        pystray.MenuItem(dizer, None, enabled=False),
        pystray.MenuItem("Abrir a guia Clipes", abrir_app),
        pystray.MenuItem("Ver o que aconteceu", abrir_registro),
        pystray.MenuItem("Sair", lambda: (g.parar(), icone.stop(), os._exit(0))),
    ))

    def pulsar(ic):
        ic.visible = True
        while True:
            cor = (VERDE if ESTADO["gravando"]
                   else VERMELHO if ESTADO["ultimo_erro"] else CINZA)
            try:
                ic.icon = _desenhar(cor)
                ic.title = dizer()
            except Exception:
                pass
            time.sleep(5)

    icone.run(setup=pulsar)


def main() -> int:
    diz("=" * 72)
    diz("GRAVADOR DE CLIPES — " + datetime.now().strftime("%d/%m/%Y %H:%M"))
    diz("=" * 72)
    diz()

    ytdlp, ffmpeg = achar_ytdlp(), achar("ffmpeg")
    if not ytdlp or not ffmpeg:
        diz("    Falta ferramenta:")
        if not ytdlp:
            diz("      yt-dlp :  py -3 -m pip install -U yt-dlp")
        if not ffmpeg:
            diz("      ffmpeg :  winget install Gyan.FFmpeg")
        diz("    (o instalar_ferramentas.bat faz os dois)")
        return 1

    app = arquivo("app_url.txt").rstrip("/")
    token = arquivo("clipe_token.txt")
    if not app:
        diz("    Falta o arquivo app_url.txt com o endereço do seu app.")
        return 1
    if not token:
        diz("    Falta o arquivo clipe_token.txt.")
        diz("    Ele tem que conter o MESMO valor da variável CLIPE_TOKEN")
        diz("    que está configurada no Railway. Sem isso o app recusa os")
        diz("    clipes que eu mandar, e com razão.")
        return 1
    diz(f"    versao : {VERSAO}")
    diz(f"    app    : {app}")
    diz(f"    token  : configurado ({len(token)} caracteres)")
    conferir_rede(app)
    diz()

    g = Gravador(app, token, ytdlp, ffmpeg)

    # Sem console (rodando por pythonw), o laço vai para uma thread e a bandeja
    # fica no fio principal — pystray exige isso no Windows.
    if "--bandeja" in sys.argv or (os.name == "nt" and not sys.stdout.isatty()):
        import threading
        threading.Thread(target=g.rodar, daemon=True).start()
        bandeja(g)
        return 0

    try:
        g.rodar()
    except KeyboardInterrupt:
        diz("")
        diz("    parando…")
    finally:
        g.parar()
        diz("    gravações encerradas. Os arquivos ficam em gravacoes/ —")
        diz("    apague quando não precisar mais, eles são grandes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
