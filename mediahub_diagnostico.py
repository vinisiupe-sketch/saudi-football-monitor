"""Diagnóstico pontual de páginas públicas, sem login nem sessão armazenada."""
import asyncio
import json
import os
import subprocess
from urllib.parse import urlparse
from playwright.async_api import async_playwright


async def main():
    print("Diagnóstico público iniciado (sem credenciais).", flush=True)
    async with async_playwright() as pw:
        for headless in (True, False):
            print(f"Abrindo navegador: headless={headless}", flush=True)
            display = None
            if not headless:
                display = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x720x24", "-nolisten", "tcp"])
                os.environ["DISPLAY"] = ":99"
                await asyncio.sleep(1)
            browser = None
            try:
                browser = await pw.chromium.launch(headless=headless, timeout=20000,
                    env={k: os.environ[k] for k in ("DISPLAY", "PATH", "HOME", "LANG") if k in os.environ})
                page = await browser.new_page(locale="en-GB")
                for caminho in ("/", "/site/login"):
                    try:
                        print(f"Consultando {caminho}", flush=True)
                        response = await page.goto("https://mediahub.spl.media" + caminho,
                                                   wait_until="domcontentloaded", timeout=30000)
                        title = await page.title()
                        dados = {"modo": "headless" if headless else "janela",
                                 "caminho": urlparse(page.url).path,
                                 "http": response.status if response else None,
                                 "titulo": title,
                                 "servidor": response.headers.get("server") if response else None,
                                 "cache": response.headers.get("x-cache") if response else None,
                                 "formulario_login": await page.get_by_label("Email address", exact=True).count()}
                        # Só o erro público padrão do CDN; jamais HTML de conta.
                        if title == "ERROR: The request could not be satisfied":
                            dados["erro_cdn"] = (await page.locator("body").inner_text()).split("Request ID:")[0][:1600]
                        print(json.dumps(dados, ensure_ascii=False), flush=True)
                    except Exception as exc:
                        print(json.dumps({"modo": str(headless), "caminho": caminho,
                                          "falha": type(exc).__name__}), flush=True)
            finally:
                if browser:
                    await browser.close()
                if display:
                    display.terminate()
                    try:
                        display.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        display.kill()
                        display.wait()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=120))
