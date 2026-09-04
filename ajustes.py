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

    # ── Clipe automático (pelo alerta de gol) ──────────────────────────────
    # O gol é detectado pelo alerta da API-Football, o mesmo que já preenche a
    # legenda. Ele chega DEPOIS do lance — por isso a janela aqui é mais larga
    # que a do botão: melhor sobrar vídeo, que a fita de corte resolve, do que
    # faltar o lance, que não tem conserto.
    {
        "chave": "clipe_auto_ligado",
        "grupo": "Clipe automático (pelo alerta de gol)",
        "rotulo": "Pedir clipe sozinho quando sair gol",
        "tipo": "escolha",
        "opcoes": ["ligado", "desligado"],
        "padrao": "ligado",
        "ajuda": "Só vale para jogo que está sendo gravado E que a API "
                 "reconheceu. O botão GOL AGORA continua igual, e o clipe "
                 "automático aparece marcado com ⚡ na lista.",
    },
    {
        "chave": "clipe_auto_atraso_alerta_seg",
        "grupo": "Clipe automático (pelo alerta de gol)",
        "rotulo": "Atraso do alerta de gol",
        "unidade": "s",
        "tipo": "int", "min": 0, "max": 180, "padrao": 45,
        "ajuda": "Quanto tempo passa entre a bola entrar e o alerta chegar "
                 "aqui. O coletor passa de 45 em 45 segundos e o provedor "
                 "leva o dele. Se os clipes automáticos estiverem pegando o "
                 "lance tarde demais, aumente.",
    },
    {
        "chave": "clipe_auto_antes_seg",
        "grupo": "Clipe automático (pelo alerta de gol)",
        "rotulo": "Segundos antes (automático)",
        "unidade": "s",
        "tipo": "int", "min": 3, "max": 90, "padrao": 20,
        "ajuda": "Maior que a do botão de propósito: o instante do gol aqui é "
                 "estimado, não apontado por você.",
    },
    {
        "chave": "clipe_auto_depois_seg",
        "grupo": "Clipe automático (pelo alerta de gol)",
        "rotulo": "Segundos depois (automático)",
        "unidade": "s",
        "tipo": "int", "min": 1, "max": 90, "padrao": 20,
        "ajuda": "Idem: sobra de vídeo se resolve na fita de corte; falta de "
                 "vídeo, não.",
    },

    # ── Clipe automático (lê o placar do vídeo) ─────────────────────────────
    # Em teste desde 01/09/26: a máquina que grava lê o gráfico do placar
    # direto do vídeo, sem depender de nenhuma API, e pede um clipe sozinha
    # quando o número muda. O botão GOL AGORA continua funcionando igual —
    # isto roda em paralelo, não substitui.
    {
        "chave": "gravador_placar_ativo",
        "grupo": "Clipe automático (lê o placar do vídeo)",
        "rotulo": "Detectar gol pelo placar do vídeo",
        "tipo": "escolha",
        "opcoes": ["ligado", "desligado"],
        "padrao": "desligado",
        "ajuda": "DESLIGADO desde 03/09/26. A leitura olhava uma posição fixa "
                 "da tela, e a transmissão move o placar: quando entra o "
                 "letreiro em L da casa de apostas, a imagem encolhe e o "
                 "placar sai de baixo do recorte — o que estava sendo lido "
                 "virava grama, e cada troca de câmera parecia um gol. Quem "
                 "detecta gol agora é o alerta da API-Football.",
    },
    {
        "chave": "gravador_atraso_placar_seg",
        "grupo": "Clipe automático (lê o placar do vídeo)",
        "rotulo": "Atraso do gráfico do placar",
        "unidade": "s",
        "tipo": "int", "min": 0, "max": 30, "padrao": 8,
        "ajuda": "Quantos segundos o número do placar demora para mudar na "
                 "tela DEPOIS do gol de verdade — é um atraso da produção do "
                 "gráfico, medido dentro do próprio vídeo, e não tem relação "
                 "com o atraso da transmissão até você. Descontado do instante "
                 "do clipe, do mesmo jeito que o tempo de reação é descontado "
                 "no botão manual.",
    },
    # ── Arbitragem ────────────────────────────────────────────────────────
    {
        "chave": "arbitragem_cabecalho",
        "grupo": "Arbitragem",
        "rotulo": "Primeira linha do texto",
        "tipo": "texto",
        "padrao": "👨‍⚖️ 𝐀𝐑𝐁𝐈𝐓𝐑𝐀𝐆𝐄𝐌 𝐃𝐎 𝐃𝐈𝐀",
        "ajuda": "Este padrão eu reconstruí olhando um print seu — o emoji "
                 "estava pequeno demais para eu ter certeza de qual era. Se "
                 "não for esse, cole aqui a linha exata do seu post e ela "
                 "passa a valer.",
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
