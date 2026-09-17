"""
As coletas: o que o app vai buscar sozinho, de onde, e de quanto em quanto tempo.

DE ONDE VEIO (16/09/26)
    A gente passou uma conversa inteira separando o que é ficha permanente do
    que é dado com prazo de validade. A conclusão dele foi direta:

        "pode ser uma rotina de atualização por periodo, e daí além da fonte
         você também define frequência pra ficar minimamente utilizavel. Nas
         configurações pode ficar armazenado o visto_em, e ter um botão pra
         rodar manualmente se necessário nos que forem rotineiros."

    Este arquivo é a lista. O `database.marcar_coleta` guarda quando cada uma
    rodou, e a guia de Configurações se monta a partir daqui.

POR QUE UMA LISTA SÓ, AQUI
    Mesma razão do `ajustes.py`, que já tinha aprendido isso: a tela não pode
    ter uma segunda cópia. Coleta nova é uma entrada aqui — e ela aparece na
    tela, com data e botão, sem ninguém tocar na página.

A CADÊNCIA É UMA SUGESTÃO, E ISSO É DE PROPÓSITO
    Ela não dispara nada: quem dispara é o agendador, que tem os horários
    dele, e o botão, que é ele. O que a cadência faz é dizer na tela "isto
    devia ter rodado ontem" — a informação que transforma um `visto_em` em
    aviso. Um cache sem data é indistinguível de uma resposta errada; um cache
    com data mas sem expectativa ainda deixa o leitor decidir sozinho se sete
    dias é muito.

O QUE CADA CAMPO SIGNIFICA
    chave    — o nome no banco. Nunca muda, ou a data se perde.
    nome     — o que aparece na tela.
    fonte    — de onde vem o dado. Ele perguntou isso o tempo todo, e a
               resposta estava só no código.
    cadencia — de quanto em quanto tempo faz sentido rodar.
    dias     — a mesma coisa em número, para a tela poder comparar. `0` quer
               dizer "uma vez por pessoa, não se repete".
    rota     — o endereço que roda a coleta. A tela chama este endereço.
    ajuda    — o que quebra se ela não rodar. Sem isso, a lista vira um painel
               de botões que ninguém sabe se deve apertar.
"""

COLETAS = [
    {
        "chave": "ficha_permanente",
        "nome": "Ficha permanente (altura, peso, pé, país)",
        "fonte": "SPL, Transfermarkt e API-Football",
        "cadencia": "uma vez por jogador",
        "dias": 0,
        "rota": "/api/coletas/ficha-permanente",
        "metodo": "POST",
        "ajuda": "Os campos que não mudam na vida de um jogador. Colhe só "
                 "quem ainda está sem — e NUNCA sobrescreve o que você "
                 "corrigiu à mão. O pé é o que mais importa aqui: ele só "
                 "existe no Transfermarkt, que bloqueia de vez em quando. "
                 "Depois de colhido, ele pode cair para sempre que o dado "
                 "fica.",
    },
    {
        "chave": "competicoes",
        "nome": "Calendário de todas as competições",
        "fonte": "API-Football",
        "cadencia": "diário",
        "dias": 1,
        "rota": "/api/competicoes/atualizar",
        "metodo": "GET",
        "ajuda": "Pergunta a cada clube da liga tudo que ele jogou na "
                 "temporada — Saudi Pro League, AFC, Copa do Rei, Supercopa. "
                 "Sem isto, a ficha do jogador mostra só o campeonato, e o "
                 "filtro de competição aparece com uma opção só.",
    },
    {
        "chave": "escalacoes",
        "nome": "Escalações e números jogo a jogo",
        "fonte": "API-Football",
        "cadencia": "após cada rodada",
        "dias": 3,
        "rota": "/api/escalacoes/reler",
        "metodo": "GET",
        "ajuda": "Quem entrou em cada partida, e o que fez: minutos, gols, "
                 "assistências, cartões e nota. É de onde sai a ficha do "
                 "jogador e a arte que você baixa. Roda sozinha de madrugada.",
    },
    {
        "chave": "elencos_congelados",
        "nome": "Cópia dos elencos do Transfermarkt",
        "fonte": "Transfermarkt",
        "cadencia": "a cada janela de transferências",
        "dias": 30,
        "rota": "/api/elencos/congelar",
        "metodo": "POST",
        "ajuda": "O retrato do elenco de cada clube guardado no banco. É o "
                 "que segura a guia de Elencos de pé nos dias em que o "
                 "Transfermarkt bloqueia — e foi o que faltou no dia em que "
                 "ela caiu.",
    },
    {
        "chave": "cadastro_das_fontes",
        "nome": "Cadastro das fontes (nascimento, altura, peso)",
        "fonte": "SPL e API-Football",
        "cadencia": "a cada janela de transferências",
        "dias": 30,
        "rota": "/api/jogadores/perfis",
        "metodo": "POST",
        "ajuda": "Vai ao site da liga e ao cadastro da API-Football buscar "
                 "nascimento, altura, peso, país de nascimento — e cruza os "
                 "dois pela data de nascimento, que é a única chave que não "
                 "sofre transliteração. É a coleta que ALIMENTA a ficha "
                 "permanente; depois dela, rode a de cima.",
    },

]

POR_CHAVE = {c["chave"]: c for c in COLETAS}


def com_datas(feitas: dict) -> list[dict]:
    """A lista com a data da última vez e o veredito de cada uma.

    `feitas` vem do `database.coletas_feitas()`. O veredito é uma palavra:

        nunca     — não rodou uma vez sequer
        erro      — rodou e falhou; é diferente de nunca ter rodado
        atrasada  — passou da cadência
        ok        — em dia
        uma_vez   — das que não se repetem, e já rodou

    Sai daqui e não da tela porque "atrasada" é uma comparação de datas, e
    conta de data no navegador é onde o fuso entra sem ser convidado.
    """
    from datetime import datetime, timezone
    agora = datetime.now(timezone.utc)
    saida = []
    for c in COLETAS:
        feita = feitas.get(c["chave"]) or {}
        quando = feita.get("ultima_em")
        idade = None
        if quando:
            try:
                d = datetime.fromisoformat(quando)
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                idade = (agora - d).total_seconds() / 86400.0
            except ValueError:
                idade = None
        if not quando:
            estado = "nunca"
        elif feita.get("erro"):
            estado = "erro"
        elif not c["dias"]:
            estado = "uma_vez"
        elif idade is not None and idade > c["dias"]:
            estado = "atrasada"
        else:
            estado = "ok"
        saida.append({**c, "ultima_em": quando, "dias_atras": idade,
                      "resultado": feita.get("resultado") or "",
                      "erro": feita.get("erro") or "", "estado": estado})
    return saida
