"""Diagnóstico pontual de páginas públicas, sem login nem sessão armazenada."""
import asyncio
import json
from urllib.parse import urlparse
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        for headless in (True, False):
            browser = await pw.chromium.launch(headless=headless)
            try:
                page = await browser.new_page(locale="en-GB")
                for caminho in ("/", "/site/login"):
                    try:
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
                await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
