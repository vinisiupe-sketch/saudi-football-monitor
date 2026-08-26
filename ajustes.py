"""
Os números que você pode mexer sem eu precisar mexer em código.

POR QUE ISTO EXISTE
    Olhando o que mudou nas últimas semanas — janela do clipe de 10/5 para
    20/8 e depois 12/10, atraso da transmissão de 26 para 15, passo dos botões
    de 5 para 8 — quase nada disso era estrutura. Era ajuste. E cada um custou
    um commit, um deploy e, quando o gravador estava em outra máquina, alguém
    do outro lado atualizando arquivo.

    Aqui esses números viram configuração. Você muda na tela, o app obedece na
    hora, e o gravador pega na próxima consulta. Ninguém atualiza nada.

COMO ACRESCENTAR UM AJUSTE NOVO
    Põe uma linha em AJUSTES com chave, rótulo e o que ele significa. A tela
    se monta sozinha a partir daqui — não há uma segunda lista para esquecer
    de atualizar, que é como listas paralelas costumam apodrecer.

    O campo 'ajuda' não é enfeite. Daqui a três meses, "reacao_seg = 4" não vai
    dizer nada a ninguém, nem a mim. A frase que explica o que o número faz é
    parte do ajuste.

SOBRE OS GRUPOS
    Hoje só há ajustes de clipe e de gravador. A tela agrupa por 'grupo', então
    quando as outras guias tiverem o que configurar, é só usar um grupo novo e
    elas aparecem lá sem tocar na página.
"""

# tipo: "int" | "texto" | "escolha"
AJUSTES = [
    # ── Clipes: a janela ──────────────────────────────────────────────────
    {
        "chave": "clipe_atraso_transmissao",
        "grupo": "Clipe — o instante do lance",
        "rotulo": "Atraso da transmissão",
        "unidade": "s",
        "tipo": "int", "min": 0, "max": 120, "padrao": 26,
        "ajuda": "Quantos segundos a live do canal está ATRÁS do que você está "
                 "assistindo quando aperta o botão. Se o clipe pega a jogada "
                 "antes do gol, aumente. Se já entra com a comemoração "
                 "começada, diminua. É o ajuste que mais importa.",
    },
    {
        "chave": "clipe_reacao_seg",
        "grupo": "Clipe — o instante do lance",
        "rotulo": "Seu tempo de reação",
        "unidade": "s",
        "tipo": "int", "min": 0, "max": 30, "padrao": 4,
        "ajuda": "Quanto tempo passa entre você VER o lance e conseguir apertar "
                 "o botão. Descontado do instante do clipe.",
    },
    {
        "chave": "clipe_antes_seg",
        "grupo": "Clipe — o instante do lance",
        "rotulo": "Segundos antes do lance",
        "unidade": "s",
        "tipo": "int", "min": 3, "max": 90, "padrao": 12,
        "ajuda": "Quanto o clipe começa antes do lance. Serve para pegar a "
                 "construção da jogada, não só a bola entrando.",
    },
    {
        "chave": "clipe_depois_seg",
        "grupo": "Clipe — o instante do lance",
        "rotulo": "Segundos depois do lance",
        "unidade": "s",
        "tipo": "int", "min": 1, "max": 90, "padrao": 10,
        "ajuda": "Quanto o clipe continua depois do lance. Pega a comemoração.",
    },
    {
        "chave": "clipe_passo_ajuste",
        "grupo": "Clipe — o instante do lance",
        "rotulo": "Passo dos botões de ajuste",
        "unidade": "s",
        "tipo": "int", "min": 1, "max": 30, "padrao": 8,
        "ajuda": "De quanto em quanto os botões ◀ e ▶ movem a janela do clipe.",
    },

    # ── Clipes: o que fica e o que some ───────────────────────────────────
    {
        "chave": "clipe_horas_descarte",
        "grupo": "Clipe — o que fica guardado",
        "rotulo": "Descartar depois de",
        "unidade": "h",
        "tipo": "int", "min": 1, "max": 72, "padrao": 2,
        "ajuda": "Clipe sem estrela é apagado este tanto de horas depois que o "
                 "jogo sai do ar. Os marcados com ★ nunca são tocados.",
    },
    {
        "chave": "gravador_horas_gravacao",
        "grupo": "Clipe — o que fica guardado",
        "rotulo": "Apagar gravações da máquina depois de",
        "unidade": "h",
        "tipo": "int", "min": 2, "max": 168, "padrao": 12,
        "ajuda": "Cada partida gravada ocupa ~1,6 GB no computador que grava. "
                 "Passado este tempo, o arquivo bruto é apagado de lá. Não "
                 "afeta os clipes já cortados.",
    },

    # ── Gravador ──────────────────────────────────────────────────────────
    {
        "chave": "gravador_altura_max",
        "grupo": "Gravador",
        "rotulo": "Qualidade máxima da captura",
        "unidade": "p",
        "tipo": "int", "min": 360, "max": 1080, "padrao": 720,
        "ajuda": "Altura da imagem capturada. 720 gasta ~1,8 Mbps por jogo. "
                 "Subir para 1080 melhora a imagem e quase dobra a banda e o "
                 "disco — pense na internet de quem está gravando.",
    },
    {
        "chave": "gravador_preset",
        "grupo": "Gravador",
        "rotulo": "Velocidade do corte",
        "tipo": "escolha",
        "opcoes": ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"],
        "padrao": "veryfast",
        "ajuda": "Mais rápido corta antes e comprime pior. Medi na sua "
                 "gravação: 'veryfast' cortou em 13s contra 34s do 'medium', "
                 "com semelhança de 0,992 — diferença que ninguém vê num clipe "
                 "curto. Só desça daqui se a máquina que grava for lenta.",
    },
    {
        "chave": "gravador_decodifica_antes",
        "grupo": "Gravador",
        "rotulo": "Decodificar antes do corte",
        "unidade": "s",
        "tipo": "int", "min": 5, "max": 120, "padrao": 30,
        "ajuda": "Quanto o ffmpeg lê ANTES do ponto do corte para chegar nele "
                 "com imagem. Baixar demais faz o clipe abrir em preto; subir "
                 "demais deixa o corte lento. Só mexa se aparecerem clipes "
                 "começando escuros.",
    },
    {
        "chave": "gravador_intervalo_canal",
        "grupo": "Gravador",
        "rotulo": "Olhar o canal a cada",
        "unidade": "s",
        "tipo": "int", "min": 30, "max": 600, "padrao": 90,
        "ajuda": "De quanto em quanto tempo a máquina que grava pergunta ao "
                 "YouTube o que está no ar no canal do parceiro.",
    },
]

POR_CHAVE = {a["chave"]: a for a in AJUSTES}


def grupos() -> list[str]:
    """Os grupos na ordem em que aparecem na lista, sem repetir."""
    vistos = []
    for a in AJUSTES:
        if a["grupo"] not in vistos:
            vistos.append(a["grupo"])
    return vistos


def limpar(chave: str, valor):
    """Devolve o valor válido para esta chave, ou None se não serve.

    Nunca levanta: valor que não serve vira None e quem chama usa o padrão.
    Deixar um número fora da faixa entrar aqui significaria, por exemplo, uma
    janela de clipe de zero segundo — e o defeito só apareceria no meio do
    jogo, que é o pior lugar para descobrir qualquer coisa.
    """
    a = POR_CHAVE.get(chave)
    if not a:
        return None
    if a["tipo"] == "int":
        try:
            v = int(round(float(valor)))
        except Exception:
            return None
        return max(a["min"], min(a["max"], v))
    if a["tipo"] == "escolha":
        v = str(valor).strip()
        return v if v in a["opcoes"] else None
    v = str(valor).strip()
    return v or None
