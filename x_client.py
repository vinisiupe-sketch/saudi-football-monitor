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
import json
import time
import asyncio
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

# Limites do X para vídeo, conferidos na documentação deles.
LIMITE_VIDEO_BYTES = 512 * 1024 * 1024
PEDACO_BYTES = 4 * 1024 * 1024      # o teto por append é 5 MB; fico abaixo
MAX_ESPERAS_VIDEO = 40              # ~5 min de processamento no pior caso
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


async def subir_video(dados: bytes, on_status=None) -> str:
    """Sobe um vídeo em pedaços e devolve o media_id.

    Três endpoints próprios, e NÃO o velho "command=INIT" em multipart — esse é
    formato da v1.1. O guia de início rápido do X ainda mostra do jeito antigo;
    seguir o guia rendeu HTTP 400 "Missing media field in JSON". Isto aqui é o
    que a sondagem confirmou funcionando na conta real.

    Sobre a assinatura OAuth: corpo JSON (initialize) e corpo multipart
    (append) ficam FORA dela; só a query do STATUS entra. Errar isso dá 401.
    """
    ok, faltando = configurado()
    if not ok:
        raise XErro("credenciais do X ausentes: " + ", ".join(faltando))
    if not dados:
        raise XErro("vídeo vazio")
    if len(dados) > LIMITE_VIDEO_BYTES:
        raise XErro(f"vídeo tem {len(dados)/1024/1024:.1f} MB; o teto do X é 512 MB")
    cred = credenciais()

    def avisa(t: str) -> None:
        if on_status:
            on_status(t)

    async with httpx.AsyncClient(timeout=180.0) as c:
        url = f"{API_MEDIA}/initialize"
        r = await c.post(url, headers={"Authorization": _cabecalho("POST", url, cred),
                                       "Content-Type": "application/json"},
                         json={"media_type": "video/mp4",
                               "total_bytes": len(dados),
                               "media_category": "tweet_video"})
        if r.status_code >= 300:
            raise XErro(f"initialize falhou: HTTP {r.status_code} {r.text[:200]}")
        mid = str(((r.json() or {}).get("data") or {}).get("id") or "")
        if not mid:
            raise XErro(f"initialize sem media_id: {r.text[:200]}")

        pedacos = [dados[i:i + PEDACO_BYTES]
                   for i in range(0, len(dados), PEDACO_BYTES)]
        if len(pedacos) > 1000:            # segment_index vai só até 999
            raise XErro(f"vídeo exigiria {len(pedacos)} pedaços; o teto é 1000")
        for i, pedaco in enumerate(pedacos):
            url = f"{API_MEDIA}/{mid}/append"
            r = await c.post(url, headers={"Authorization": _cabecalho("POST", url, cred)},
                             files={"media": ("clipe.mp4", pedaco, "video/mp4"),
                                    "segment_index": (None, str(i))})
            if r.status_code >= 300:
                raise XErro(f"append {i+1}/{len(pedacos)} falhou: "
                            f"HTTP {r.status_code} {r.text[:200]}")
            avisa(f"enviando… {i+1}/{len(pedacos)}")

        url = f"{API_MEDIA}/{mid}/finalize"
        r = await c.post(url, headers={"Authorization": _cabecalho("POST", url, cred)})
        if r.status_code >= 300:
            raise XErro(f"finalize falhou: HTTP {r.status_code} {r.text[:200]}")

        # O X transcodifica antes de liberar. Postar com media_id ainda em
        # processamento dá erro, então espero de verdade em vez de torcer.
        info = ((r.json() or {}).get("data") or {}).get("processing_info") or {}
        esperas = 0
        while info.get("state") in ("pending", "in_progress"):
            if esperas >= MAX_ESPERAS_VIDEO:
                raise XErro(f"o X não terminou de processar o vídeo depois de "
                            f"{esperas} checagens; estado: {info.get('state')}")
            await asyncio.sleep(max(1, min(15, int(info.get("check_after_secs") or 1))))
            esperas += 1
            avisa(f"o X está processando… ({info.get('state')})")
            q = {"command": "STATUS", "media_id": mid}
            r = await c.get(API_MEDIA, params=q,
                            headers={"Authorization": _cabecalho("GET", API_MEDIA, cred, q)})
            if r.status_code >= 300:
                raise XErro(f"status falhou: HTTP {r.status_code} {r.text[:200]}")
            info = ((r.json() or {}).get("data") or {}).get("processing_info") or {}
        if info.get("state") == "failed":
            erro = (info.get("error") or {}).get("message") or json.dumps(info)[:200]
            raise XErro(f"o X recusou o vídeo: {erro}")
    return mid


async def publicar(texto: str, imagens: list | None = None,
                   permitir_link: bool = False, publicados_hoje: int = 0,
                   media_ids: list | None = None) -> dict:
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

    # media_ids já prontos entram direto: é o caso do clipe de gol, cujo vídeo
    # foi subido antes, num passo separado, porque leva tempo e tem progresso.
    ids = [str(m) for m in (media_ids or []) if m]
    for img in (imagens or [])[:4]:          # o X aceita no máximo 4
        if isinstance(img, (bytes, bytearray)) or (isinstance(img, str) and os.path.exists(img)):
            ids.append(await subir_imagem(img))

    corpo = {"text": texto}
    if ids:
        corpo["media"] = {"media_ids": ids[:4]}
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
