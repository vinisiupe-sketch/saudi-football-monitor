"""
Quem a notícia está falando — o elo entre o texto e a tabela de jogadores.

O QUE ESTE ARQUIVO FAZ, E O QUE ELE SE RECUSA A FAZER
    Faz: acha, no texto da notícia, o nome COMPLETO de alguém que está na
    tabela de jogadores, nas duas escritas.

    Não faz: adivinhar. Não casa por semelhança, não casa por sobrenome
    solto, não escolhe entre dois candidatos. Um jogador citado e não achado
    é um prejuízo pequeno e visível. Um jogador ERRADO colado numa notícia é
    uma foto errada no card, um link errado, e — quando isso virar
    estatística — um número que ninguém sabe explicar.

POR QUE SÓ NOME COMPLETO
    A liga tem 573 jogadores. 'محمد' (Mohammed) aparece em dezenas deles;
    'الدوسري' (Al Dawsari) em vários. Qualquer regra que aceite uma palavra
    solta transforma toda notícia sobre o Al-Hilal numa notícia sobre sete
    jogadores. O nome inteiro, na ordem, é a única forma barata de ter certeza.

    A perda disso é real e eu não escondo: 'Al Dawsari marcou' não vai ser
    encontrado. Prefiro assim até ter uma forma medida de resolver — e a
    forma provável é o clube da notícia, não a semelhança do nome.

AS DUAS ESCRITAS
    A mesma notícia existe em árabe (title_orig) e em português (title_pt). As
    duas chaves erram em pessoas diferentes: no cruzamento de jogadores, o
    árabe sozinho deu 53%, o latim sozinho 62%, e juntos 84%. Aqui vale o
    mesmo raciocínio — procuro nas duas e junto o resultado.
"""
import glossary

# Uma chave com uma palavra só nunca entra no índice. É a regra que impede
# 'محمد' de virar um elo.
MINIMO_DE_PALAVRAS = 2

# Até onde vale procurar. Nome de jogador árabe passa de cinco palavras com
# alguma frequência ('Abdulmajeed Abdullah Fehaid Al Khathami'), mas acima
# disso o custo cresce sem achar mais ninguém.
MAIOR_NOME = 6


def _chaves_do_jogador(j: dict) -> list[tuple[str, str]]:
    """As formas do nome desta pessoa que valem a pena procurar.

    Devolve pares (chave, de_onde) para eu conseguir contar depois qual
    escrita achou o quê — sem isso eu não teria como saber se vale manter as
    duas.
    """
    saida = []
    lat = glossary.chave_latina(j.get("nome") or "")
    if len(lat.split()) >= MINIMO_DE_PALAVRAS:
        saida.append((lat, "latim"))
    ar = glossary.chave_arabe(j.get("nome_ar") or "")
    if len(ar.split()) >= MINIMO_DE_PALAVRAS:
        saida.append((ar, "árabe"))
        # 'عبد الله' e 'عبدالله' são a mesma pessoa, e a diferença é só onde
        # alguém apertou espaço. Como o espaço muda a divisão em palavras, o
        # n-grama não resolve: a forma SEM espaço nenhum é comparada contra o
        # texto também sem espaço, mais adiante.
        #
        # Eu tinha posto aqui uma condição `colada != ar.replace(" ", "")`,
        # achando que ela evitaria uma chave repetida. As duas coisas são
        # iguais por construção, então a condição era sempre falsa e a chave
        # colada nunca existiu. O teste com 'عبد الله الحمدان' foi o que
        # mostrou: o nome estava no texto, escrito do outro jeito, e não era
        # encontrado.
        colada = glossary.chave_colada(ar)
        if len(colada) >= 8:
            saida.append((colada, "árabe colado"))
    return saida


def indice_de_jogadores(jogadores: list[dict]) -> tuple[dict, dict]:
    """chave -> spl_id, e as chaves que eu me recuso a usar.

    Uma chave que cai em duas pessoas é jogada fora, não desempatada. Duas
    pessoas com o nome completo idêntico existem, e escolher uma delas seria
    acertar metade das vezes — calado, na metade errada.
    """
    achados: dict[str, set] = {}
    origem: dict[str, str] = {}
    for j in jogadores:
        spl = j.get("spl_id")
        if not spl:
            continue
        for chave, de_onde in _chaves_do_jogador(j):
            achados.setdefault(chave, set()).add(spl)
            origem.setdefault(chave, de_onde)
    indice = {k: next(iter(v)) for k, v in achados.items() if len(v) == 1}
    ambiguas = {k: sorted(v) for k, v in achados.items() if len(v) > 1}
    return {"chave": indice, "origem": origem}, ambiguas


def _ngramas(palavras: list[str], maior: int):
    """Todos os pedaços contíguos de 2 até `maior` palavras."""
    for n in range(min(maior, len(palavras)), MINIMO_DE_PALAVRAS - 1, -1):
        for i in range(len(palavras) - n + 1):
            yield " ".join(palavras[i:i + n])


def jogadores_no_texto(texto_ar: str, texto_lat: str, indice: dict) -> dict:
    """Quem aparece neste texto. spl_id -> a escrita que achou.

    Procuro do nome mais longo para o mais curto para que, num texto com
    'Abdulmajeed Abdullah Fehaid Al Khathami', o casamento aconteça com a
    pessoa inteira e não com um pedaço dela que por acaso seja o nome
    completo de outra.
    """
    chave = indice.get("chave") or {}
    encontrados: dict[str, str] = {}
    for bruto, normaliza, rotulo in ((texto_ar, glossary.chave_arabe, "árabe"),
                                     (texto_lat, glossary.chave_latina, "latim")):
        if not bruto:
            continue
        palavras = normaliza(bruto).split()
        for pedaco in _ngramas(palavras, MAIOR_NOME):
            spl = chave.get(pedaco)
            if spl and spl not in encontrados:
                encontrados[spl] = rotulo
        if rotulo == "árabe":
            # A forma colada precisa do texto colado: 'عبد الله' no texto vira
            # 'عبدالله' e só então bate com a chave colada do nome.
            junto = "".join(palavras)
            for k, spl in chave.items():
                if " " not in k and len(k) >= 8 and k in junto:
                    encontrados.setdefault(spl, "árabe colado")
    return encontrados


def _tem_arabe(t: str) -> bool:
    return any("ء" <= c <= "ي" for c in t or "")


def indice_de_clubes() -> dict:
    """Cada grafia conhecida de clube -> nome de exibição, já normalizada.

    O glossário de clubes é feito à mão e tem 18 entradas com seus apelidos.
    Isso muda tudo em relação a jogador: aqui eu não estou tentando reconhecer
    573 nomes parecidos entre si, estou procurando uma lista curta e fechada.
    """
    saida = {}
    for variante, canonico in glossary.variantes_de_clube().items():
        # O artigo `ال` é PRESERVADO aqui, ao contrário do que faço com nome
        # de pessoa. Sem ele, 'النصر' vira 'نصر' — a palavra "vitória" — e o
        # Al-Nassr passaria a ser citado em toda notícia que fale em vencer.
        # 'الفتح' e 'الحزم' têm o mesmo problema. Num nome de gente o artigo
        # é ruído de grafia; num nome de clube ele é o que separa o time da
        # palavra comum.
        chave = (glossary.chave_arabe(variante, manter_artigo=True)
                 if _tem_arabe(variante) else glossary.chave_latina(variante))
        # Grafia de uma ou duas letras não entra: o ganho é mínimo e o
        # estrago de casar dentro de outra coisa é grande.
        if len(chave.replace(" ", "")) >= 3:
            saida.setdefault(chave, canonico)
    return saida


def clubes_no_texto(texto_ar: str, texto_lat: str, indice: dict) -> list[str]:
    """Os clubes citados, com o nome canônico do glossário.

    Comparo por PALAVRA INTEIRA, e não por pedaço de string, pelo mesmo motivo
    de sempre: 'al ahli' está contido em 'al ahliya', e um clube errado numa
    notícia é tão ruim quanto um jogador errado.
    """
    achados: list[str] = []
    for bruto, normaliza in (
            (texto_ar, lambda t: glossary.chave_arabe(t, manter_artigo=True)),
            (texto_lat, glossary.chave_latina)):
        if not bruto:
            continue
        palavras = normaliza(bruto).split()
        vistos = set(_ngramas(palavras, 4)) | set(palavras)
        for chave, canonico in indice.items():
            if chave in vistos and canonico not in achados:
                achados.append(canonico)
    return achados
