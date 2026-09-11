"""
Filtro por clube na guia Lesões, e a sub-aba que confere na API.

POR QUE A SUB-ABA EXISTE
    O monitor de lesões lê NOTÍCIA. Ele é bom no que a imprensa cobre — o
    titular do Al-Hilal que rompeu o ligamento sai em todo lugar — e cego no
    que ela não cobre: o reserva do Al-Fayha que ninguém noticiou não existe
    para ele. A API-Football vê a lista oficial de ausentes, sem passar pelo
    interesse editorial de ninguém.

    Nenhuma das duas manda na outra, então a tela mostra as duas e marca a
    diferença. Fonte que discorda da outra é informação, não defeito.

A ARMADILHA QUE ESTE ARQUIVO VIGIA DE PERTO
    A API-Football só devolve ausências onde `coverage.injuries` é verdadeiro.
    Se a liga saudita não estiver coberta, a chamada volta com sucesso e lista
    VAZIA. Na tela, "a API não cobre isto" e "ninguém está machucado" seriam a
    mesma tela em branco — e a segunda leitura é a que o Vini faria, porque é
    a que faz sentido numa guia de lesões. Publicar uma escalação confiando
    nisso é o estrago.

    Por isso a rota devolve `cobertura` e a tela diz qual dos dois casos é.
"""
import ast
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

FONTE = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)


def _corpo(nome_da_funcao: str) -> str:
    """O código-fonte de uma função só, para não varrer o main.py inteiro."""
    mod = ast.parse(FONTE)
    for n in ast.walk(mod):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name == nome_da_funcao:
            return ast.get_source_segment(FONTE, n) or ""
    return ""


def testar():
    falhas.clear()
    tela = _corpo("_page_lesoes_impl")
    rota = _corpo("api_ausencias_af")

    ok(tela, "sumiu a função que monta a guia Lesões")
    ok(rota, "sumiu a rota que consulta as ausências na API-Football")

    # ── 1. o filtro por clube ────────────────────────────────────────────
    ok('data-clube="' in tela,
       "o card de lesão perdeu o data-clube — é por ele que o filtro esconde "
       "e mostra")
    ok("_html.escape(club" in tela,
       "o nome do clube entra no atributo sem escapar. Ele vem de notícia "
       "raspada: um nome com aspas fecha o atributo cedo e quebra o card")
    ok('id="filtroClube"' in tela and "filtrarPorClube()" in tela,
       "sumiu o seletor de clube da guia Lesões")
    ok("opcoes_clube" in tela,
       "as opções do filtro deixaram de ser montadas no servidor")
    # A lista sai das lesões que ESTÃO na tela. Clube sem ninguém machucado
    # como opção é uma opção que só devolve tela vazia.
    ok("for i in injuries" in tela and 'i.get("club")' in tela,
       "a lista de clubes do filtro não vem mais das lesões carregadas")
    ok("contaAtivas" in tela and "conta.textContent" in tela,
       "a contagem ao lado do título não acompanha mais o filtro — a tela "
       "mostraria três cards com o título dizendo 'Ativas (37)'")
    # Os DOIS lados: criar o recado e reencontrá-lo na volta seguinte. Sem o
    # querySelector, cada troca de clube empilharia um recado novo; sem a
    # criação, não há recado nenhum. A primeira versão deste teste só
    # procurava o nome da classe, e passava com o querySelector arrancado —
    # porque o nome continuava escrito na linha que cria o elemento.
    ok("querySelector('.lsn-filtro-vazio')" in tela,
       "o filtro parou de reencontrar o recado de seção vazia — cada troca "
       "de clube passa a empilhar um recado novo embaixo do anterior")
    ok("'empty-state lsn-filtro-vazio'" in tela,
       "sumiu a criação do recado de seção vazia: filtrar por um clube sem "
       "ninguém machucado devolveria um branco com cara de tela quebrada")

    # ── 2. UMA LISTA SÓ, sem sub-aba ─────────────────────────────────────
    # O Transfermarkt chegou como sub-aba e o Vini cortou: "Transfermarkt é
    # mais uma fonte, então tome o TM como uma fonte que apareceria no
    # histórico". Ele tem razão. Sub-aba diz "isto é outra coisa"; o TM não é
    # outra coisa, é a mesma coisa sabida por outro caminho — e separá-lo
    # obrigava a olhar duas telas para responder uma pergunta só.
    # Procuro o USO (a classe emitida no HTML e a função que troca de painel),
    # e não a palavra: o comentário que explica por que as sub-abas saíram
    # cita o nome delas, e a primeira versão deste teste falhava na própria
    # documentação. Já aconteceu quatro vezes neste projeto.
    ok('class="lsn-abas"' not in tela and "mostrarLesoes(" not in tela,
       "voltaram as sub-abas na guia Lesões. O Transfermarkt é mais uma "
       "fonte da MESMA lista, não uma tela paralela")
    # A CHAMADA, e não a menção. Comentar a linha deixa o nome no arquivo, e
    # a primeira versão deste teste passava com a junção desligada.
    ok("\njuntarTransfermarkt();" in tela,
       "sumiu a CHAMADA que junta o Transfermarkt à lista principal — o "
       "nome da função pode estar aí e ela nunca rodar")
    # O TM entra como TAG e como item do HISTÓRICO, não como linha no meio do
    # card. "Transfermarkt é mais uma fonte" — fonte que confirma não precisa
    # engordar a lista; precisa ser rastreável.
    # Outra vez a chamada, e não o nome: comentar `marcarTM(card, a);` deixa
    # a função definida e o card sem tag nenhuma.
    # Com a quebra de linha e o recuo exatos: comentar a linha insere "// "
    # depois do recuo, e aí o trecho procurado deixa de casar. Sem isso, o
    # teste passava com a chamada comentada.
    ok("\n    marcarTM(card, a);" in tela
       and "\n      marcarTM(card, a, true);" in tela,
       "sumiu a CHAMADA que marca o card com a tag do Transfermarkt — nos "
       "dois casos: no card que já existia e no que só o TM conhece")
    ok("card.className = 'injury-card status-lesionado';" in tela,
       "o card que só o Transfermarkt conhece perdeu a moldura de estado. "
       "Ele fica visualmente diferente dos outros, como se fosse outra coisa "
       "— e não é: é a mesma lista")
    ok("lsn-tag-tm" in tela,
       "sumiu a tag (TM) — sem ela não dá para saber qual fonte disse o quê")
    # E entra DENTRO do histórico que já existe, não numa gaveta própria:
    # duas gavetas no mesmo card obrigam a abrir as duas para saber o que se
    # sabe sobre o jogador, e a pergunta é uma só.
    ok("extra.querySelector('.injury-timeline')" in tela,
       "o Transfermarkt parou de procurar o histórico que já existe no card "
       "— ele volta a criar uma gaveta só dele")
    ok("linha.insertBefore(item, linha.firstChild)" in tela,
       "a entrada do Transfermarkt deixou de ser inserida na linha do tempo")
    # O link tem que estar no ÂNCORA emitida, e não só na variável: trocar o
    # <a> por um <span> deixava o endereço montado e nunca clicável.
    ok("+ '<a href=\"' + link + '\"" in tela
       and "transfermarkt.com/-/profil/spieler/" in tela,
       "a entrada do Transfermarkt perdeu o link para a página do jogador — "
       "sem ele, a fonte não dá para conferir")
    # E quem só o TM conhece entra na MESMA lista, sem seção própria: a tag
    # já diz de onde veio, e uma segunda seção era redundância.
    ok("Só no Transfermarkt" not in tela,
       "voltou a seção separada 'Só no Transfermarkt'. A tag (TM) já diz a "
       "origem, e uma lista só é o que responde 'quem do meu time está fora'")
    ok("grade.appendChild(card)" in tela,
       "quem só o Transfermarkt conhece deixou de entrar na lista principal")

    # ── 3. a fonte é o TM, não a API ─────────────────────────────────────
    # A API-Football NÃO cobre ausências nesta liga (coverage.injuries =
    # false, conferido com a chave do Vini). Ela respondia com SUCESSO e lista
    # VAZIA, para sempre — foi isso que ele relatou como "não tá trazendo
    # nada". Uma fonte que só sabe dizer "nada" não confere coisa nenhuma.
    ok("/api/lesoes/transfermarkt" in tela,
       "a guia voltou a consultar a API-Football, que não cobre ausências "
       "nesta liga e sempre devolve lista vazia")
    # A rota da API continua existindo — ela volta a servir no dia em que a
    # cobertura aparecer, e apagá-la agora seria jogar fora a conferência do
    # coverage junto.
    ok("coverage" in rota,
       "a rota antiga perdeu a conferência do coverage.injuries, que é o que "
       "distingue 'a API não sabe' de 'ninguém está fora'")
    ok("NÃO quer dizer" in tela,
       "sumiu o aviso de que lista vazia pode ser falha de leitura, e não "
       "ausência de lesionados")

    # ── 3b. o escudo vem da LIGA, não da tabela de transferências ────────
    # O Al-Nassr de Riade apareceu com o escudo do Al Nasr de Dubai: os dois
    # normalizam para a mesma chave em escudos_por_clube(), que lê a tabela de
    # transferências — com clube do mundo inteiro — e deixa ganhar quem entrou
    # primeiro. O erro é silencioso e convincente: um escudo bonito no lugar
    # errado.
    ok("escudos_da_liga" in tela,
       "a guia voltou a tirar escudo só da tabela de transferências. Lá há "
       "clube do mundo inteiro, e homônimo do Golfo colide na mesma chave — "
       "foi assim que o Al-Nassr saiu com o escudo do Al Nasr de Dubai")
    i_geral = tela.find("escudos_por_clube()")
    i_liga = tela.find("escudos_da_liga(")
    ok(-1 < i_geral < i_liga,
       "a ordem inverteu: o mapa geral precisa entrar PRIMEIRO e o da liga "
       "por cima, senão o homônimo volta a ganhar")

    # E a função da liga tem que sair mesmo do CALENDÁRIO da competição —
    # é de lá que vem a garantia de só haver os 18 clubes da Roshn. Checar só
    # o nome dela na tela deixaria passar uma função que devolve nada.
    banco = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    corpo_liga = banco[banco.find("def escudos_da_liga"):]
    corpo_liga = corpo_liga[:corpo_liga.find("\ndef ", 10)]
    ok("FROM partida_liga" in corpo_liga,
       "escudos_da_liga parou de ler o calendário da competição. É ele que "
       "garante que só existem ali os clubes da liga, sem homônimo")
    ok("media.api-sports.io" in corpo_liga,
       "o escudo da liga deixou de usar o endereço padrão da API-Football, "
       "que é o mesmo das guias Pendurados e Elencos")

    # ── 4. suspensão vem junto, e o tipo cru não se perde ────────────────
    ok("suspend" in rota and "Suspensão" in rota,
       "a rota parou de reconhecer suspensão. O mesmo endpoint da API "
       "devolve lesão E suspensão, e a suspensão é metade do valor dele")
    ok('"tipo_bruto"' in rota,
       "sumiu o tipo_bruto. A API também escreve 'Missing Fixture' e "
       "'Questionable'; traduzir só o que eu previ apaga o resto")

    # ── 5. cruzar com o nosso monitor sem inventar ───────────────────────
    # A marca de "só uma fonte viu" é o motivo de ter a segunda fonte. Na
    # rota ela continua vindo calculada; na tela, quem separa é a junção —
    # o jogador que o TM conhece e a imprensa não vira card próprio.
    ok("no_nosso_monitor" in rota,
       "a rota parou de marcar quem o nosso monitor já conhece")
    ok("não saiu na imprensa que eu coleto" in tela,
       "sumiu o aviso de quem só a segunda fonte viu — é o reserva que "
       "ninguém noticiou, e é metade do valor de ter duas fontes")
    # A normalização de nome, exercitada de verdade — e não procurada no
    # texto. Rodo só ESTA função, num espaço com re e unicodedata, porque ela
    # é pura e o main.py inteiro não sobe sem banco.
    chave_src = _corpo("_chave_de_nome")
    ok(chave_src, "sumiu a normalização de nome usada para cruzar as fontes")
    if chave_src:
        import re as _re
        import unicodedata as _ud
        ns = {"re": _re, "unicodedata": _ud}
        exec(compile(ast.Module(body=[ast.parse(chave_src).body[0]],
                                type_ignores=[]), "<chave>", "exec"), ns)
        chave = ns["_chave_de_nome"]

        ok(chave("Cristiano  RONALDO ") == chave("cristiano ronaldo"),
           "caixa e espaço sobrando voltaram a ser diferença de pessoa")
        ok(chave("Ângelo") == chave("Angelo"),
           "acento voltou a ser diferença: a API escreve 'Angelo' e o "
           "matchsheet escreve 'Ângelo'")
        ok(chave("A. Boulbina") == chave("A Boulbina"),
           "a pontuação do nome abreviado voltou a contar")
        # E o limite: casar por pedaço do nome poria o jogador errado na tela.
        ok(chave("N. Fekir") != chave("Nabil Fekir"),
           "a comparação passou a casar nome abreviado com nome completo. "
           "'N. Fekir' e 'Nabil Fekir' são provavelmente a mesma pessoa — mas "
           "'N. Silva' e 'Neymar Silva' também seriam, e aí a tela marca como "
           "conferido um jogador que ninguém conferiu")
        ok(chave("") == "" and chave(None) == "",
           "nome vazio deixou de virar chave vazia e pode casar com qualquer "
           "outro nome vazio")

    # ── 6. A MESMA PESSOA VIRA UM CARD SÓ ────────────────────────────────
    # O banco guarda uma linha por incidente e o casamento era por
    # SEMELHANÇA DE TEXTO, com corte em 0,75. A IA transliterou o mesmo
    # jogador como "Rúger Fernández" numa notícia, "Rojer" noutra e "Roger
    # Fernandes" numa terceira — nomes que não se parecem com nada — e ele
    # apareceu três vezes na tela, como três lesionados.
    #
    # O Vini perguntou se todo o mapeamento de nomes tinha sido feito à toa.
    # Tinha sido feito; não estava sendo consultado aqui.
    # A CHAMADA, não a definição. Procurar "_juntar(" casa com o `def
    # _juntar(` e o teste passa com a função definida e nunca usada — que é
    # exatamente o defeito. Já caí nisso três vezes neste projeto.
    ok("active, recovered = _juntar(active), _juntar(recovered)" in tela,
       "sumiu a CHAMADA que une as lesões da mesma pessoa. Sem ela, o mesmo "
       "jogador volta a aparecer três vezes, uma por transliteração da IA")
    ok("def _identidade(" in tela,
       "sumiu a função que resolve a identidade do lesionado")
    ok('for nome in (inj.get("player_name"), inj.get("player_name_orig"))' in tela,
       "a identidade parou de tentar também o nome ORIGINAL da notícia. No "
       "caso do Roger Fernandes o nome certo era justamente o original: a "
       "transliteração da IA foi a que errou")
    ok("_do_elenco(nome" in tela,
       "a identidade deixou de passar pelo índice de jogadores")
    ok('grupos.setdefault(_identidade(inj), [])' in tela,
       "o agrupamento deixou de usar a identidade como chave")
    # Quem o elenco NÃO conhece continua sozinho: juntar dois desconhecidos
    # porque não sei quem são seria inventar identidade em cima de ignorância.
    ok('return ("nome", _chave_de_nome' in tela,
       "quem o elenco não conhece deixou de ter chave própria — dois "
       "desconhecidos passariam a ser tratados como a mesma pessoa")
    # E o conserto na origem, para não depender só da tela.
    banco2 = open(os.path.join(RAIZ, "database.py"), encoding="utf-8").read()
    ok("def _quem_e(" in banco2,
       "sumiu a resolução de identidade do banco — sem ela, cada notícia nova "
       "volta a criar uma linha por grafia")
    upsert = banco2[banco2.find("def upsert_injury"):]
    upsert = upsert[:upsert.find("\ndef ", 10)]
    i_id = upsert.find("_quem_e(")
    i_txt = upsert.find("SequenceMatcher(None")
    ok(-1 < i_id < i_txt,
       "a semelhança de texto voltou a vir ANTES da identidade. A ordem é a "
       "regra: 'Rúger Fernández' e 'Rojer' nunca se parecerão, e só a "
       "identidade sabe que são a mesma pessoa")

    # ── 7. excluir, e o cadastro manual ──────────────────────────────────
    ok("excluirLesao(" in tela and "/api/injuries/apagar" in tela,
       "sumiu o botão de excluir. A coleta é automática e às vezes erra; sem "
       "um jeito de tirar, o conserto seria aprender a ignorar linhas — e "
       "monitor que se aprende a ignorar não monitora mais nada")
    ok("confirm('Tem certeza que deseja excluir a lesão de '" in tela,
       "o excluir parou de perguntar antes")
    ok("nome.trim()" in tela,
       "a pergunta de exclusão parou de dizer QUEM vai sair. 'Tem certeza?' "
       "sozinho não protege de nada: a pessoa confirma sem ler")
    ok("data-ids=" in tela,
       "o card perdeu os ids. Depois que a identidade passou a juntar "
       "registros, apagar só um deixaria os irmãos de volta na próxima carga")

    ok("/api/injuries/manual" in tela and "salvarLesao(" in tela,
       "sumiu o cadastro manual de lesão")
    ok("/api/injuries/buscar-jogador" in tela,
       "a busca de jogador do cadastro manual sumiu")
    manual = _corpo("api_injuries_manual")
    ok("upsert_injury" in manual,
       "o cadastro manual deixou de entrar pelo mesmo caminho das "
       "automáticas. Por uma porta lateral, ele criaria um card paralelo em "
       "vez de se juntar ao que já existe daquele jogador")
    ok("Cadastro manual" in manual,
       "a fonte manual parou de se identificar no histórico — daqui a um mês "
       "não dá para saber o que veio da imprensa e o que foi você que pôs")

    # ── 8. ordem de ocorrência, e os chips de estado ─────────────────────
    # A data da LESÃO manda, não a da última notícia. Um caso de três semanas
    # atrás que ganhou uma nota hoje subia ao topo e empurrava para baixo
    # quem se machucou ontem.
    ok("def _quando(" in tela and 'i.get("injury_date")' in tela,
       "a lista voltou a ser ordenada pela última atualização em vez da data "
       "da lesão — notícia velha com nota nova sobe ao topo")
    ok("active.sort(key=_quando, reverse=True)" in tela,
       "sumiu a ordenação por ocorrência")
    ok("lsn-chips" in tela and "filtrarEstado(" in tela,
       "sumiram os filtros de estado no topo")
    # Os dois filtros valem juntos: "quem do Al-Hilal está lesionado" é a
    # pergunta mais comum, e exigir escolher um dos dois a deixaria sem
    # resposta.
    ok("doClube && doEstado" in tela,
       "os filtros de clube e de estado deixaram de valer ao mesmo tempo")

    # ── 9. o celular não pode reescalar a letra sozinho ──────────────────
    # O rodapé "ATUALIZADO" é 10px fixos no CSS e mesmo assim saía enorme no
    # celular — duas vezes o Vini apontou. Não era o CSS: Android Chrome e
    # iOS Safari incham por conta própria a letra que julgam pequena demais,
    # e escolhem o que inchar, o que faz o sintoma parecer arbitrário.
    ok("text-size-adjust: 100%" in FONTE,
       "voltou o inchaço automático de letra no celular. O CSS pode dizer "
       "10px e o navegador desenhar o dobro — e só num pedaço da tela")
    ok("_HEAD_COMUM = _THEME_INIT_SCRIPT + _PWA_HEAD + _SEM_ZOOM_NO_TOQUE" in FONTE,
       "a regra saiu do _HEAD_COMUM e deixou de valer em todas as telas")

    # ── 10. O GLOSSÁRIO DE APELIDOS — a ideia do Vini ────────────────────
    # Passei três rodadas tentando fazer a máquina adivinhar que "Rúger
    # Fernández", "Rojer" e "Roger Fernandes" são a mesma pessoa. Não existe
    # regra automática que acerte: a transliteração está ERRADA, não é uma
    # variação. Adivinhar ali seria chutar identidade — e chutar identidade
    # põe a lesão de um jogador no card de outro.
    #
    # O que resolve é uma decisão humana, tomada uma vez e guardada para
    # sempre. É o mesmo padrão que o app já usa para nome de árbitro.
    # A LIGAÇÃO, e não o nome da função: o botão precisa CHAMAR a abertura, e
    # o salvar precisa CHAMAR a rota. Procurar "abrirCorrecao(" casa com o
    # `function abrirCorrecao(` e passa com o onclick vazio.
    ok('onclick=\\"abrirCorrecao(this)\\"' in tela and "lsn-corrigir" in tela,
       "sumiu o campo de corrigir o nome no card. Sem ele, o nome que a IA "
       "transliterou errado não tem conserto nenhum")
    ok("onclick=\"salvarCorrecao(this)\"" in tela
       and "fetch('/api/jogador/apelido'" in tela,
       "a correção deixou de ser gravada — corrigir na tela e não guardar é "
       "pedir para o Vini corrigir a mesma coisa toda semana")
    ok('"spl_id": j.get("spl_id")' in FONTE,
       "a busca de jogador parou de devolver o spl_id. Sem ele, o glossário "
       "teria de casar por NOME de novo — o problema que veio resolver")
    # Dentro do salvarCorrecao, e não em qualquer lugar do arquivo: o
    # recarregar existe em outros pontos da página.
    salvar = tela[tela.find("async function salvarCorrecao"):]
    salvar = salvar[:salvar.find("\n}}") + 3]
    ok("location.reload();" in salvar,
       "depois de corrigir, a tela não recarrega — a união dos cards "
       "acontece no servidor, e o resultado não apareceria")

    ok("def definir_apelido(" in banco2 and "def apelidos_de_jogador(" in banco2,
       "sumiu o glossário de apelidos do banco")
    # E ele tem que ser consultado ANTES de qualquer dedução: o que o Vini
    # corrigiu olhando a tela vale mais que o meu palpite.
    quem = banco2[banco2.find("def _quem_e("):]
    quem = quem[:quem.find("\ndef ", 10)]
    i_glo = quem.find("apelidos_de_jogador()")
    i_idx = quem.find("elos.jogadores_no_texto")
    ok(-1 < i_glo < i_idx,
       "o glossário deixou de vir antes do índice automático. O que foi "
       "corrigido à mão tem que ganhar: quem corrigiu estava olhando a tela")
    ok("_apelidos.get(" in tela,
       "a tela parou de consultar o glossário na hora de identificar")

    # ── 11. o `since` do Transfermarkt ───────────────────────────────────
    # O Vini achou a visão detalhada (/plus/1), que traz a data de INÍCIO da
    # lesão. Sem ela eu só tinha a previsão de retorno, e a entrada no
    # histórico ia carimbada com a data de hoje.
    tm = open(os.path.join(RAIZ, "lesoes_tm.py"), encoding="utf-8").read()
    ok('CAMINHO = "/saudi-pro-league/verletztespieler/wettbewerb/SA1/plus/1"' in tm,
       "a raspagem voltou para a visão simples do Transfermarkt, que não tem "
       "a data de início da lesão")
    ok('"desde"' in tm,
       "o campo `desde` (o since do TM) sumiu da leitura")
    # As colunas mudam entre as duas visões — 5 na simples, 8 na detalhada.
    # Contar a partir do fim lia a nacionalidade como lesão, sem erro nenhum.
    ok("_indice_das_colunas" in tm,
       "a leitura voltou a achar as colunas por posição. As duas versões da "
       "página têm número diferente de colunas, e contar do fim lê a coluna "
       "errada sem dar erro")

    # ── 12. QUEM JÁ VOLTOU SAI DA LISTA ──────────────────────────────────
    # A imprensa escreve quando alguém se machuca e cala quando o sujeito
    # volta a jogar — retorno não é notícia. O monitor, que só lê notícia,
    # vira uma lista que nunca encolhe.
    #
    # Dá para deduzir SEM CHUTAR porque não passa por nome: `jogador.af_id`
    # liga o nosso jogador ao da API-Football, e a escalação da partida vem
    # com esse mesmo id. "Fulano atuou" é comparação de inteiros.
    retorno = _corpo("_marcar_retornos")
    ok(retorno, "sumiu a rotina que marca quem já voltou a jogar")
    ok("await asyncio.to_thread(atuou_depois, af, desde)" in retorno,
       "a rotina parou de conferir se o jogador atuou depois da lesão")
    ok('af = (por_spl.get(spl) or {}).get("af_id")' in retorno,
       "a identificação deixou de usar o af_id. Se voltar a casar por nome, "
       "volta a errar de pessoa — e aqui errar é pôr em campo, na tela, "
       "alguém que continua no departamento médico")
    ok('feito["sem_af_id"] += 1' in retorno and "continue" in retorno,
       "quem não tem id cruzado deixou de ser pulado. Sem identidade EXATA "
       "eu não posso deduzir recuperação")
    # Os dois "recuperado" existem de propósito e cada um faz uma coisa: o de
    # cima muda o estado do card, o de baixo escreve a linha do histórico. Por
    # isso são conferidos separadamente — trocar só um dos dois deixaria o card
    # dizendo uma coisa e o histórico outra, e esse é justamente o erro que
    # passaria despercebido.
    ok('"club": inj.get("club"), "status": "recuperado",' in retorno,
       "o card parou de mudar para recuperado")
    ok('"source_name": "Escalação da partida"' in retorno
       and '"status": "recuperado"' in retorno.split("source_info")[-1],
       "o retorno deixou de virar uma entrada de histórico. Trocar o estado "
       "em silêncio tira do Vini a chance de conferir")
    ok("Voltou a jogar em" in retorno and "minuto(s)" in retorno,
       "a entrada do retorno parou de dizer em que jogo e quantos minutos — "
       "é o que torna a dedução conferível")

    ler = _corpo("_ler_escalacoes")
    ok("fixtures/players" in ler,
       "a leitura de escalações mudou de endpoint sem querer")
    ok("if not minutos:\n                    continue" in ler,
       "quem ficou no banco sem entrar passou a contar como tendo atuado. "
       "Relacionado não é o mesmo que recuperado")
    ok("partidas_com_escalacao_lida" in ler,
       "sumiu o controle do que já foi lido — cada passagem reconsultaria as "
       "mesmas partidas, uma chamada cada")
    ok("conferirRetornos(" in tela,
       "sumiu o botão de conferir quem já voltou")

    # ── 13. a caneta também onde ela mais falta ──────────────────────────
    # Os cards que só o Transfermarkt conhece ficam sozinhos no fim da lista
    # justamente porque o nome não bateu com nenhum de cima — e corrigir o
    # nome é o que os junta.
    ok(tela.count('onclick="abrirCorrecao(this)"') >= 1
       or tela.count('onclick=\\"abrirCorrecao(this)\\"') >= 1,
       "sumiu a caneta de corrigir nome")
    ok("data-bruto=\"' + lsnEsc(nome) + '\"" in tela,
       "o card que só o Transfermarkt conhece ficou sem a caneta. É nele que "
       "ela mais serve: ele está sozinho porque o nome não casou")

    for f in falhas:
        print("  ✗", f)
    print(f"\nFALHAS: {len(falhas)}" if falhas else
          "  ✓ Lesões: filtro por clube com contagem viva, e a conferência "
          "no Transfermarkt casando por id")
    return len(falhas)


if __name__ == "__main__":
    sys.exit(1 if testar() else 0)
