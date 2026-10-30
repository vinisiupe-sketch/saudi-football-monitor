"""Mudou o código do gravador? A versão tem de mudar junto.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR (30/10/26)
    "O erro do 'o corte saiu com 261 bytes' no gravador de clipes voltou."

    Não voltou: nunca tinha saído da máquina que grava. Em 19/10 eu consertei
    o ffprobe que nunca era encontrado — e mudei o gravador.py sem mudar a
    VERSAO, que ficou em "2026-09-08a". O gravador só se atualiza sozinho
    quando a versão que o app espera é DIFERENTE da dele. A máquina perguntou,
    ouviu "você está em dia", e seguiu onze dias com o código velho, dando o
    mesmo "261 bytes" sem complemento que a correção existia para explicar.

COMO A TRAVA FUNCIONA
    Cada versão fica registrada aqui com a impressão digital do código (o
    arquivo inteiro, menos a própria linha da VERSAO). Se o código mudar e a
    versão não, este teste falha. Para passar: mude a VERSAO no gravador.py E
    a VERSAO_GRAVADOR no main.py, e registre a impressão nova abaixo — o
    próprio teste imprime qual é.
"""
import hashlib
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# versão → impressão digital do gravador.py daquela versão.
REGISTRO = {
    "2026-10-30a": "8376fc9bf86750e0956de0512de28bffed64236be7fe26cc13b1e35dec8a5525",
    "2026-10-30b": "9f9e65ed2af32bdfd8dd73aac53709b049608c60de84a4ae806ea2258e16650c",
}

falhas = []
codigo = open(os.path.join(RAIZ, "gravador.py"), encoding="utf-8").read().replace("\r\n", "\n")
main = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()

m = re.search(r'^VERSAO = "(.*)"$', codigo, re.M)
versao = m.group(1) if m else ""
m2 = re.search(r'^VERSAO_GRAVADOR = "(.*)"$', main, re.M)
esperada = m2.group(1) if m2 else ""
impressao = hashlib.sha256(
    re.sub(r'^VERSAO = ".*"$', 'VERSAO = ""', codigo, flags=re.M).encode()).hexdigest()

if versao != esperada:
    falhas.append(f"o gravador.py diz {versao!r} e o main.py espera {esperada!r}. "
                  "Com as duas diferentes, a máquina se atualiza em toda volta; "
                  "com as duas iguais e o código mudado, ela nunca se atualiza")
if versao not in REGISTRO:
    falhas.append(f"a versão {versao!r} não está registrada. Registre em REGISTRO: "
                  f'"{versao}": "{impressao}"')
elif REGISTRO[versao] != impressao:
    falhas.append(f"O CÓDIGO DO GRAVADOR MUDOU E A VERSÃO NÃO ({versao}). A máquina "
                  "que grava não vai baixar a mudança — foi assim que a correção "
                  "de 19/10 ficou onze dias fora dela. Mude VERSAO (gravador.py) e "
                  "VERSAO_GRAVADOR (main.py), e registre a impressão nova: "
                  f"{impressao}")

if falhas:
    print("❌ " + str(len(falhas)) + " falha(s):")
    for f in falhas:
        print("   - " + f)
    sys.exit(1)
print(f"✅ gravador {versao}: código e versão andam juntos")
