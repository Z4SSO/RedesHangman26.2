# [01.7] P2PClient: orquestração, tarefas periódicas e encerramento limpo

| | |
|---|---|
| **Responsável** | Parte A: Rede |
| **Área** | rede |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/01-7-p2p-client` |
| **Depende de** | [01.1](01-1-rendezvous.md), [01.2](01-2-peer-table.md), [01.5](01-5-keep-alive.md), [03.2](03-2-message-router.md) |
| **Etiquetas** | `parte-A` `rede` `Sprint Backlog` |
| **Especificação** | Componentes de um peer; Gerenciamento de Conexões e Reconexões; /quit na tabela de comandos |

## Contexto atual

Cada módulo funciona sozinho; falta quem os liga, sobe as tarefas periódicas e garante o encerramento na ordem certa.

## Objetivo

Implementar `P2PClient.start()/stop()` com o ciclo de vida completo do peer, em parceria com a Parte C (ligação dos handlers).

## Dentro do escopo

- [ ] `start()`: `PeerServer.start` → `REGISTER` → tarefas periódicas → ligar `MessageRouter` e eventos da `PeerTable` a `GameHost`/`GamePlayer`
- [ ] Tarefa de `DISCOVER` a cada `discover_interval` → `PeerTable.reconcile`; trata `peer_not_registered` com novo `REGISTER` e uma repetição (contrato 6.9)
- [ ] Tarefa de refresh do registro na metade do `register_ttl`
- [ ] Garantir que nenhum laço fica sem `await asyncio.sleep` (limite de 50 req/min do Rendezvous)
- [ ] `stop()` na ordem do contrato (seção 8): `GAME_OVER ABORTED`/`LEAVE` → `BYE` a todos → `UNREGISTER` → cancelar tarefas
- [ ] Tratar `Ctrl+C` e `/quit` pelo mesmo caminho

## Fora do escopo

- Comandos da CLI (issues 03.3 e 03.4)

## Critérios de aceite

- [ ] Três peers locais se registram, se descobrem e `/conn` mostra duas conexões em cada um (cenário 1)
- [ ] `/quit` executa os passos na ordem do contrato e o processo termina sozinho
- [ ] Depois do `stop()` não sobra tarefa pendente nem socket aberto
- [ ] Em uso normal ficam ~3 requisições/min ao Rendezvous por peer

## Itens a estudar

- `asyncio.TaskGroup` (3.11+) ou lista de tasks com cancelamento no `stop()`
- `loop.add_signal_handler` para o `SIGINT`

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/01-7-p2p-client.md`. Releia na `docs/especificacao.md` as seções: Componentes de um peer, Gerenciamento de Conexões e Reconexões, /quit na tabela de comandos. Entre em plan mode e proponha o plano para a issue 01.7. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
