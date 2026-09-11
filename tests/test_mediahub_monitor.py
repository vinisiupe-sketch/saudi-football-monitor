"""Falhas que não podem causar perda, duplicação ou falso sucesso do monitor."""
import ast
import asyncio
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mediahub_monitor as m


def funcao(arquivo, nome, contexto):
    """Carrega uma função sem iniciar o app, outros coletores ou banco remoto."""
    tree = ast.parse((ROOT / arquivo).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(arquivo), "exec"), contexto)
    return contexto[nome]


class Regras(unittest.TestCase):
    def test_limites_e_fusos(self):
        inicio = m.instante("2026-09-09T21:00:00+03:00")
        self.assertTrue(m.na_janela(inicio, m.instante("2026-09-09T16:20:00Z")))
        self.assertFalse(m.na_janela(inicio, m.instante("2026-09-09T16:19:59Z")))
        self.assertTrue(m.na_janela(inicio, m.instante("2026-09-09T18:00:00Z")))
        self.assertFalse(m.na_janela(inicio, m.instante("2026-09-09T18:00:01Z")))

    def test_busca_temporada_e_rodada_do_mediahub(self):
        dia = m.instante("2026-09-08T22:00:00Z").astimezone(m.ARABIA).date()
        filtros = parse_qs(urlparse(m.busca_url(dia, rodada="MD7")).fragment[2:])["filterBy"][0]
        self.assertIn('Season,"2026/27"', filtros)
        self.assertIn('Match_Week,"MD7"', filtros)
        self.assertNotIn("Match_Date", filtros)

    def test_descobre_rodada_e_seleciona_so_jogos_ativos(self):
        jogos = [{"casa": "Al Qadsiah", "fora": "Al Ettifaq", "rodada": "MD7"},
                 {"casa": "Al Faisaly", "fora": "Al Ittihad", "rodada": "MD7"}]
        self.assertEqual(m.rodada_mediahub(jogos), "MD7")
        self.assertTrue(m.titulo_dos_jogos(
            "Al Qadsiah v Al Ettifaq Team Sheets ENG and AR", jogos))
        self.assertFalse(m.titulo_dos_jogos(
            "Al Khaleej v Al Nassr Team Sheets ENG and AR", jogos))

    def test_urls_externas_e_credenciais_na_url_recusadas(self):
        for url in ("https://evil.test/record/1", "https://mediahub.spl.media@evil.test/record/1",
                    "http://mediahub.spl.media/record/1", "https://mediahub.spl.media/site/login"):
            with self.subTest(url=url), self.assertRaises(m.MonitorError):
                m.url_registro(url)

    def test_pdf_real_e_download_que_na_verdade_e_login(self):
        dados, inicio = m.validar_pdf(ROOT / "tests/fixtures/matchsheet_al_hilal_al_ahli.pdf")
        self.assertEqual(len(dados["casa"]["titulares"]), 11)
        with self.assertRaises(m.MonitorError):
            m.validar_pdf(ROOT / "tests/fixtures/matchsheet_al_hilal_al_ahli.pdf", inicio.date() + timedelta(days=1))
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake.pdf"
            fake.write_text("<html>Login</html>")
            with self.assertRaises(m.MonitorError):
                m.validar_pdf(fake)


class Entrega(unittest.IsolatedAsyncioTestCase):
    async def test_sem_confirmacao_duravel_nao_aceita_sucesso_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "test.pdf"
            pdf.write_bytes(b"%PDF-test")
            for status, corpo in ((503, {}), (401, {}), (200, {"salvo": False}), (200, {})):
                cli = types.SimpleNamespace(post=AsyncMock(return_value=types.SimpleNamespace(status_code=status, json=lambda: corpo)))
                with self.subTest(status=status, corpo=corpo), self.assertRaises(m.MonitorError):
                    await m.entregar(cli, "https://app.test", "segredo-teste", pdf)

    async def test_reiniciar_nao_duplica_e_correcao_reenvia(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"APP_URL": "https://app.test", "ESCALACAO_TOKEN": "segredo-teste", "MEDIAHUB_DATA_DIR": tmp}
            with patch.dict(os.environ, env):
                monitor = m.Monitor()
                conteudo = [b"%PDF-primeira"]
                async def baixar(url, caminho):
                    caminho.write_bytes(conteudo[0])
                    return True
                monitor.baixar = baixar
                monitor.status = AsyncMock()
                registro = "https://mediahub.spl.media/record/14146"
                with patch.object(m, "validar_pdf", return_value=({}, m.agora())), patch.object(m, "entregar", new_callable=AsyncMock) as envio:
                    envio.side_effect = m.MonitorError("falha transitória")
                    with self.assertRaises(m.MonitorError):
                        await monitor.processar(None, registro, None, ignorar_janela=True)
                    self.assertEqual(m.Estado(tmp).dados["registros"], {})
                    envio.side_effect = None
                    await monitor.processar(None, registro, None, ignorar_janela=True)
                    self.assertEqual(envio.await_count, 2)
                    monitor.estado = m.Estado(tmp)
                    await monitor.processar(None, registro, None, ignorar_janela=True)
                    self.assertEqual(envio.await_count, 2)
                    conteudo[0] = b"%PDF-corrigida"
                    await monitor.processar(None, registro, None, ignorar_janela=True)
                    self.assertEqual(envio.await_count, 3)

    async def test_registro_sem_anexo_nao_e_erro_nem_entrega(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "APP_URL": "https://app.test", "ESCALACAO_TOKEN": "teste", "MEDIAHUB_DATA_DIR": tmp}):
            monitor = m.Monitor()
            monitor.baixar = AsyncMock(return_value=False)
            with patch.object(m, "entregar", new_callable=AsyncMock) as envio:
                await monitor.processar(None, "https://mediahub.spl.media/record/14164", None)
                envio.assert_not_awaited()
                self.assertEqual(monitor.estado.dados["registros"], {})


class Persistencia(unittest.TestCase):
    def test_upsert_substitui_correcao_sem_mudar_primeira_observacao(self):
        # Exercita o SQL real de conflito em banco em memória. A integração
        # PostgreSQL de produção continua sendo uma etapa separada do deploy.
        banco = sqlite3.connect(":memory:")
        banco.execute("CREATE TABLE escalacao_vista (fonte TEXT, chave TEXT, jogo TEXT, conteudo TEXT, visto_em TEXT DEFAULT 'primeira', UNIQUE(fonte,chave))")
        class Cursor:
            def execute(self, sql, args):
                return banco.execute(sql.replace("%s", "?"), args)
        @contextmanager
        def conexao():
            with banco:
                yield types.SimpleNamespace(cursor=lambda: Cursor())
        salvar = funcao("database.py", "salvar_escalacao_pdf", {"get_conn": conexao, "_cria_escalacao": lambda c: None})
        salvar("jogo-1", "A x B", "original")
        salvar("jogo-1", "A x B", "corrigido")
        self.assertEqual(banco.execute("SELECT conteudo, visto_em FROM escalacao_vista").fetchall(), [("corrigido", "primeira")])
        banco.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            salvar("jogo-2", "C x D", "não salvo")


class Status(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_parado_nao_parece_ativo(self):
        ctx = {"Request": object, "JSONResponse": lambda *a, **k: None,
               "_escalacao_autorizada": lambda r: True, "json": json,
               "datetime": datetime, "timezone": timezone,
               "get_state": lambda chave: json.dumps({"estado": "monitorando", "mensagem": "ok",
                    "visto_em": (m.agora() - timedelta(minutes=6)).isoformat()})}
        consultar = funcao("main.py", "consultar_status_monitor", ctx)
        status = await consultar(None)
        self.assertTrue(status["atrasado"])
        self.assertIn("sem contato", status["mensagem"])


if __name__ == "__main__":
    unittest.main()
