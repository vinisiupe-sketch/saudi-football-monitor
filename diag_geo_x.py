"""
Sondagem: qual é o formato do campo geo_restrictions na API do X?

POR QUE ISTO EXISTE
    O plano de publicar o clipe de gol restrito ao Brasil depende inteiro de um
    campo que o X documenta como existente e NÃO documenta como se preenche:
    em POST /2/media/metadata, geo_restrictions aparece no OpenAPI apenas como
    "type: object", sem propriedade nenhuma. Ou seja: sei que o campo existe,
    não sei o que colocar dentro.

    Melhor descobrir agora, com um vídeo preto de 4 KB, do que depois de
    construir o gravador inteiro.

O QUE ELA FAZ
    1. Sobe um vídeo mínimo (1 segundo, preto, mudo) pelo fluxo picotado real
       — INIT / APPEND / FINALIZE / STATUS — que é o mesmo que o clipe usará.
    2. Tenta várias formas possíveis de geo_restrictions, uma por vez.
    3. Lê de volta o associated_metadata que o X devolve e mostra o que grudou.

O QUE ELA NÃO FAZ
    Não publica nada. Não existe chamada a /2/tweets neste arquivo.
    Não imprime nem devolve o valor de chave nenhuma.

CUSTO
    Media Metadata custa US$ 0,005 por requisição. Com as formas abaixo, algo
    entre US$ 0,03 e US$ 0,05. O upload da mídia não consta na tabela de preços.

COMO LER O RESULTADO
    HTTP 200 sozinho NÃO é vitória: o X pode aceitar a requisição e ignorar um
    campo que não entendeu. A prova é o associated_metadata voltar com a
    restrição dentro. Por isso o relatório mostra a resposta crua.
"""
import asyncio
import base64
import json

import httpx

import x_client

API_MEDIA = "https://api.x.com/2/media/upload"
API_METADATA = "https://api.x.com/2/media/metadata"

# Vídeo de teste: 1s, 320x240, preto, áudio mudo. H.264 High + AAC + faststart,
# que é o padrão que o X aceita. Vai embutido para a sondagem não depender de
# ffmpeg instalado no servidor.
VIDEO_B64 = (
    "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"
    "AAAAAQAAAAEAAAAEAAAAAgAAAAEAAAAFAAAAAQAAAAEAAAAGAAAAAgAAAAEAAAAHAAAAAQAA"
    "AAEAAAAIAAAAAgAAAAEAAAAJAAAAAQAAAAEAAAALAAAAAgAAAAEAAAAMAAAAAQAAAAEAAAAN"
    "AAAAAgAAAAEAAAAOAAAAAQAAAAEAAAAPAAAAAgAAAAEAAAAQAAAAAQAAAAEAAAASAAAAAgAA"
    "AAEAAAATAAAAAQAAAAEAAAAUAAAAAgAAAAEAAAAVAAAAAQAAAAEAAAAWAAAAAgAAAAEAAAAX"
    "AAAAAQAAAAEAAAAYAAAAAgAAAAEAAAAZAAAAAQAAAAEAAAAbAAAAAgAAAAEAAAAcAAAAAQAA"
    "AAEAAAAdAAAABQAAAAEAAADIc3RzegAAAAAAAAAAAAAALQAAABgAAAAGAAAABgAAAAYAAAAG"
    "AAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAA"
    "AAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAG"
    "AAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAA"
    "AIRzdGNvAAAAAAAAAB0AAAzRAAAM9wAADREAAA0lAAANSAAADV4AAA14AAANjAAADa8AAA3F"
    "AAAN2QAADfMAAA4QAAAOLAAADkAAAA5aAAAOdwAADo0AAA6nAAAOuwAADt0AAA7zAAAPDQAA"
    "DyEAAA9DAAAPWQAAD20AAA+HAAAPowAAABpzZ3BkAQAAAHJvbGwAAAACAAAAAf//AAAAHHNi"
    "Z3AAAAAAcm9sbAAAAAEAAAAtAAAAAQAAAGJ1ZHRhAAAAWm1ldGEAAAAAAAAAIWhkbHIAAAAA"
    "AAAAAG1kaXJhcHBsAAAAAAAAAAAAAAAALWlsc3QAAAAlqXRvbwAAAB1kYXRhAAAAAQAAAABM"
    "YXZmNTguNzYuMTAwAAAACGZyZWUAAAX5bWRhdAAAAq4GBf//qtxF6b3m2Ui3lizYINkj7u94"
    "MjY0IC0gY29yZSAxNjMgcjMwNjAgNWRiNmFhNiAtIEguMjY0L01QRUctNCBBVkMgY29kZWMg"
    "LSBDb3B5bGVmdCAyMDAzLTIwMjEgLSBodHRwOi8vd3d3LnZpZGVvbGFuLm9yZy94MjY0Lmh0"
    "bWwgLSBvcHRpb25zOiBjYWJhYz0xIHJlZj0zIGRlYmxvY2s9MTowOjAgYW5hbHlzZT0weDM6"
    "MHgxMTMgbWU9aGV4IHN1Ym1lPTcgcHN5PTEgcHN5X3JkPTEuMDA6MC4wMCBtaXhlZF9yZWY9"
    "MSBtZV9yYW5nZT0xNiBjaHJvbWFfbWU9MSB0cmVsbGlzPTEgOHg4ZGN0PTEgY3FtPTAgZGVh"
    "ZHpvbmU9MjEsMTEgZmFzdF9wc2tpcD0xIGNocm9tYV9xcF9vZmZzZXQ9LTIgdGhyZWFkcz0z"
    "IGxvb2thaGVhZF90aHJlYWRzPTEgc2xpY2VkX3RocmVhZHM9MCBucj0wIGRlY2ltYXRlPTEg"
    "aW50ZXJsYWNlZD0wIGJsdXJheV9jb21wYXQ9MCBjb25zdHJhaW5lZF9pbnRyYT0wIGJmcmFt"
    "ZXM9MyBiX3B5cmFtaWQ9MiBiX2FkYXB0PTEgYl9iaWFzPTAgZGlyZWN0PTEgd2VpZ2h0Yj0x"
    "IG9wZW5fZ29wPTAgd2VpZ2h0cD0yIGtleWludD0yNTAga2V5aW50X21pbj0yNSBzY2VuZWN1"
    "dD00MCBpbnRyYV9yZWZyZXNoPTAgcmNfbG9va2FoZWFkPTQwIHJjPWNyZiBtYnRyZWU9MSBj"
    "cmY9MjMuMCBxY29tcD0wLjYwIHFwbWluPTAgcXBtYXg9NjkgcXBzdGVwPTQgaXBfcmF0aW89"
    "MS40MCBhcT0xOjEuMDAAgAAAADpliIQAN//+9vD+BTZWBFCXEc3onTMfvxW4ujQ3vc4AAq1P"
    "EG+4LBNpT2AQQAABnxHdErgspBAQL0rrAAAADUGaJGxDf/6nhAAA3oDeBABMYXZjNTguMTM0"
    "LjEwMABCIAjBGDgAAAAKQZ5CeIV/AAC2gSEQBGCMHCEQBGCMHAAAAAoBnmF0Qn8AAOmAIRAE"
    "YIwcAAAACgGeY2pCfwAA6YEhEARgjBwhEARgjBwAAAATQZpoSahBaJlMCG///qeEAADegSEQ"
    "BGCMHAAAAAxBnoZFESwr/wAAtoEhEARgjBwhEARgjBwAAAAKAZ6ldEJ/AADpgSEQBGCMHAAA"
    "AAoBnqdqQn8AAOmAIRAEYIwcIRAEYIwcAAAAE0GarEmoQWyZTAhv//6nhAAA3oAhEARgjBwA"
    "AAAMQZ7KRRUsK/8AALaBIRAEYIwcAAAACgGe6XRCfwAA6YAhEARgjBwhEARgjBwAAAAKAZ7r"
    "akJ/AADpgCEQBGCMHAAAABNBmvBJqEFsmUwIb//+p4QAAN6BIRAEYIwcIRAEYIwcAAAADEGf"
    "DkUVLCv/AAC2gSEQBGCMHAAAAAoBny10Qn8AAOmBIRAEYIwcIRAEYIwcAAAACgGfL2pCfwAA"
    "6YAhEARgjBwAAAATQZs0SahBbJlMCG///qeEAADegCEQBGCMHAAAAAxBn1JFFSwr/wAAtoEh"
    "EARgjBwhEARgjBwAAAAKAZ9xdEJ/AADpgCEQBGCMHAAAAAoBn3NqQn8AAOmAIRAEYIwcIRAE"
    "YIwcAAAAEkGbeEmoQWyZTAhn//6eEAADZyEQBGCMHAAAAAxBn5ZFFSwr/wAAtoAhEARgjBwh"
    "EARgjBwAAAAKAZ+1dEJ/AADpgSEQBGCMHAAAAAoBn7dqQn8AAOmBIRAEYIwcIRAEYIwcAAAA"
    "EkGbvEmoQWyZTAhX//44QAANSCEQBGCMHAAAAAxBn9pFFSwr/wAAtoEhEARgjBwAAAAKAZ/5"
    "dEJ/AADpgCEQBGCMHCEQBGCMHAAAAAoBn/tqQn8AAOmBIRAEYIwcAAAAEkGb/UmoQWyZTAhP"
    "//3xAAAf4SEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHA=="
)

# As formas candidatas, em ordem de aposta.
#
# A primeira vem de uma pista dentro da própria documentação: o campo irmão
# domain_restrictions, que fica no MESMO objeto de metadata, é declarado como
# {"whitelist": [...]}. Mesma equipe, mesmo lugar, provavelmente mesma forma.
# As outras cobrem as convenções usuais.
FORMAS = [
    ("whitelist", {"whitelist": ["BR"]}),
    ("allow_countries", {"allow_countries": ["BR"]}),
    ("allowed_countries", {"allowed_countries": ["BR"]}),
    ("countries+allow", {"countries": ["BR"], "allow": True}),
    ("country_codes", {"country_codes": ["BR"], "type": "allow"}),
    ("allow", {"allow": ["BR"]}),
    ("blacklist", {"blacklist": ["US"]}),
]


def _linhas_cred() -> tuple[bool, str]:
    ok, faltando = x_client.configurado()
    return ok, ("faltando: " + ", ".join(faltando) if faltando else "")


async def _subir_video(cred: dict, dados: bytes, diz) -> str:
    """INIT / APPEND / FINALIZE / STATUS. Devolve o media_id."""
    # INIT — multipart, então nenhum campo do corpo entra na assinatura OAuth.
    cab = x_client._cabecalho("POST", API_MEDIA, cred)
    async with httpx.AsyncClient(timeout=90.0) as c:
        r = await c.post(API_MEDIA, headers={"Authorization": cab}, files={
            "command": (None, "INIT"),
            "media_type": (None, "video/mp4"),
            "total_bytes": (None, str(len(dados))),
            "media_category": (None, "tweet_video"),
        })
        diz(f"    INIT      -> HTTP {r.status_code} {r.text[:200]}")
        if r.status_code >= 300:
            raise RuntimeError("INIT falhou")
        mid = str(((r.json() or {}).get("data") or {}).get("id") or "")
        if not mid:
            raise RuntimeError("INIT sem media_id")

        # APPEND — o arquivo é minúsculo, um pedaço só.
        cab = x_client._cabecalho("POST", API_MEDIA, cred)
        r = await c.post(API_MEDIA, headers={"Authorization": cab}, files={
            "command": (None, "APPEND"),
            "media_id": (None, mid),
            "segment_index": (None, "0"),
            "media": ("clipe.mp4", dados, "video/mp4"),
        })
        diz(f"    APPEND    -> HTTP {r.status_code} {r.text[:160]}")
        if r.status_code >= 300:
            raise RuntimeError("APPEND falhou")

        cab = x_client._cabecalho("POST", API_MEDIA, cred)
        r = await c.post(API_MEDIA, headers={"Authorization": cab}, files={
            "command": (None, "FINALIZE"),
            "media_id": (None, mid),
        })
        diz(f"    FINALIZE  -> HTTP {r.status_code} {r.text[:250]}")
        if r.status_code >= 300:
            raise RuntimeError("FINALIZE falhou")

        info = ((r.json() or {}).get("data") or {}).get("processing_info") or {}
        # STATUS é GET com parâmetros na URL — e AÍ eles entram na assinatura,
        # ao contrário do corpo multipart dos passos acima.
        esperas = 0
        while info.get("state") in ("pending", "in_progress") and esperas < 20:
            await asyncio.sleep(max(1, int(info.get("check_after_secs") or 1)))
            esperas += 1
            q = {"command": "STATUS", "media_id": mid}
            cab = x_client._cabecalho("GET", API_MEDIA, cred, q)
            r = await c.get(API_MEDIA, params=q, headers={"Authorization": cab})
            if r.status_code >= 300:
                diz(f"    STATUS    -> HTTP {r.status_code} {r.text[:160]}")
                break
            info = ((r.json() or {}).get("data") or {}).get("processing_info") or {}
            diz(f"    STATUS    -> {info.get('state')}")
        if info and info.get("state") == "failed":
            raise RuntimeError(f"processamento falhou: {json.dumps(info)[:200]}")
    return mid


async def _tentar(cred: dict, mid: str, rotulo: str, forma: dict, diz) -> bool:
    """Aplica uma forma de geo_restrictions e confere se ela grudou."""
    corpo = {"id": mid, "metadata": {"geo_restrictions": forma}}
    cab = x_client._cabecalho("POST", API_METADATA, cred)   # corpo JSON: fora da assinatura
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(API_METADATA, json=corpo,
                         headers={"Authorization": cab,
                                  "Content-Type": "application/json"})
    diz(f"    {rotulo:18} HTTP {r.status_code}")
    diz(f"        enviei : {json.dumps(forma, ensure_ascii=False)}")
    diz(f"        recebi : {r.text[:400]}")
    if r.status_code >= 300:
        return False
    # A prova não é o 200 — é o campo voltar no associated_metadata. O X pode
    # aceitar a chamada e descartar em silêncio um campo que não entendeu.
    voltou = ((r.json() or {}).get("data") or {}).get("associated_metadata") or {}
    grudou = "geo" in json.dumps(voltou).lower()
    diz(f"        grudou : {'SIM' if grudou else 'não (o campo não voltou)'}")
    return grudou


async def sondar() -> str:
    """Roda a sondagem e devolve o relatório em texto."""
    linhas: list[str] = []

    def diz(t: str = "") -> None:
        linhas.append(t)

    diz("=" * 72)
    diz("SONDAGEM — formato do geo_restrictions na API do X")
    diz("=" * 72)
    diz()

    ok, falta = _linhas_cred()
    diz(f"credenciais do X: {'ok' if ok else 'INCOMPLETAS — ' + falta}")
    if not ok:
        diz()
        diz("Sem as quatro variáveis no Railway não dá para sondar.")
        return "\n".join(linhas)

    cred = x_client.credenciais()
    dados = base64.b64decode(VIDEO_B64)
    diz(f"vídeo de teste: {len(dados)} bytes (1s, preto, mudo)")
    diz()

    diz("1) UPLOAD PICOTADO — o mesmo caminho que o clipe de gol vai usar")
    diz("-" * 72)
    try:
        mid = await _subir_video(cred, dados, diz)
    except Exception as e:
        diz()
        diz(f"    PAROU AQUI: {type(e).__name__}: {e}")
        diz()
        diz("    Se o upload de vídeo não passa, não adianta testar o geo.")
        diz("    Este já é um achado: o problema é o upload, não a restrição.")
        return "\n".join(linhas)
    diz(f"    media_id obtido: {mid}")
    diz()

    diz("2) FORMATOS DE geo_restrictions")
    diz("-" * 72)
    vencedores = []
    for rotulo, forma in FORMAS:
        try:
            if await _tentar(cred, mid, rotulo, forma, diz):
                vencedores.append((rotulo, forma))
        except Exception as e:
            diz(f"    {rotulo:18} EXPLODIU: {type(e).__name__}: {e}")
        diz()

    diz("=" * 72)
    diz("VEREDITO")
    diz("-" * 72)
    if vencedores:
        diz(f"    {len(vencedores)} formato(s) aceito(s) e confirmado(s) na volta:")
        for rotulo, forma in vencedores:
            diz(f"      {rotulo}: {json.dumps(forma, ensure_ascii=False)}")
        diz()
        diz("    Dá para restringir ao Brasil por API. O plano automático vive.")
    else:
        diz("    Nenhum formato grudou.")
        diz()
        diz("    Isso NÃO significa necessariamente que é impossível — pode ser")
        diz("    que o campo exija nível de acesso que esta conta não tem, ou")
        diz("    uma forma que eu não adivinhei. Mas significa que publicar")
        diz("    restrito por API não está ao nosso alcance hoje, e que a")
        diz("    restrição teria de ser feita à mão no Media Studio.")
    diz("=" * 72)
    diz()
    diz("Nada foi publicado. Este arquivo não chama /2/tweets em lugar nenhum.")
    return "\n".join(linhas)
