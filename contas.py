"""
Contas: guardar senha sem guardar senha, e saber quem está do outro lado.

COMO A SENHA É GUARDADA
    Nunca em texto. O que fica no banco é o resultado de um scrypt — uma
    função feita para ser LENTA de propósito, para que tentar milhões de
    senhas por segundo deixe de ser barato.

    Uso o scrypt da biblioteca padrão do Python, e não bcrypt ou argon2, por
    um motivo prático: dependência nova é mais uma coisa para instalar, para
    quebrar no deploy e para atualizar. O scrypt já vem com o Python e é
    adequado para isto.

    Cada senha tem um "sal" próprio, sorteado na hora. Sem sal, duas pessoas
    com a mesma senha teriam o mesmo registro no banco — e quem visse o banco
    saberia disso.

COMO A SESSÃO FUNCIONA
    Um cookie assinado. Ele carrega o e-mail e a validade, e uma assinatura
    HMAC que só este servidor sabe fazer. Não dá para editar o cookie e virar
    outra pessoa: a assinatura deixa de bater.

    A comparação da assinatura usa compare_digest, e não ==, porque comparar
    com == vaza informação pelo TEMPO que a comparação leva.

QUEM PODE CRIAR CONTA
    Só quem estiver na lista EMAILS_LIBERADOS. Sem essa variável configurada,
    NINGUÉM cria conta — nem por engano, nem por acaso. É um app aberto na
    internet que decide o que sai no X de alguém; cadastro livre aqui seria
    entregar a chave na porta.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

# Custo do scrypt. n=2**14 leva uns 50 ms numa máquina comum — imperceptível
# para quem entra uma vez, caríssimo para quem quer testar um dicionário.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
TAMANHO_SAL = 16
TAMANHO_HASH = 32

DIAS_DE_SESSAO = 30
COOKIE = "iar_sessao"

SENHA_MINIMA = 8


def _segredo() -> bytes:
    """A chave que assina as sessões.

    Se SESSAO_SECRETA não estiver configurada, invento uma na subida. Funciona,
    mas toda vez que o app reinicia todo mundo é deslogado — porque a chave
    mudou e as assinaturas antigas deixam de valer. A tela de configurações
    avisa quando é o caso, em vez de deixar você achando que é bug.
    """
    s = os.environ.get("SESSAO_SECRETA", "").strip()
    if s:
        return s.encode()
    global _SEGREDO_TEMPORARIO
    try:
        return _SEGREDO_TEMPORARIO
    except NameError:
        _SEGREDO_TEMPORARIO = secrets.token_bytes(32)
        return _SEGREDO_TEMPORARIO


def segredo_configurado() -> bool:
    return bool(os.environ.get("SESSAO_SECRETA", "").strip())


def emails_liberados() -> list[str]:
    bruto = os.environ.get("EMAILS_LIBERADOS", "")
    return [e.strip().lower() for e in bruto.replace(";", ",").split(",") if e.strip()]


def pode_criar_conta(email: str) -> bool:
    return normalizar_email(email) in emails_liberados()


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def primeiro_nome(email: str, nome: str = "") -> str:
    """O nome para a saudação. Sem nome, uso o começo do e-mail."""
    if nome and nome.strip():
        return nome.strip().split()[0].capitalize()
    pedaco = normalizar_email(email).split("@")[0]
    pedaco = pedaco.replace(".", " ").replace("_", " ").replace("-", " ")
    return (pedaco.split() or ["você"])[0].capitalize()


# ── senha ─────────────────────────────────────────────────────────────────
def guardar_senha(senha: str) -> str:
    sal = secrets.token_bytes(TAMANHO_SAL)
    bruto = hashlib.scrypt(senha.encode(), salt=sal, n=SCRYPT_N, r=SCRYPT_R,
                           p=SCRYPT_P, dklen=TAMANHO_HASH)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(sal).decode(), base64.b64encode(bruto).decode())


def senha_confere(senha: str, guardada: str) -> bool:
    """Nunca levanta: senha errada e registro corrompido dão o mesmo False."""
    try:
        marca, n, r, p, sal_b64, hash_b64 = (guardada or "").split("$")
        if marca != "scrypt":
            return False
        bruto = hashlib.scrypt(senha.encode(), salt=base64.b64decode(sal_b64),
                               n=int(n), r=int(r), p=int(p),
                               dklen=len(base64.b64decode(hash_b64)))
        return hmac.compare_digest(bruto, base64.b64decode(hash_b64))
    except Exception:
        return False


def senha_fraca(senha: str) -> str:
    """Devolve o motivo, ou "" se serve. Uma regra só, e clara."""
    if len(senha or "") < SENHA_MINIMA:
        return f"a senha precisa ter pelo menos {SENHA_MINIMA} caracteres"
    return ""


def senha_temporaria() -> str:
    """Uma senha que dá para ditar no telefone sem soletrar."""
    return secrets.token_urlsafe(9)


# ── sessão ────────────────────────────────────────────────────────────────
def criar_sessao(email: str) -> str:
    corpo = json.dumps({"e": normalizar_email(email),
                        "v": int(time.time()) + DIAS_DE_SESSAO * 86400},
                       separators=(",", ":")).encode()
    dados = base64.urlsafe_b64encode(corpo).decode().rstrip("=")
    assinatura = hmac.new(_segredo(), dados.encode(), hashlib.sha256).hexdigest()
    return f"{dados}.{assinatura}"


def ler_sessao(cookie: str) -> str:
    """O e-mail de quem está logado, ou "" se o cookie não vale."""
    try:
        dados, assinatura = (cookie or "").rsplit(".", 1)
    except ValueError:
        return ""
    esperada = hmac.new(_segredo(), dados.encode(), hashlib.sha256).hexdigest()
    # compare_digest, e não ==: comparar com == devolve a resposta mais rápido
    # quando os primeiros caracteres já diferem, e isso é o bastante para
    # alguém descobrir a assinatura tentativa por tentativa.
    if not hmac.compare_digest(esperada, assinatura):
        return ""
    try:
        falta = len(dados) % 4
        corpo = json.loads(base64.urlsafe_b64decode(dados + "=" * (4 - falta if falta else 0)))
    except Exception:
        return ""
    if int(corpo.get("v", 0)) < time.time():
        return ""
    return normalizar_email(corpo.get("e", ""))
