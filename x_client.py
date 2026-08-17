"""
Publicação no X (Twitter).

Assina OAuth 1.0a à mão para não acrescentar dependência: publicar exige
autenticação como usuário, e o Bearer Token (só-app) não serve.

Duas travas de custo vivem aqui, e não na tela, porque tela se contorna:
post com link custa US$ 0,20 contra US$ 0,015 do post normal — 13 vezes mais —
e um laço com defeito poderia publicar sem parar.
"""
import os
import re
import time
import hmac
import base64
import hashlib
import secrets
from urllib.parse import quote, urlencode

import httpx

API_POST = "https://api.x.com/2/tweets"
# Endpoint atual, conferido em docs.x.com/x-api/media/upload-media: o antigo
# upload.twitter.com/1.1/media/upload.json foi substituído por este.
API_MEDIA = "https://api.x.com/2/media/upload"

LIMITE_DIARIO = 40          # teto de segurança; uma rodada tem 9 jogos
CUSTO_POST = 0.015
CUSTO_POST_COM_LINK = 0.200

_URL_NO_TEXTO = re.compile(r"https?://|www\.", re.I)


class XErro(RuntimeError):
    pass


def credenciais() -> dict:
    return {
        "api_key": os.environ.get("X_API_KEY", ""),
        "api_secret": os.environ.get("X_API_SECRET", ""),
        "token": os.environ.get("X_ACCESS_TOKEN", ""),
        "token_secret": os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
    }


def configurado() -> tuple[bool, list[str]]:
    """Diz se dá pra publicar, sem NUNCA devolver o valor das chaves."""
    c = credenciais()
    faltando = [k for k, v in c.items() if not v]
    return (not faltando), faltando


def _pct(s: str) -> str:
    return quote(str(s), safe="~")


def _assinatura(metodo: str, url: str, params: dict, cred: dict) -> str:
    base = "&".join([metodo.upper(), _pct(url),
                     _pct("&".join(f"{_pct(k)}={_pct(params[k])}" for k in sorted(params)))])
    chave = f"{_pct(cred['api_secret'])}&{_pct(cred['token_secret'])}"
    bruto = hmac.new(chave.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(bruto).decode()


def _cabecalho(metodo: str, url: str, cred: dict, params_extra: dict | None = None) -> str:
    oauth = {
        "oauth_consumer_key": cred["api_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": cred["token"],
        "oauth_version": "1.0",
    }
    # Parâmetros de formulário entram na assinatura; corpo JSON, não.
    todos = dict(oauth)
    todos.update(params_extra or {})
    oauth["oauth_signature"] = _assinatura(metodo, url, todos, cred)
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


def texto_tem_link(texto: str) -> bool:
    return bool(_URL_NO_TEXTO.search(texto or ""))


async def subir_imagem(imagem) -> str:
    """Sobe uma imagem e devolve o media_id. Aceita bytes ou caminho de arquivo.

    A versão anterior mandava o corpo como application/x-www-form-urlencoded e
    deixava media_data de fora da assinatura. Isso dava HTTP 401 code 32
    ("Could not authenticate you"): a RFC 5849 manda incluir os campos do corpo
    na assinatura justamente quando ele é urlencoded. Em multipart o corpo fica
    de fora, que é o caso aqui — por isso a assinatura não leva campo nenhum.
    """
    cred = credenciais()
    if isinstance(imagem, (bytes, bytearray)):
        dados = bytes(imagem)
    else:
        with open(imagem, "rb") as f:
            dados = f.read()
    cabecalho = _cabecalho("POST", API_MEDIA, cred)
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            API_MEDIA,
            files={"media": ("escudo.png", dados, "image/png")},
            data={"media_category": "tweet_image"},   # obrigatório na v2
            headers={"Authorization": cabecalho},
        )
    if r.status_code >= 300:
        raise XErro(f"upload da imagem falhou: HTTP {r.status_code} {r.text[:200]}")
    corpo = r.json() or {}
    # A v2 devolve {"data": {"id": ...}}; media_id_string era da v1.1.
    mid = (corpo.get("data") or {}).get("id") or corpo.get("media_id_string")
    if not mid:
        raise XErro(f"upload sem media_id na resposta: {r.text[:200]}")
    return str(mid)


async def publicar(texto: str, imagens: list | None = None,
                   permitir_link: bool = False, publicados_hoje: int = 0) -> dict:
    """Publica e devolve {id, custo}. Levanta XErro em qualquer recusa."""
    ok, faltando = configurado()
    if not ok:
        raise XErro("credenciais do X ausentes: " + ", ".join(faltando))
    if not (texto or "").strip():
        raise XErro("texto vazio")
    if len(texto) > 280:
        raise XErro(f"texto com {len(texto)} caracteres; o limite é 280")
    if texto_tem_link(texto) and not permitir_link:
        raise XErro("o texto contém link, que custa US$ 0,20 em vez de US$ 0,015 "
                    "(13x mais). Remova o link ou libere explicitamente.")
    if publicados_hoje >= LIMITE_DIARIO:
        raise XErro(f"limite diário de {LIMITE_DIARIO} publicações atingido")

    media_ids = []
    for img in (imagens or [])[:4]:          # o X aceita no máximo 4
        if isinstance(img, (bytes, bytearray)) or (isinstance(img, str) and os.path.exists(img)):
            media_ids.append(await subir_imagem(img))

    corpo = {"text": texto}
    if media_ids:
        corpo["media"] = {"media_ids": media_ids}
    cred = credenciais()
    cabecalho = _cabecalho("POST", API_POST, cred)
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(API_POST, json=corpo,
                         headers={"Authorization": cabecalho,
                                  "Content-Type": "application/json"})
    if r.status_code >= 300:
        raise XErro(f"HTTP {r.status_code}: {r.text[:300]}")
    dados = (r.json() or {}).get("data") or {}
    return {"id": str(dados.get("id") or ""),
            "custo": CUSTO_POST_COM_LINK if texto_tem_link(texto) else CUSTO_POST}
