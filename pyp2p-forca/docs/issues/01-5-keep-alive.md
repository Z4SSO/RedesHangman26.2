# [01.5] KeepAlive: PING/PONG, RTT e detecção de STALE

| | |
|---|---|
| **Responsável** | Parte A: Rede |
| **Área** | rede |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/01-5-keep-alive` |
| **Depende de** | [01.4](01-4-hello-bye-duplicadas.md) |
| **Etiquetas** | `parte-A` `rede` `Sprint Backlog` |
| **Especificação** | PING / PONG; Transporte e Codificação |

## Contexto atual

Uma conexão TCP pode morrer sem aviso (`kill -9`, cabo desconectado). É o `PING/PONG` que detecta isso, e a detecção dispara a remoção do jogador (host) ou o aborto da partida (jogador).

## Objetivo

Enviar PING periódico nos dois lados, medir RTT e marcar o peer `STALE` após 3 PINGs sem resposta.

## Dentro do escopo

- [ ] `PING` a cada `ping_interval` em cada conexão (`timestamp` ISO com milissegundos); `PONG` repete `msg_id` **e** `timestamp`
- [ ] RTT = recebimento do `PONG` − envio do `PING` (casado por `msg_id`), com média móvel dos últimos 10
- [ ] Contador de PINGs sem resposta, zerado quando um `PONG` chega
- [ ] Após `ping_miss_limit` (3) seguidos: log `[KeepAlive] carol@CIC missed 3 PINGs — marking STALE`, estado `STALE`, fecha a conexão e emite `peer_stale`
- [ ] Log `[KeepAlive] bob@CIC RTT=41.7 ms (avg 43.2 ms)`
- [ ] Testes com intervalo curto (ex.: 0,05 s) e com um par que não responde

## Fora do escopo

- Tentar reconectar o peer STALE (01.6)

## Critérios de aceite

- [ ] O RTT medido aparece em `conn.rtt_ms` e no log
- [ ] Um par que ignora os PINGs é marcado `STALE` após exatamente 3 intervalos sem `PONG`
- [ ] `peer_stale` é emitido uma única vez por queda
- [ ] Fechar a conexão cancela a tarefa de PING (sem tarefa vazando)

## Itens a estudar

- `time.monotonic()` para medir intervalos (e não `datetime`)
- Cancelar tarefas com `task.cancel()` e tratar `CancelledError`

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/01-5-keep-alive.md`. Releia na `docs/especificacao.md` as seções: PING / PONG, Transporte e Codificação. Entre em plan mode e proponha o plano para a issue 01.5. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
