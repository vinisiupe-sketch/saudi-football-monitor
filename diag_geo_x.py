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
    1. Sobe um vídeo mínimo (1 segundo, preto, mudo) pelo caminho real da v2
       — initialize / append / finalize — que é o mesmo que o clipe usará.
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


async def _subir_video(cred: dict, dados: bytes, diz,
                       categoria: str = "tweet_video") -> str:
    """initialize / append / finalize. Devolve o media_id.

    A v2 NÃO usa mais o velho "command=INIT" em multipart no /2/media/upload —
    esse é o formato da v1.1. O guia de início rápido do X ainda mostra assim,
    e eu segui o guia: deu HTTP 400 "Missing media field in JSON", porque sem o
    command reconhecido a chamada virava um upload simples, que exige o campo
    media. A referência do OpenAPI tem endpoints próprios para cada passo.
    """
    async with httpx.AsyncClient(timeout=90.0) as c:
        # ── initialize: corpo JSON (e corpo JSON não entra na assinatura OAuth)
        url = f"{API_MEDIA}/initialize"
        cab = x_client._cabecalho("POST", url, cred)
        r = await c.post(url, headers={"Authorization": cab,
                                       "Content-Type": "application/json"},
                         json={"media_type": "video/mp4",
                               "total_bytes": len(dados),
                               "media_category": categoria})
        diz(f"    initialize -> HTTP {r.status_code} {r.text[:220]}")
        if r.status_code >= 300:
            raise RuntimeError("initialize falhou")
        mid = str(((r.json() or {}).get("data") or {}).get("id") or "")
        if not mid:
            raise RuntimeError("initialize sem id")

        # ── append: multipart, com media e segment_index. Arquivo minúsculo,
        # um pedaço só. (multipart também fica fora da assinatura.)
        url = f"{API_MEDIA}/{mid}/append"
        cab = x_client._cabecalho("POST", url, cred)
        r = await c.post(url, headers={"Authorization": cab}, files={
            "media": ("clipe.mp4", dados, "video/mp4"),
            "segment_index": (None, "0"),
        })
        diz(f"    append     -> HTTP {r.status_code} {r.text[:180]}")
        if r.status_code >= 300:
            raise RuntimeError("append falhou")

        # ── finalize
        url = f"{API_MEDIA}/{mid}/finalize"
        cab = x_client._cabecalho("POST", url, cred)
        r = await c.post(url, headers={"Authorization": cab})
        diz(f"    finalize   -> HTTP {r.status_code} {r.text[:260]}")
        if r.status_code >= 300:
            raise RuntimeError("finalize falhou")

        info = ((r.json() or {}).get("data") or {}).get("processing_info") or {}
        esperas = 0
        while info.get("state") in ("pending", "in_progress") and esperas < 20:
            await asyncio.sleep(max(1, int(info.get("check_after_secs") or 1)))
            esperas += 1
            # STATUS é GET com parâmetros na URL — e AÍ eles entram na
            # assinatura, ao contrário dos corpos JSON e multipart acima.
            q = {"command": "STATUS", "media_id": mid}
            cab = x_client._cabecalho("GET", API_MEDIA, cred, q)
            r = await c.get(API_MEDIA, params=q, headers={"Authorization": cab})
            if r.status_code >= 300:
                diz(f"    status     -> HTTP {r.status_code} {r.text[:160]}")
                diz("    (sigo assim mesmo: um vídeo de 4 KB não costuma "
                    "precisar de processamento)")
                break
            info = ((r.json() or {}).get("data") or {}).get("processing_info") or {}
            diz(f"    status     -> {info.get('state')}")
        if info and info.get("state") == "failed":
            raise RuntimeError(f"processamento falhou: {json.dumps(info)[:200]}")
    return mid


async def _tentar(cred: dict, mid: str, rotulo: str, meta: dict, diz,
                  url: str = API_METADATA) -> tuple[int, bool]:
    """Aplica um metadado e devolve (status_http, grudou)."""
    corpo = {"id": mid, "metadata": meta}
    cab = x_client._cabecalho("POST", url, cred)   # corpo JSON: fora da assinatura
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(url, json=corpo,
                             headers={"Authorization": cab,
                                      "Content-Type": "application/json"})
    except Exception as e:
        diz(f"    {rotulo:18} EXPLODIU: {type(e).__name__}: {e}")
        return 0, False
    diz(f"    {rotulo:18} HTTP {r.status_code}")
    diz(f"        enviei : {json.dumps(meta, ensure_ascii=False)[:160]}")
    diz(f"        recebi : {r.text[:400]}")
    if r.status_code >= 300:
        return r.status_code, False
    # A prova não é o 200 — é o campo voltar no associated_metadata. O X pode
    # aceitar a chamada e descartar em silêncio um campo que não entendeu.
    voltou = ((r.json() or {}).get("data") or {}).get("associated_metadata") or {}
    diz(f"        voltou : {json.dumps(voltou, ensure_ascii=False)[:300]}")
    return r.status_code, bool(voltou)


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

    diz("1) UPLOAD EM PEDAÇOS — o mesmo caminho que o clipe de gol vai usar")
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

    # CONTROLE. Sem isto eu não sei distinguir "o formato está errado" de "o
    # endpoint não está respondendo". Na rodada anterior as sete tentativas
    # voltaram 503 iguais e eu escrevi no veredito que a restrição por API
    # estava fora do alcance — conclusão que o dado não sustentava.
    # alt_text é o campo mais simples e documentado do mesmo objeto: se ele
    # passa, o endpoint funciona e o problema é o geo. Se ele também falha,
    # o problema é o endpoint e nada foi testado sobre o geo.
    diz("2) CONTROLE — o endpoint de metadados responde a alguma coisa?")
    diz("-" * 72)
    st_ctrl, ok_ctrl = await _tentar(cred, mid, "alt_text (controle)",
                                     {"alt_text": {"text": "teste de sondagem"}}, diz)
    diz()
    if st_ctrl >= 500 or st_ctrl == 0:
        diz(f"    O CONTROLE FALHOU (HTTP {st_ctrl}).")
        diz("    O endpoint de metadados não está respondendo nem ao campo mais")
        diz("    simples que existe. Testar geo_restrictions agora não mede nada")
        diz("    e só gastaria crédito — paro aqui.")
        diz()
        diz("    Tente de novo em alguns minutos. Se persistir, é indisponibilidade")
        diz("    do lado deles ou falta de permissão nesta chave, e não formato.")
        diz("=" * 72)
        return "\n".join(linhas)
    if st_ctrl >= 400:
        diz(f"    Controle voltou {st_ctrl} — o endpoint responde, mas recusou até")
        diz("    o alt_text. Provável falta de permissão (escopo media.write).")
        diz("    Sigo mesmo assim: a resposta do geo ainda informa.")
        diz()

    diz("3) FORMATOS DE geo_restrictions")
    diz("-" * 72)
    vencedores, servidor_falhou = [], 0
    for rotulo, forma in FORMAS:
        st, grudou = await _tentar(cred, mid, rotulo, {"geo_restrictions": forma}, diz)
        if st >= 500 or st == 0:
            servidor_falhou += 1
        elif grudou:
            vencedores.append((rotulo, forma))
        diz()
        # Espaço entre as chamadas: sete requisições instantâneas podem ser
        # barradas por ritmo, e aí eu leria estrangulamento como recusa.
        await asyncio.sleep(2)

    # ── 4. É o CAMPO ou é a FORMA? ──────────────────────────────────────
    # O controle provou que o endpoint funciona. Falta separar duas coisas
    # que o 503 não distingue sozinho:
    #
    #   (a) o handler do geo_restrictions está quebrado/desligado, e QUALQUER
    #       valor derruba — inclusive objeto vazio e tipo errado;
    #   (b) só as formas que eu inventei estão erradas.
    #
    # Se {} e uma string também derem 503, é (a): nem chega na validação.
    # Um campo validado responderia 400 a um tipo errado, não 503.
    #
    # Testo junto dois campos IRMÃOS do mesmo objeto, escolhidos de propósito:
    # allow_download_status é bem especificado no OpenAPI (tem propriedades),
    # sensitive_media_warning é declarado como "type: object" pelado, igual ao
    # geo_restrictions. Se os pelados falham e os especificados passam, o
    # padrão deixa de ser palpite e vira achado.
    if not vencedores:
        diz("4) É O CAMPO OU É A FORMA?")
        diz("-" * 72)
        provas = {}
        for chave, rot, meta in [
            ("vazio",   "geo vazio {}", {"geo_restrictions": {}}),
            ("tipo",    "geo tipo errado", {"geo_restrictions": "BR"}),
            ("irmao1",  "irmão especificado",
             {"allow_download_status": {"allow_download": False}}),
            ("irmao2",  "irmão 'object' pelado",
             {"sensitive_media_warning": {"other": True}}),
        ]:
            st, _g = await _tentar(cred, mid, rot, meta, diz)
            provas[chave] = st
            diz()
            await asyncio.sleep(2)

        # ── 5. A hipótese do Amplify ────────────────────────────────────────
        # A restrição geográfica, na interface, é recurso de publisher: mora no
        # Media Studio, junto de monetização e Amplify. Talvez ela exija que a
        # mídia tenha sido criada como amplify_video, e não tweet_video. Custa
        # um upload a mais descobrir.
        diz("5) E SE A MÍDIA FOR amplify_video EM VEZ DE tweet_video?")
        diz("-" * 72)
        try:
            mid2 = await _subir_video(cred, dados, diz, categoria="amplify_video")
            diz(f"    media_id amplify: {mid2}")
            diz()
            for rot, forma in FORMAS[:3]:
                st, grudou = await _tentar(cred, mid2, rot + " (amplify)",
                                           {"geo_restrictions": forma}, diz)
                if grudou:
                    # Sem esta linha a descoberta não entrava na conta e o
                    # veredito continuava dizendo que tudo falhou. Meu teste de
                    # cenário pegou: seria o erro de ontem invertido, jogando
                    # fora justamente o resultado que interessa.
                    vencedores.append((rot + " (só com amplify_video)", forma))
                diz()
                await asyncio.sleep(2)
        except Exception as e:
            diz(f"    não consegui subir como amplify_video: {type(e).__name__}: {e}")
            diz("    (isso por si só já diz que a conta não tem acesso a Amplify)")
            diz()

    diz("=" * 72)
    diz("VEREDITO")
    diz("-" * 72)
    if vencedores:
        diz(f"    {len(vencedores)} formato(s) aceito(s) e confirmado(s) na volta:")
        for rotulo, forma in vencedores:
            diz(f"      {rotulo}: {json.dumps(forma, ensure_ascii=False)}")
        diz()
        if any("amplify" in r for r, _ in vencedores):
            diz("    ATENÇÃO: só funcionou com a mídia criada como amplify_video,")
            diz("    e não como tweet_video. O clipe de gol teria de ser subido")
            diz("    nessa categoria. Vale conferir se isso muda como o vídeo")
            diz("    aparece no post antes de fechar o desenho.")
            diz()
        diz("    Dá para restringir ao Brasil por API. O plano automático vive.")
    elif (provas.get("tipo") == 400 and provas.get("vazio", 0) >= 500
          and provas.get("irmao2") == 200):
        # Este é o padrão mais informativo que a sondagem sabe reconhecer, e
        # aponta para um só lugar.
        diz("    O CAMPO EXISTE, É VALIDADO, E O HANDLER DELE CAI.")
        diz()
        diz("    A cadeia de evidência, toda na mesma mídia e na mesma chamada:")
        diz(f"      - alt_text                      -> 200 (o endpoint funciona)")
        diz(f"      - allow_download_status         -> {provas.get('irmao1')} (escrita de metadado funciona)")
        diz(f"      - sensitive_media_warning       -> {provas.get('irmao2')} (outro campo 'object' pelado funciona)")
        diz(f"      - geo_restrictions: \"BR\"        -> 400 'string found, object expected'")
        diz(f"      - geo_restrictions: {{}}          -> {provas.get('vazio')}")
        diz()
        diz("    O 400 no tipo errado prova que o validador CONHECE o campo e")
        diz("    exige objeto. O 5xx no objeto VAZIO prova que ele passa pela")
        diz("    validação e quebra depois, no tratamento. Não é formato: nenhum")
        diz("    valor meu poderia consertar um objeto vazio.")
        diz()
        diz("    E não é a categoria da mídia: amplify_video deu o mesmo 5xx.")
        diz()
        diz("    Duas leituras cabem, e daqui não dá para separar: ou o recurso")
        diz("    está quebrado para todo mundo, ou existe uma checagem de")
        diz("    habilitação que responde 5xx em vez de 403 para quem não tem.")
        diz("    Nos dois casos a pergunta é para o suporte do X, não para mim")
        diz("    continuar adivinhando formato.")
    elif servidor_falhou == len(FORMAS):
        diz(f"    Todas as {len(FORMAS)} tentativas voltaram erro de servidor (5xx),")
        diz("    embora o controle com alt_text tenha passado.")
        diz()
        diz("    Isso é estranho e vale repetir: pode ser que o campo exista mas")
        diz("    esteja quebrado do lado deles, ou que exija permissão que esta")
        diz("    chave não tem e o erro saia como 5xx em vez de 403.")
        diz("    NÃO concluo daqui que é impossível — 5xx não é recusa de formato.")
    else:
        diz("    O endpoint respondeu (o controle passou), e nenhum dos formatos")
        diz("    de geo_restrictions grudou.")
        diz()
        diz("    Aqui sim a conclusão se sustenta: ou nenhuma das sete formas é a")
        diz("    certa, ou o campo não está liberado para esta conta. Em qualquer")
        diz("    dos casos, a restrição teria de ser feita à mão no Media Studio,")
        diz("    e o plano de aprovar pelo celular e subir sozinho não fecha.")
    diz("=" * 72)
    diz()
    diz("Nada foi publicado. Este arquivo não chama /2/tweets em lugar nenhum.")
    return "\n".join(linhas)
