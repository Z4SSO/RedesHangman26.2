# Issues do trabalho

30 issues no mesmo formato do tp2 (Contexto atual, Objetivo, Dentro/Fora do escopo, Critérios de aceite, Itens a estudar). Cada uma tem um **prompt sugerido** para começar a sessão do Claude Code.

- **Importar no GitLab:** `Issues → Import issues → CSV`, arquivo [`issues.csv`](issues.csv) (colunas `Title` e `Description`). O GitLab não importa etiquetas nem responsáveis por CSV: aplique `parte-A/B/C`, `Sprint Backlog` etc. pelo quadro.
- **Fluxo de git, revisão e cronograma:** [`../WORKFLOW.md`](../WORKFLOW.md).
- **Interfaces entre módulos:** [`../CONTRATO.md`](../CONTRATO.md).

## Ordem do dia a dia

- **Dom 15/11 (noite):** **00.1** (todos); **00.2** (todos)
- **Seg 16/11:** **00.3** (todos); **01.1** (A); **01.2** (A); **01.3** (A); **01.4** (A); **01.5** (A); **01.7** (A); **02.1** (B); **02.2** (B); **02.3** (B); **02.4** (B); **02.6** (B); **03.1** (C); **03.2** (C); **03.3** (C); **03.4** (C); **04.1** (C); **04.2** (todos)
- **Ter 17/11:** **01.6** (A); **02.5** (B); **03.5** (C); **04.3** (todos); **04.4** (todos); **04.5** (todos); **04.6** (todos)
- **Qua 18/11 (manhã):** **04.7** (todos); **05.1** (B); **05.2** (C)

> Hoje é domingo à noite e a entrega é quarta: o plano é apertado. As issues da segunda-feira são o caminho crítico e podem ser feitas **em paralelo** pelas três pessoas, porque só dependem do contrato. Se atrasar, corte pela ordem em `WORKFLOW.md`.

## 00 · Fundação (todos)

| | Issue | Prazo | Depende de |
|---|---|---|---|
| [x] | [00.1](00-1-repositorio.md) Criar o repositório e subir o esqueleto | Dom 15/11 (noite) | - |
| [x] | [00.2](00-2-contrato.md) Revisar e congelar o contrato entre módulos | Dom 15/11 (noite) | 00.1 |
| [x] | [00.3](00-3-material-professor.md) Obter o material do professor e testar o Rendezvous | Seg 16/11 | - |

## 01 · Rede (Parte A)

| | Issue | Prazo | Depende de |
|---|---|---|---|
| [x] | [01.1](01-1-rendezvous.md) Cliente do Rendezvous (REGISTER / DISCOVER / UNREGISTER) | Seg 16/11 | 00.2 |
| [x] | [01.2](01-2-peer-table.md) PeerTable: estados, eventos e reconciliação | Seg 16/11 | 00.2 |
| [x] | [01.3](01-3-peer-connection.md) PeerServer e PeerConnection: TCP e framing JSON por linha | Seg 16/11 | 00.2 |
| [x] | [01.4](01-4-hello-bye-duplicadas.md) HELLO/HELLO_OK, desempate de duplicadas e BYE/BYE_OK | Seg 16/11 | 01.3 |
| [x] | [01.5](01-5-keep-alive.md) KeepAlive: PING/PONG, RTT e detecção de STALE | Seg 16/11 | 01.4 |
| [x] | [01.6](01-6-reconexao-backoff.md) Reconexão com backoff exponencial | Ter 17/11 | 01.2, 01.5 |
| [x] | [01.7](01-7-p2p-client.md) P2PClient: orquestração, tarefas periódicas e encerramento limpo | Seg 16/11 | 01.1, 01.2, 01.5, 03.2 |

## 02 · Jogo (Parte B)

| | Issue | Prazo | Depende de |
|---|---|---|---|
| [x] | [02.1](02-1-hangman.md) hangman.py: lógica pura do jogo + testes unitários | Seg 16/11 | 00.2 |
| [x] | [02.2](02-2-host-lobby.md) GameHost (1/4): criar partida e lobby (GAME_LIST, JOIN, LEAVE) | Seg 16/11 | 02.1 |
| [x] | [02.3](02-3-host-start.md) GameHost (2/4): /start, GAME_START e STATE | Seg 16/11 | 02.2 |
| [x] | [02.4](02-4-host-jogadas.md) GameHost (3/4): GUESS, turnos, GAME_OVER e pontuação | Seg 16/11 | 02.3 |
| [x] | [02.5](02-5-host-falhas.md) GameHost (4/4): timeout de turno, queda de jogador e rejoin | Ter 17/11 | 02.4, 01.5 |
| [x] | [02.6](02-6-game-player.md) GamePlayer: entrar, jogar, aplicar STATE e reagir à queda do host | Seg 16/11 | 02.1 |

## 03 · CLI e logs (Parte C)

| | Issue | Prazo | Depende de |
|---|---|---|---|
| [x] | [03.1](03-1-main-logging.md) main.py: argumentos, config.json e logging | Seg 16/11 | 00.2 |
| [x] | [03.2](03-2-message-router.md) MessageRouter: validar o envelope e despachar por tipo | Seg 16/11 | 00.2 |
| [x] | [03.3](03-3-cli-rede.md) CLI (1/2): laço de comandos e comandos de rede | Seg 16/11 | 03.1, 03.2 |
| [x] | [03.4](03-4-cli-jogo.md) CLI (2/2): comandos de jogo e /games | Seg 16/11 | 03.3, 02.2, 02.6 |
| [x] | [03.5](03-5-logs-spec.md) Passada final de logs: textos e níveis da especificação | Ter 17/11 | 01.5, 02.4, 02.6, 03.1 |

## 04 · Integração e testes (todos)

| | Issue | Prazo | Depende de |
|---|---|---|---|
| [x] | [04.1](04-1-run-local.md) tools/run_local.py: subir N peers locais | Seg 16/11 | 03.1 |
| [x] | [04.2](04-2-integrar-malha.md) Integração 1: malha de descoberta (cenário 1) | Seg 16/11 | 01.7, 03.3 |
| [x] | [04.3](04-3-integrar-partida.md) Integração 2: partida completa (cenários 2 a 6) | Ter 17/11 | 04.2, 02.4, 02.6, 03.4 |
| [x] | [04.4](04-4-integrar-falhas.md) Integração 3: falhas de jogador e de host (cenários 7 a 9) | Ter 17/11 | 04.3, 02.5, 01.6 |
| [x] | [04.5](04-5-integrar-quit.md) Integração 4: encerramento limpo (cenário 10) | Ter 17/11 | 04.3, 01.7 |
| [x] | [04.6](04-6-interoperabilidade.md) Interoperabilidade com o cliente de referência e o forca-bot (cenário 11) | Ter 17/11 | 04.3, 00.3 |
| [ ] | [04.7](04-7-entrega.md) Revisão final, README e entrega | Qua 18/11 (manhã) | 04.4, 04.5, 04.6, 03.5 |

## 05 · Bônus (só se sobrar tempo)

| | Issue | Prazo | Depende de |
|---|---|---|---|
| [x] | [05.1](05-1-bonus-migracao-host.md) Bônus: migração de host | Qua 18/11 (manhã) | 04.4 |
| [x] | [05.2](05-2-bonus-chat.md) Bônus: chat na partida | Qua 18/11 (manhã) | 04.3 |

## Revisão cruzada

A revisa B, B revisa C, C revisa A. Issues `todos` são revisadas por quem não escreveu o código corrigido.
