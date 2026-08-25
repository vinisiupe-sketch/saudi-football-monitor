"""
Publicação de story no Instagram.

COMO FUNCIONA, EM TRÊS PASSOS
    1. Crio um "container" mandando a URL do vídeo — o Instagram vai BUSCAR o
       arquivo no seu servidor, você não envia bytes para ele.
    2. Espero ele processar. Vídeo é assíncrono lá: receber o id do container
       não quer dizer que deu certo.
    3. Publico o container.

    Por isso a URL do clipe precisa estar acessível de fora. A rota
    /api/clipe/{id}/video já é aberta — é dela que o Instagram puxa.

O QUE PRECISA ESTAR CONFIGURADO NO RAILWAY
    IG_USER_ID        — o id da conta profissional
    IG_ACCESS_TOKEN   — token de usuário com permissão de publicar
    IG_HOST           — opcional; graph.instagram.com (padrão) para o login
                        pelo Instagram, graph.facebook.com para o login pelo
                        Facebook

    A conta tem que ser profissional (comercial ou de criador). Conta pessoal
    não publica por API, e o erro que ela devolve não diz isso com clareza.

SOBRE DIREITOS
    Story do Instagram NÃO tem restrição por país. Diferente do X, não existe
    um Media Studio para entrar depois e limitar ao Brasil. Isso está dito na
    tela, ao lado do botão, porque é decisão sua a cada clipe e não é o tipo de
    coisa que deva ficar só na cabeça de quem escreveu o código.

O QUE ESTE ARQUIVO NÃO FAZ
    Não publica sozinho. Só publica quando a rota é chamada, e a rota só é
    chamada quando você aperta o botão e confirma.
"""
import os
import asyncio

import httpx

VERSAO_API = "v25.0"

# Limites do story, conferidos na referência da Meta (IG User Media).
# Confiro ANTES de mandar: o erro deles para arquivo fora de especificação é
# genérico, e descobrir isso no meio de um jogo custa caro.
DURACAO_MIN_SEG = 3
DURACAO_MAX_SEG = 60
TAMANHO_MAX_BYTES = 100 * 1024 * 1024

# O Instagram processa o vídeo antes de liberar. A documentação sugere olhar
# uma vez por minuto por até cinco minutos; olho mais de perto porque aqui o
# jogo está correndo, mas mantenho o teto de tempo.
ESPERA_SEG = 3
MAX_ESPERAS = 100


class InstagramErro(RuntimeError):
    pass


def credenciais() -> dict:
    return {
        "ig_user_id": os.environ.get("IG_USER_ID", "").strip(),
        "ig_access_token": os.environ.get("IG_ACCESS_TOKEN", "").strip(),
    }


def host() -> str:
    return os.environ.get("IG_HOST", "").strip() or "graph.instagram.com"


def configurado() -> tuple[bool, list[str]]:
    """Diz se dá para publicar, sem NUNCA devolver o valor das chaves."""
    c = credenciais()
    return (all(c.values()), [k for k, v in c.items() if not v])


def _erro_legivel(r) -> str:
    """A mensagem da Meta vem enterrada; trago ela para a superfície."""
    try:
        e = (r.json() or {}).get("error") or {}
    except Exception:
        e = {}
    partes = [str(e.get("message") or "")[:200]]
    if e.get("error_user_msg"):
        partes.append(str(e["error_user_msg"])[:200])
    if e.get("code"):
        partes.append(f"código {e['code']}")
    texto = " · ".join(p for p in partes if p)
    return texto or f"HTTP {r.status_code}: {r.text[:200]}"


def conferir_video(tamanho_bytes: int, duracao_seg: float | None) -> str:
    """Devolve o motivo da recusa, ou "" se o vídeo serve para story."""
    if tamanho_bytes > TAMANHO_MAX_BYTES:
        return (f"o vídeo tem {tamanho_bytes/1048576:.1f} MB e o teto do story "
                f"é {TAMANHO_MAX_BYTES//1048576} MB")
    if duracao_seg is None:
        return ""          # não medi; deixo o Instagram decidir
    if duracao_seg > DURACAO_MAX_SEG:
        return (f"o clipe tem {duracao_seg:.0f}s e o story aceita no máximo "
                f"{DURACAO_MAX_SEG}s")
    if duracao_seg < DURACAO_MIN_SEG:
        return (f"o clipe tem {duracao_seg:.0f}s e o story exige pelo menos "
                f"{DURACAO_MIN_SEG}s")
    return ""


async def diagnostico() -> list[str]:
    """Diz, em português, por que a publicação está falhando.

    "Algo de autenticação" pode ser cinco coisas diferentes: conta pessoal em
    vez de profissional, token vencido, token do tipo errado para o host, id
    que não é o da conta, ou permissão que não foi concedida. Cada uma tem um
    conserto diferente, e a mensagem crua da Meta não separa. Aqui eu pergunto
    para eles e traduzo.

    Nunca imprime o valor do token — só o tamanho e os quatro últimos
    caracteres, que bastam para você conferir se colou o certo.
    """
    linhas = []
    c = credenciais()
    tok = c["ig_access_token"]
    linhas.append(f"host          : {host()}")
    linhas.append(f"IG_USER_ID    : {c['ig_user_id'] or 'AUSENTE'}")
    linhas.append("IG_ACCESS_TOKEN: " + (
        f"{len(tok)} caracteres, terminando em …{tok[-4:]}" if tok else "AUSENTE"))
    if not all(c.values()):
        linhas.append("")
        linhas.append("Falta variável no Railway. Sem isso nem dá para perguntar.")
        return linhas

    async with httpx.AsyncClient(timeout=30.0) as cli:
        linhas.append("")
        linhas.append("— a conta —")
        r = await cli.get(f"https://{host()}/{VERSAO_API}/{c['ig_user_id']}",
                          params={"fields": "id,username,account_type",
                                  "access_token": tok})
        if r.status_code >= 300:
            linhas.append(f"  NÃO CONSEGUI LER: {_erro_legivel(r)}")
            linhas.append("")
            linhas.append("  Os suspeitos, em ordem:")
            linhas.append("   1. o token venceu (os curtos duram 1 hora)")
            linhas.append("   2. o host não combina com o tipo de token —")
            linhas.append("      graph.instagram.com quer token do Login pelo")
            linhas.append("      Instagram; graph.facebook.com quer token de")
            linhas.append("      Página. Trocar o IG_HOST resolve esse caso.")
            linhas.append("   3. o IG_USER_ID não é o id dessa conta")
            linhas.append("   4. a permissão de publicar não foi concedida")
        else:
            d = r.json() or {}
            linhas.append(f"  usuário : @{d.get('username') or '?'}")
            tipo = d.get("account_type") or "?"
            linhas.append(f"  tipo    : {tipo}")
            if tipo not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
                linhas.append("  ⚠️  conta pessoal NÃO publica por API. Tem que")
                linhas.append("      ser comercial ou de criador.")

        linhas.append("")
        linhas.append("— quanto já publiquei hoje —")
        r = await cli.get(
            f"https://{host()}/{VERSAO_API}/{c['ig_user_id']}/content_publishing_limit",
            params={"fields": "quota_usage,config", "access_token": tok})
        if r.status_code >= 300:
            linhas.append(f"  não consegui ler: {_erro_legivel(r)}")
        else:
            dados = ((r.json() or {}).get("data") or [{}])[0]
            linhas.append(f"  {dados.get('quota_usage', '?')} de "
                          f"{(dados.get('config') or {}).get('quota_total', '?')}")
    return linhas


async def publicar_story(video_url: str, on_status=None) -> str:
    """Publica o vídeo como story e devolve o id. Levanta InstagramErro."""
    ok, faltando = configurado()
    if not ok:
        raise InstagramErro("faltam variáveis no Railway: " + ", ".join(faltando))
    if not video_url.lower().startswith("https://"):
        # Eles buscam o arquivo de fora. Sem https a busca falha, e o erro que
        # volta fala de "media", não de esquema — daria meia hora de caça.
        raise InstagramErro(f"a URL do vídeo precisa ser https, e veio: {video_url[:80]}")

    c = credenciais()
    base = f"https://{host()}/{VERSAO_API}/{c['ig_user_id']}"
    token = c["ig_access_token"]

    def avisa(t: str) -> None:
        if on_status:
            on_status(t)

    async with httpx.AsyncClient(timeout=120.0) as cli:
        avisa("criando o story…")
        r = await cli.post(f"{base}/media", data={
            "media_type": "STORIES", "video_url": video_url,
            "access_token": token})
        if r.status_code >= 300:
            raise InstagramErro("o Instagram recusou o vídeo: " + _erro_legivel(r))
        container = str((r.json() or {}).get("id") or "")
        if not container:
            raise InstagramErro(f"resposta sem id do container: {r.text[:200]}")

        # Vídeo é assíncrono: ter o container não quer dizer que deu certo.
        # Publicar sem esperar dá erro, então espero de verdade.
        estado = ""
        for tentativa in range(MAX_ESPERAS):
            await asyncio.sleep(ESPERA_SEG)
            r = await cli.get(f"https://{host()}/{VERSAO_API}/{container}",
                              params={"fields": "status_code,status",
                                      "access_token": token})
            if r.status_code >= 300:
                raise InstagramErro("não consegui ver o andamento: " + _erro_legivel(r))
            corpo = r.json() or {}
            estado = corpo.get("status_code") or ""
            if estado == "FINISHED":
                break
            if estado in ("ERROR", "EXPIRED"):
                detalhe = str(corpo.get("status") or "")[:200]
                raise InstagramErro(f"o Instagram não aceitou o vídeo ({estado})"
                                    + (f": {detalhe}" if detalhe else ""))
            avisa(f"o Instagram está processando… ({estado or 'sem resposta'})")
        else:
            raise InstagramErro(
                f"o Instagram não terminou de processar depois de "
                f"{MAX_ESPERAS * ESPERA_SEG}s; último estado: {estado or 'nenhum'}")

        avisa("publicando…")
        r = await cli.post(f"{base}/media_publish",
                           data={"creation_id": container, "access_token": token})
        if r.status_code >= 300:
            raise InstagramErro("falhou na hora de publicar: " + _erro_legivel(r))
        story = str((r.json() or {}).get("id") or "")
        if not story:
            raise InstagramErro(f"publicou mas não devolveu id: {r.text[:200]}")
    return story
