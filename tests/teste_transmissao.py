"""
A transmissão como dado.

O que se testa aqui é a volta: ler de um post já escrito quais canais estão
marcados. Essa leitura só existe por causa do que já estava no banco antes da
tabela, mas é justamente por isso que ela precisa de teste — é código que roda
uma vez, em produção, sem ninguém olhando, e depois nunca mais.

O erro que mais me preocupa não é falhar: é acertar quase. "Sportv" está
contido em "Sportv 2". Se a leitura casar por pedaço em vez de por nome
inteiro, marcar o 2 acende os dois, e o relatório de prévia sai dizendo que o
jogo passa num canal onde ele não passa.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import posts_gerador as pg


def _post(*linhas):
    return "🔴 BOLA ROLANDO\n\nAl Hilal x Al Nassr\n" + "\n".join(linhas)


def testar():
    falhas = []

    def conferir(nome, deu, esperado):
        if deu != esperado:
            falhas.append(f"{nome}: esperava {esperado!r}, veio {deu!r}")

    # ---------------------------------------------------- ida e volta
    for canais in ([], ["Band"], ["Band", "Sportv"],
                   ["Canal GOAT 🐐", "BandSports", "XSports"],
                   ["Sportv", "Sportv 2", "Sportv 3", "Sportv 4"]):
        linha = pg.linha_transmissao(canais)
        volta = pg.canais_da_linha(_post(linha))
        conferir(f"ida e volta {canais}", volta, canais)

    # ------------------------------------- o caso que motivou o teste
    # "Sportv 2" sozinho não pode acender "Sportv".
    conferir("Sportv 2 sozinho",
             pg.canais_da_linha(_post(pg.linha_transmissao(["Sportv 2"]))),
             ["Sportv 2"])

    # ------------------------------------------- ausência vs. vazio
    # Post sem linha nenhuma: ninguém olhou ainda.
    conferir("sem linha", pg.canais_da_linha(_post("")), None)
    conferir("texto vazio", pg.canais_da_linha(""), None)
    conferir("texto None", pg.canais_da_linha(None), None)
    # Post com ❌: olhou, e não tem.
    conferir("sem transmissão", pg.canais_da_linha(_post("❌ Sem transmissão")), [])

    # ---------------------------------------- linha no meio, não no fim
    # A rota escreve a transmissão como última linha, mas o Vini edita o texto
    # à mão. Se ele escrever algo embaixo, a leitura tem que continuar achando.
    conferir("linha com texto embaixo",
             pg.canais_da_linha(_post("🖥️ Band", "", "Vai ser bom.")),
             ["Band"])

    # ------------------------------------------------ canal inventado
    # Nome que não está na lista é ignorado, não vira canal novo.
    conferir("canal fora da lista",
             pg.canais_da_linha(_post("🖥️ Band e ESPN")), ["Band"])

    # ------------------------------------------------ chave do jogo
    conferir("chave ida e volta", pg.jogo_da_chave(pg.chave_do_jogo(12345)), 12345)
    conferir("chave de outro tipo", pg.jogo_da_chave("gol:999"), None)
    conferir("chave sem número", pg.jogo_da_chave("bola_rolando:abc"), None)
    conferir("chave vazia", pg.jogo_da_chave(""), None)
    conferir("chave None", pg.jogo_da_chave(None), None)

    # ------------------------------------- ordem estável, sem repetido
    # A tela desenha os canais na ordem de TRANSMISSOES. Se a leitura devolver
    # em outra ordem, comparar duas marcações vira falso negativo.
    fora_de_ordem = pg.linha_transmissao(["Sportv", "Band"])
    conferir("ordem canônica", pg.canais_da_linha(_post(fora_de_ordem)),
             ["Band", "Sportv"])

    if falhas:
        for f in falhas:
            print(f"  ✗ {f}")
        return False
    print("  ✓ transmissão: leitura, ausência e chave do jogo")
    return True


if __name__ == "__main__":
    sys.exit(0 if testar() else 1)
