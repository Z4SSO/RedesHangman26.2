# [02.5] GameHost (4/4): timeout de turno, queda de jogador e rejoin

| | |
|---|---|
| **Responsável** | Parte B: Jogo |
| **Área** | jogo |
| **Prazo** | Ter 17/11 |
| **Branch** | `feat/02-5-host-falhas` |
| **Depende de** | [02.4](02-4-host-jogadas.md), [01.5](01-5-keep-alive.md) |
| **Etiquetas** | `parte-B` `jogo` `Sprint Backlog` |
| **Especificação** | Regras do jogo (timeout de turno, jogadores que saem); Tratamento de falhas; JOIN (rejoin) |

## Contexto atual

Jogadores podem ficar parados, sair ou cair (`kill -9`). O host precisa continuar a partida sem travar.

## Objetivo

Implementar o timeout de turno, a remoção de jogador caído e o retorno de jogador (`rejoin`).

## Dentro do escopo

- [ ] Timer de turno de `turn_timeout` s, reiniciado a cada `STATE`; ao estourar, passa o turno e difunde `STATE` com `last_guess: {"player": ..., "timeout": true}`, **sem custar vida**; log `[Host] Turn timeout for carol@CIC — skipping`
- [ ] `on_peer_stale(peer_id)`: se era jogador, remove, difunde `STATE`; se era a vez dele, passa o turno; log `[Host] Player carol@CIC STALE — removed from game`
- [ ] Se não restar nenhum jogador: `GAME_OVER ABORTED reason:"no_players"` (só registrado) e volta a `IDLE`
- [ ] `LEAVE` durante `RUNNING` também difunde novo `STATE`
- [ ] `JOIN` de quem já era jogador numa partida `RUNNING`: `JOIN_OK rejoin:true` + `STATE` corrente; ele volta ao **fim** do rodízio
- [ ] Cancelar o timer em todo fim de partida (sem tarefa vazando)
- [ ] Testes com relógio curto: timeout, queda na vez do jogador, queda do último jogador, rejoin

## Fora do escopo

- Migração de host (bônus 05.1)

## Critérios de aceite

- [ ] Cenários 6, 7 e 8 passam contra o `GameHost` com `Sender` falso
- [ ] Timeout não custa vida e o `STATE` traz `timeout: true`
- [ ] Jogador que cai na própria vez não trava a partida
- [ ] Rejoin devolve o `STATE` atual e o jogador entra no fim do rodízio

## Itens a estudar

- `asyncio.Task` com `cancel()` para reiniciar o timer; evitar dois timers simultâneos
- Por que o timeout chama a mesma rotina de "passar turno" que uma jogada aceita

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/02-5-host-falhas.md`. Releia na `docs/especificacao.md` as seções: Regras do jogo (timeout de turno, jogadores que saem), Tratamento de falhas, JOIN (rejoin). Entre em plan mode e proponha o plano para a issue 02.5. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
