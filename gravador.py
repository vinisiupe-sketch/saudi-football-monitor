"""
GRAVADOR — roda na sua máquina durante a partida.

O QUE ELE FAZ
    Grava a transmissão num arquivo, fica perguntando ao app se você apertou
    GOL AGORA, e quando você apertou ele recorta o trecho e devolve o mp4.

    Você não digita minutagem nenhuma. Ele sabe a que horas começou a gravar,
    então converte hora-de-relógio em posição no arquivo sozinho.

COMO RODAR
    1. Dois cliques em  gravador.bat
    2. Cole o link da transmissão quando ele pedir
    3. Deixe a janela aberta até o fim do jogo

    Para parar: feche a janela, ou Ctrl+C.

O QUE PRECISA ESTAR PRONTO
    app_url.txt      — o endereço do seu app no Railway
    clipe_token.txt  — o mesmo valor da variável CLIPE_TOKEN lá no Railway
    yt-dlp e ffmpeg  — o checar_ferramentas.bat confirma

O QUE ELE NÃO FAZ
    Não publica nada. Ele só entrega o recorte para o app; quem publica é você,
    apertando Publicar na tela, depois de assistir.

SOBRE QUEDAS
    Se a transmissão cair no meio, ele começa um arquivo novo e continua. O
    trecho perdido entre um arquivo e outro fica registrado: se você pedir um
    corte que caia bem nesse buraco, ele avisa em vez de mandar vídeo errado.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

PASTA = os.path.dirname(os.path.abspath(__file__))
GRAVACOES = os.path.join(PASTA, "gravacoes")

INTERVALO_CONSULTA = 4          # de quantos em quantos segundos pergunto ao app
MARGEM_SEG = 2                  # folga antes de cortar, para o trecho existir
ESPERA_MAX_SEG = 90             # até quando espero o fim da janela ser gravado


def diz(t: str = "") -> None:
    print(t, flush=True)


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


class Gravacao:
    """Um arquivo contínuo, com a hora de relógio em que ele começou."""

    def __init__(self, caminho: str, inicio: datetime, processo):
        self.caminho, self.inicio, self.processo = caminho, inicio, processo
        self.fim: datetime | None = None

    def vivo(self) -> bool:
        return self.processo is not None and self.processo.poll() is None

    def cobre(self, quando: datetime) -> bool:
        if quando < self.inicio:
            return False
        return self.fim is None or quando <= self.fim

    def posicao(self, quando: datetime) -> float:
        return (quando - self.inicio).total_seconds()


class Gravador:
    def __init__(self, url_live: str, app: str, token: str,
                 ytdlp: list, ffmpeg: str):
        self.url_live, self.app, self.token = url_live, app, token
        self.ytdlp, self.ffmpeg = ytdlp, ffmpeg
        self.pedacos: list[Gravacao] = []

    # ── conversa com o app ────────────────────────────────────────────────
    def _http(self, caminho: str, dados: bytes | None = None,
              tipo: str = "application/json"):
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
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ── gravar ────────────────────────────────────────────────────────────
    def _urls_do_fluxo(self) -> list:
        """Vídeo e áudio vêm separados nesta transmissão; pego os dois."""
        r = subprocess.run(
            self.ytdlp + ["--no-warnings", "-f",
                          "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
                          "-g", self.url_live],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
        return [l.strip() for l in (r.stdout or "").splitlines()
                if l.startswith("http")]

    def comecar_pedaco(self) -> bool:
        fluxos = self._urls_do_fluxo()
        if not fluxos:
            diz("    não consegui a URL do fluxo. A transmissão ainda está no ar?")
            return False
        os.makedirs(GRAVACOES, exist_ok=True)
        agora = datetime.now(timezone.utc)
        caminho = os.path.join(
            GRAVACOES, agora.strftime("gravacao_%Y%m%d_%H%M%S.ts"))
        cmd = [self.ffmpeg, "-y", "-loglevel", "error"]
        for f in fluxos[:2]:
            cmd += ["-i", f]
        cmd += ["-c", "copy"]
        if len(fluxos) > 1:
            # Sem o -map o ffmpeg pegaria só a primeira entrada, que é o vídeo,
            # e o clipe sairia mudo — sem o grito do narrador, que é metade da
            # graça de um clipe de gol.
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd += [caminho]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.pedacos.append(Gravacao(caminho, agora, proc))
        diz(f"    gravando em {os.path.basename(caminho)}")
        return True

    def cuidar_da_gravacao(self) -> None:
        """Se o ffmpeg morreu, fecha o pedaço e começa outro."""
        if self.pedacos and self.pedacos[-1].vivo():
            return
        if self.pedacos:
            ultimo = self.pedacos[-1]
            if ultimo.fim is None:
                ultimo.fim = datetime.now(timezone.utc)
                diz("")
                diz("    !! a gravação caiu. Recomeçando em outro arquivo.")
                diz("    !! o trecho a partir de agora até religar está perdido.")
        self.comecar_pedaco()

    # ── cortar ────────────────────────────────────────────────────────────
    def atender(self, clipe: dict) -> None:
        cid = clipe.get("id")
        antes = int(clipe.get("antes_seg") or 10)
        depois = int(clipe.get("depois_seg") or 5)
        try:
            alvo = datetime.fromisoformat(clipe["alvo_em"])
        except Exception:
            self._falhou(cid, "não entendi o instante do clipe")
            return
        if alvo.tzinfo is None:
            alvo = alvo.replace(tzinfo=timezone.utc)

        inicio_janela = alvo - timedelta(seconds=antes)
        fim_janela = alvo + timedelta(seconds=depois)

        pedaco = next((p for p in self.pedacos if p.cobre(inicio_janela)), None)
        if pedaco is None:
            self._falhou(cid, "esse instante não está em nenhuma gravação — "
                              "ou é anterior ao início, ou caiu num corte de sinal")
            return
        if not pedaco.cobre(fim_janela):
            self._falhou(cid, "a janela do clipe atravessa uma queda de sinal")
            return

        # O fim da janela pode ainda não ter sido gravado: você aperta o botão
        # no instante do gol, e os segundos seguintes ainda estão chegando.
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
        diz(f"    clipe {cid}: cortando de {inicio:.0f}s "
            f"({antes}s antes até {depois}s depois)")
        # Recodifico em vez de copiar: cópia bruta cortaria no keyframe mais
        # próximo, e o clipe começaria fora da hora — às vezes segundos fora.
        cmd = [self.ffmpeg, "-y", "-loglevel", "error",
               "-ss", f"{inicio:.2f}", "-i", pedaco.caminho,
               "-t", str(antes + depois),
               "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
               "-b:v", "5M", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
               "-movflags", "+faststart", saida]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.exists(saida):
            self._falhou(cid, f"ffmpeg falhou: {(r.stderr or '')[:200]}")
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
        diz(f"    clipe {cid}: {motivo}")
        self._http(f"/api/clipe/{cid}/falhou",
                   json.dumps({"erro": motivo}).encode())

    # ── laço principal ────────────────────────────────────────────────────
    def rodar(self) -> None:
        if not self.comecar_pedaco():
            return
        diz("")
        diz("    Pronto. Pode ir para o celular e apertar GOL AGORA quando sair gol.")
        diz("    Deixe esta janela aberta. Ctrl+C para parar.")
        diz("")
        ultimo_aviso = 0.0
        while True:
            self.cuidar_da_gravacao()
            d, err = self._http("/api/clipe/pendentes")
            if err:
                # Não desisto por causa de uma falha de rede: o jogo continua.
                agora = time.time()
                if agora - ultimo_aviso > 60:
                    diz(f"    (sem contato com o app: {err})")
                    ultimo_aviso = agora
            else:
                for clipe in (d or {}).get("clipes", []):
                    self.atender(clipe)
            time.sleep(INTERVALO_CONSULTA)

    def parar(self) -> None:
        for p in self.pedacos:
            if p.vivo():
                try:
                    p.processo.terminate()
                    p.processo.wait(timeout=10)
                except Exception:
                    pass


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
    diz(f"    app    : {app}")
    diz(f"    token  : configurado ({len(token)} caracteres)")

    url = arquivo("live_url.txt")
    if url:
        diz(f"    link   : li de live_url.txt")
        diz("             (para usar outro, apague o arquivo ou edite ele)")
    else:
        url = input("\n    Cole o link da transmissão e dê Enter:\n    > ").strip()
    if not url:
        diz("    sem link, não há o que gravar.")
        return 1
    diz()

    g = Gravador(url, app, token, ytdlp, ffmpeg)
    try:
        g.rodar()
    except KeyboardInterrupt:
        diz("")
        diz("    parando…")
    finally:
        g.parar()
        diz("    gravação encerrada. Os arquivos ficam em gravacoes/ —")
        diz("    apague quando não precisar mais, eles são grandes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
