"""Serviço separado: Media Hub autenticado -> PDF inglês -> app existente.

Não importa main nem inicia os outros coletores. Credenciais são fornecidas
pelas variáveis do serviço no Railway; nunca são copiadas do navegador pessoal.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import signal
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

HUB = "https://mediahub.spl.media"
ARABIA = timezone(timedelta(hours=3))
MAX_PDF = 15 * 1024 * 1024


class MonitorError(Exception):
    """Somente mensagens seguras para exibir no app e nos logs."""


def agora():
    return datetime.now(timezone.utc)


def instante(texto):
    valor = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if valor.tzinfo is None:
        raise ValueError("horário sem fuso")
    return valor


def na_janela(inicio, momento, antecedencia=100):
    return inicio - timedelta(minutes=antecedencia) <= momento <= inicio


def busca_url(dia, pagina=1):
    # Formato produzido pelo filtro de data do próprio portal, conferido na UI.
    d = dia.strftime("%Y%m%d")
    filtros = f'Content_Type,"Match Day Support",Competition,"SPL",Match_Date,"{d}|{d}"'
    return HUB + "/search/results#/?" + urlencode({
        "query": "*", "page": pagina, "type": "grid", "sort": "Match_Date desc",
        "filterBy": filtros, "spellCheck": "true"})


def url_registro(url):
    p = urlparse(url)
    if (p.scheme != "https" or p.netloc != "mediahub.spl.media"
            or not re.fullmatch(r"/record/\d+(?:/media_id/\d+)?", p.path)):
        raise MonitorError("Endereço de documento inválido.")
    return HUB + p.path


def validar_pdf(caminho, dia=None):
    import matchsheet
    if caminho.stat().st_size > MAX_PDF:
        raise MonitorError("PDF excede o limite de 15 MB.")
    with caminho.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise MonitorError("O download não é um PDF.")
    dados = matchsheet.extrair(str(caminho))
    # O parser reconhece o template inglês; não publicar extração parcial.
    for lado in ("casa", "fora"):
        t = dados[lado]
        jogadores = t["titulares"]
        if (not t["time"] or len(jogadores) != 11
                or len({j["numero"] for j in jogadores}) != 11):
            raise MonitorError("PDF precisa de revisão: time ou 11 titulares não identificados.")
    try:
        inicio = datetime.strptime(dados["data"] + " " + dados["hora"],
                                   "%d %B %Y %H:%M").replace(tzinfo=ARABIA)
    except ValueError as exc:
        raise MonitorError("Data ou horário do PDF não reconhecidos.") from exc
    if dia and inicio.date() != dia:
        raise MonitorError("A data do PDF difere da data consultada.")
    return dados, inicio


class Estado:
    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.pasta / "monitor.json"
        self.dados = {"registros": {}}
        if self.arquivo.exists():
            # Não silenciar corrupção, que poderia provocar reenvios.
            self.dados = json.loads(self.arquivo.read_text(encoding="utf-8"))

    def salvar(self):
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.dados, ensure_ascii=False), encoding="utf-8")
        temporario.replace(self.arquivo)

    def entregue(self, registro, digest):
        return self.dados["registros"].get(registro, {}).get("sha256") == digest

    def confirmar(self, registro, digest, inicio):
        self.dados["registros"][registro] = {
            "sha256": digest, "inicio": inicio.isoformat(), "checado": time.time()}
        self.salvar()


async def entregar(cli, app_url, token, caminho):
    resposta = await cli.post(app_url + "/api/escalacao-pdf",
        headers={"X-Escalacao-Token": token},
        files={"arquivo": ("team-sheet.pdf", caminho.read_bytes(), "application/pdf")})
    if resposta.status_code in (401, 403):
        raise MonitorError("O app recusou o token do monitor. Confira ESCALACAO_TOKEN nos dois serviços.")
    if resposta.status_code != 200:
        raise MonitorError(f"O app não confirmou o PDF (HTTP {resposta.status_code}); tentarei novamente.")
    try:
        dados = resposta.json()
    except ValueError as exc:
        raise MonitorError("O app devolveu uma página em vez da confirmação do PDF.") from exc
    if dados.get("salvo") is not True:
        raise MonitorError("O app não confirmou a gravação. Publique também a atualização do app.")
    return dados


class Monitor:
    def __init__(self):
        self.app = os.environ.get("APP_URL", "").rstrip("/")
        p = urlparse(self.app)
        if p.scheme != "https" or not p.netloc or p.username or p.password or p.query or p.fragment:
            raise MonitorError("Configure APP_URL com o endereço HTTPS do seu app.")
        self.token = os.environ.get("ESCALACAO_TOKEN", "")
        if not self.token:
            raise MonitorError("Configure ESCALACAO_TOKEN no serviço do monitor.")
        self.estado = Estado(os.environ.get("MEDIAHUB_DATA_DIR", "/data"))
        self.intervalo = max(60, int(os.environ.get("MEDIAHUB_INTERVAL_SECONDS", "60")))
        self.revisao = max(60, int(os.environ.get("MEDIAHUB_REVISION_SECONDS", "300")))
        self.antecedencia = int(os.environ.get("MEDIAHUB_BEFORE_MINUTES", "100"))
        self.browser = self.context = self.page = None
        self.login_depois = 0

    async def status(self, cli, estado, mensagem, **extra):
        dados = {"estado": estado, "mensagem": mensagem, **extra}
        self.estado.dados["status"] = {**dados, "visto_em": agora().isoformat()}
        self.estado.salvar()
        print(json.dumps(dados, ensure_ascii=False), flush=True)
        try:
            r = await cli.post(self.app + "/api/escalacao-pdf/monitor",
                              headers={"X-Escalacao-Token": self.token}, json=dados)
            if r.status_code != 200:
                print(f"Status não publicado: HTTP {r.status_code}", flush=True)
        except Exception:
            print("Não foi possível atualizar o status no app.", flush=True)

    async def abrir(self, pw):
        if self.browser is None:
            self.browser = await pw.chromium.launch(headless=os.environ.get("MEDIAHUB_HEADLESS") == "1")
            sessao = self.estado.pasta / "sessao.json"
            self.context = await self.browser.new_context(
                storage_state=str(sessao) if sessao.exists() else None,
                accept_downloads=True, locale="en-GB")
            self.page = await self.context.new_page()
            self.page.set_default_timeout(30000)
            self.login_verificado = False

    async def navegar(self, url):
        # Navegar só pelo fragmento mantém a busca Angular anterior por alguns
        # instantes. Um documento novo evita confundir resultados antigos.
        await self.page.goto("about:blank")
        # Iniciar pelo formulário oficial, antes de solicitar conteúdo protegido.
        destino = url if self.login_verificado else HUB + "/site/login"
        resposta = await self.page.goto(destino, wait_until="domcontentloaded")
        if resposta is not None and resposta.status >= 400:
            raise MonitorError(f"Media Hub recusou a página: HTTP {resposta.status} em {urlparse(self.page.url).path}.")
        if "/site/login" not in self.page.url:
            if not self.login_verificado:
                self.login_verificado = True
                await self.navegar(url)
            return
        if time.time() < self.login_depois:
            raise MonitorError("Login do Media Hub pendente. Nova tentativa em até 15 minutos.")
        email = os.environ.get("MEDIAHUB_EMAIL", "")
        senha = os.environ.get("MEDIAHUB_PASSWORD", "")
        if not email or not senha:
            raise MonitorError("Configure o e-mail e a senha do Media Hub nas variáveis do monitor.")
        self.login_depois = time.time() + 900
        # Campos conferidos no formulário real. Não registrar valores nem traces.
        await self.page.get_by_label("Email address", exact=True).fill(email)
        await self.page.get_by_label("Password", exact=True).fill(senha)
        await self.page.get_by_role("button", name="Log in", exact=True).click()
        try:
            await self.page.wait_for_url(lambda u: "/site/login" not in str(u), timeout=20000)
        except Exception as exc:
            raise MonitorError("Media Hub não concluiu o login. Confira as credenciais; se houver código ou CAPTCHA, será necessária intervenção.") from exc
        self.login_depois = 0
        self.login_verificado = True
        await self.context.storage_state(path=str(self.estado.pasta / "sessao.json"))
        print("Login do Media Hub concluído; abrindo registro.", flush=True)
        resposta = await self.page.goto(url, wait_until="domcontentloaded")
        if resposta is not None and resposta.status >= 400:
            raise MonitorError(f"Media Hub recusou conteúdo após login: HTTP {resposta.status}.")
        if "/site/login" in self.page.url:
            raise MonitorError("A sessão do Media Hub não permaneceu autenticada.")

    async def titulos(self, url):
        await self.navegar(url)
        # A busca é Angular: aguardar os resultados, não apenas o HTML inicial.
        await self.page.get_by_role("heading", name=re.compile(r"^\d+ results?$")).wait_for()
        return await self.page.locator("#searchResults a.gridView-title").all_text_contents()

    async def baixar(self, registro, caminho):
        await self.navegar(url_registro(registro))
        english = self.page.get_by_role("link", name=re.compile(r"Team Sheet.*\bENG\b.*\(document\)", re.I))
        try:
            await self.page.get_by_role("button", name="Record options", exact=True).wait_for()
        except Exception as exc:
            # Apenas título e caminho público; nunca campos, cookies ou query.
            caminho_atual = urlparse(self.page.url).path
            titulo = (await self.page.title())[:120]
            raise MonitorError(f"Página do PDF indisponível: {caminho_atual} ({titulo}).") from exc
        if await english.count() == 0:
            # O portal cria o registro do jogo antes de anexar as escalações.
            return False
        if await english.count() != 1:
            raise MonitorError("Mais de uma versão inglesa no registro; precisa de revisão.")
        href = await english.get_attribute("href")
        await self.navegar(url_registro(HUB + href if href.startswith("/") else href))
        # O menu de download da página serve somente a mídia selecionada.
        await self.page.get_by_role("button", name="Record options", exact=True).click()
        await self.page.get_by_text("Download", exact=True).filter(visible=True).first.click()
        await self.page.locator("#sendDownloadSubmit").wait_for()
        async with self.page.expect_download(timeout=60000) as pedido:
            await self.page.locator("#sendDownloadSubmit").click()
        download = await pedido.value
        await download.save_as(str(caminho))
        return True

    async def processar(self, cli, registro, dia, dry_run=False, ignorar_janela=False):
        registro = url_registro(registro)
        anterior = self.estado.dados["registros"].get(registro, {})
        if not ignorar_janela and anterior:
            if not na_janela(instante(anterior["inicio"]), agora(), self.antecedencia):
                return
            if time.time() - anterior["checado"] < self.revisao:
                return
        with tempfile.TemporaryDirectory(dir=self.estado.pasta) as tmp:
            pdf = Path(tmp) / "team-sheet.pdf"
            if not await self.baixar(registro, pdf):
                if ignorar_janela:
                    raise MonitorError("O registro ainda não tem PDF em inglês.")
                return
            dados, inicio = validar_pdf(pdf, dia)
            if not ignorar_janela and not na_janela(inicio, agora(), self.antecedencia):
                return
            digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
            if self.estado.entregue(registro, digest):
                self.estado.confirmar(registro, digest, inicio)
                return
            if dry_run:
                print(json.dumps({"teste": "PDF validado; nenhum envio", "casa": dados["casa"]["time"],
                                  "fora": dados["fora"]["time"], "titulares_por_time": 11}, ensure_ascii=False))
                return
            await entregar(cli, self.app, self.token, pdf)
            # Só confirmar depois de o app garantir gravação no PostgreSQL.
            self.estado.confirmar(registro, digest, inicio)
            await self.status(cli, "publicado", "Escalação atualizada no app.", registro=registro)

    async def ciclo(self, cli, pw):
        r = await cli.get(self.app + "/api/diag/jogos-de-hoje")
        if r.status_code != 200:
            raise MonitorError("Não consegui consultar os jogos de hoje no app.")
        agenda = r.json()
        if agenda.get("erro") or agenda.get("aviso") or not isinstance(agenda.get("jogos"), list):
            raise MonitorError("Calendário indisponível; a busca será tentada novamente.")
        dia = agora().astimezone(ARABIA).date()
        if agenda.get("data_arabia") != dia.isoformat():
            raise MonitorError("O calendário devolveu uma data desatualizada.")
        ativos = [j for j in agenda["jogos"] if na_janela(instante(j["pontape_utc"]), agora(), self.antecedencia)]
        if not ativos:
            await self.status(cli, "aguardando", "Aguardando a janela de 100 minutos antes dos jogos.")
            if self.browser:
                await self.browser.close()
                self.browser = self.context = self.page = None
            return
        await self.abrir(pw)
        await self.status(cli, "buscando", "Consultando os PDFs de hoje no Media Hub.")
        erros = []
        # Filtro de um único dia: normalmente <= 9 partidas. Paginação explícita
        # evita perder documentos quando há registros adicionais de suporte.
        vistos = 0
        for numero in range(1, 11):
            url = busca_url(dia, numero)
            titulos = await self.titulos(url)
            total_texto = await self.page.get_by_role("heading", name=re.compile(r"^\d+ results?$")).inner_text()
            total = int(total_texto.split()[0])
            print(json.dumps({"pagina_busca": numero, "total_portal": total,
                              "titulos_lidos": len(titulos),
                              "team_sheets": [t for t in titulos if re.search(r"Team Sheets?", t, re.I)]},
                             ensure_ascii=False), flush=True)
            if not titulos:
                break
            vistos += len(titulos)
            for titulo in titulos:
                if not re.search(r"Team Sheets?", titulo, re.I):
                    continue
                try:
                    await self.titulos(url)
                    await self.page.locator("#searchResults a.gridView-title").filter(has_text=titulo).first.click()
                    await self.page.wait_for_url(re.compile(r"/record/\d+"))
                    await self.processar(cli, self.page.url, dia)
                except MonitorError as exc:
                    erros.append(str(exc))
                except Exception:
                    erros.append("Falha ao abrir ou baixar um documento; haverá nova tentativa.")
            if vistos >= total:
                break
        else:
            erros.append("A busca excedeu 10 páginas; é necessário revisar os filtros.")
        await self.context.storage_state(path=str(self.estado.pasta / "sessao.json"))
        if erros:
            raise MonitorError(erros[0])
        if vistos == 0:
            await self.status(
                cli, "monitorando",
                "Media Hub consultado: nenhuma escalação publicada hoje. Nova tentativa em 1 minuto.")
        else:
            await self.status(cli, "monitorando", "Verificação concluída. Aguardando novos PDFs ou correções.")


async def executar(args):
    import httpx
    from playwright.async_api import async_playwright
    monitor = Monitor()
    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, parar.set)
        except NotImplementedError:
            pass
    async with httpx.AsyncClient(timeout=90, follow_redirects=False) as cli, async_playwright() as pw:
        try:
            if args.check_record:
                await monitor.abrir(pw)
                await monitor.processar(cli, args.check_record, None, args.dry_run, ignorar_janela=True)
                return
            erros = 0
            while not parar.is_set():
                inicio = time.monotonic()
                try:
                    await monitor.ciclo(cli, pw)
                    erros = 0
                except Exception as exc:
                    erros += 1
                    mensagem = str(exc) if isinstance(exc, MonitorError) else "Falha de conexão ou mudança no portal; haverá nova tentativa."
                    await monitor.status(cli, "erro", mensagem)
                    if monitor.browser:
                        await monitor.browser.close()
                        monitor.browser = monitor.context = monitor.page = None
                if args.once:
                    if erros:
                        raise MonitorError("A verificação falhou. Consulte o status acima.")
                    return
                intervalo = min(900, monitor.intervalo * 2 ** min(erros, 4))
                try:
                    await asyncio.wait_for(parar.wait(), max(1, intervalo - (time.monotonic() - inicio)))
                except asyncio.TimeoutError:
                    pass
        finally:
            if monitor.browser:
                await monitor.browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check-record", help="URL de registro para teste pontual, sem janela de jogo")
    parser.add_argument("--dry-run", action="store_true", help="Só com --check-record: baixar e validar sem publicar")
    argumentos = parser.parse_args()
    if argumentos.dry_run and not argumentos.check_record:
        parser.error("--dry-run exige --check-record")
    try:
        asyncio.run(executar(argumentos))
    except MonitorError as exc:
        print(str(exc), flush=True)
        raise SystemExit(1)
