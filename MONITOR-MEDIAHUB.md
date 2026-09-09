# Monitor do Media Hub

Implementação preparada para um **segundo serviço no Railway**, no mesmo
projeto do app. Não precisa deixar seu computador ou o Brave abertos.

## O que já foi conferido

- Acesso ao portal em uma sessão autenticada no navegador integrado.
- Caminho SPL Content > Match Day Support > rodada > Team Sheets.
- Filtro por data da partida e seleção da mídia ENG, separada da AR.
- O extrator existente lê o PDF Al Fateh x Al Ittihad: 11 titulares e
  9 reservas de cada time.

**Login automático validado no Railway em 09/09/2026**, com navegador em
tela virtual e credenciais nas variáveis do serviço.

**Ainda precisa ser validado no Railway:** download no
navegador do servidor e envio com o token de produção. O login feito no
Codex não é transferido para o Railway. Não foi copiada nenhuma senha.

## Configuração guiada

1. Publique também as alterações de `main.py` e `database.py` no serviço
   atual. Elas acrescentam o estado do monitor e a confirmação de gravação,
   e permitem substituir uma escalação quando o PDF é corrigido.
2. No mesmo projeto Railway, crie outro serviço ligado a este repositório.
   Nome sugerido: `mediahub-monitor`.
3. Configure **esse novo serviço pelo painel**. Mantenha a raiz do
   repositório, defina `RAILWAY_DOCKERFILE_PATH=Dockerfile.mediahub` nas
   variáveis e o comando de início `python mediahub_start.py` em Settings.
   O app continua com sua configuração atual. Deixe uma única instância,
   sem cron, sem domínio público e sem suspensão automática. O Railway
   informa que serviços novos não podem mais aderir a Config as Code;
   por isso não use um novo arquivo railway.toml para configurar o monitor.
4. Adicione um volume ao novo serviço, montado em `/data`. Ele guarda a
   sessão e os comprovantes dos PDFs enviados entre reinícios.
5. Configure as variáveis abaixo na área Variables do Railway. Digite
   e-mail e senha ali, nunca no GitHub nem no chat.

| Variável no monitor | Valor |
| --- | --- |
| `APP_URL` | `https://saudi-football-monitor-production.up.railway.app` |
| `MEDIAHUB_EMAIL` | Seu e-mail do Media Hub |
| `MEDIAHUB_PASSWORD` | Sua senha do Media Hub |
| `ESCALACAO_TOKEN` | O mesmo segredo configurado no serviço do app |
| `RAILWAY_DOCKERFILE_PATH` | `Dockerfile.mediahub` |

Se `ESCALACAO_TOKEN` não existir no app, gere um segredo aleatório forte e
configure o mesmo valor nos dois serviços. Se já existir, reutilize-o para
preservar integrações anteriores. Não envie o segredo no chat.

## Teste antes de ativar

No novo serviço, use temporariamente este comando de início:

```text
python mediahub_start.py --check-record https://mediahub.spl.media/record/14146 --dry-run
```

Isso baixa e valida o PDF de exemplo, sem publicar e sem esperar horário
de jogo. O log deve dizer `PDF validado; nenhum envio`. O processo termina
normalmente: é um teste pontual, não o monitor permanente.

Depois retire `--dry-run` para testar uma gravação no app, se desejar
incluir esse jogo antigo no histórico. Confira a escalação na tela do app.
Para ativar o monitor, restaure:

```text
python mediahub_start.py
```

## Como funciona

- Usa Chromium com janela em uma tela virtual no servidor. Em teste no
  Railway em 09/09/2026, o modo headless recebeu HTTP 403 do CloudFront,
  enquanto o modo com janela abriu a página de login com HTTP 200 no mesmo
  ambiente. Não é necessário manter um computador pessoal ligado.

- Consulta `/api/diag/jogos-de-hoje`, já existente no app.
- Fora da janela dos jogos, fecha o navegador e aguarda.
- De 100 minutos antes até o início, busca documentos de apoio da SPL na
  data da Arábia Saudita, a cada 60 segundos, sem sobrepor ciclos.
- Seleciona o documento inglês, valida data e 11 titulares por time e
  envia para `/api/escalacao-pdf` com `X-Escalacao-Token`.
- Só marca como entregue depois de o app confirmar `salvo: true`.
- PDFs já entregues são baixados novamente a cada 5 minutos durante a
  janela, para detectar correções pelo conteúdo. Reenvia só se mudarem.
- O estado aparece na tela Escalação PDF, atualizada a cada 30 segundos.
- Falhas geram aviso e novas tentativas com intervalo crescente, até
  15 minutos. Falhas de login aguardam 15 minutos antes de tentar novamente.
- Login usa a sessão persistida; quando expira, tenta e-mail e senha.
  CAPTCHA, código de verificação ou bloqueio do servidor exigem resolver
  o acesso antes de considerar o monitor operacional.

Não é garantia de detecção em exatamente 60 segundos: dependem do tempo
do portal, número de documentos, conexão e eventuais novas tentativas.

Configurações opcionais: `MEDIAHUB_INTERVAL_SECONDS` (mínimo 60),
`MEDIAHUB_REVISION_SECONDS` (padrão 300), `MEDIAHUB_BEFORE_MINUTES`
(padrão 100), `MEDIAHUB_DATA_DIR` (padrão `/data`).

## Verificação local do código

```text
python -m unittest discover -s tests -p test_mediahub_monitor.py
```

Esses testes são locais, não autenticam no portal nem enviam PDFs ao app.
O contêiner usa a mesma versão do pacote e do navegador Playwright,
conforme a [documentação oficial](https://playwright.dev/python/docs/docker).
