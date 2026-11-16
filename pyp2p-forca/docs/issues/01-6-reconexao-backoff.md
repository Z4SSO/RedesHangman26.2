# [01.6] Reconexão com backoff exponencial

| | |
|---|---|
| **Responsável** | Parte A: Rede |
| **Área** | rede |
| **Prazo** | Ter 17/11 |
| **Branch** | `feat/01-6-reconexao-backoff` |
| **Depende de** | [01.2](01-2-peer-table.md), [01.5](01-5-keep-alive.md) |
| **Etiquetas** | `parte-A` `rede` `Sprint Backlog` |
| **Especificação** | Gerenciamento de Conexões e Reconexões |

## Contexto atual

Peers `STALE` voltam a aparecer (a pessoa reabre o programa, a rede volta). O cliente precisa tentar de novo sem martelar o servidor nem o peer.

## Objetivo

Reconectar peers `STALE` com espera `base_backoff × 2^n`, limitada por `max_backoff`, até `max_reconnect_attempts`.

## Dentro do escopo

- [ ] Agendar a próxima tentativa em `next_retry` na `PeerTable` (sem `sleep` bloqueante)
- [ ] Espera = `min(base_backoff * 2**n, max_backoff)`; `attempts` volta a zero ao reconectar
- [ ] Passar de `max_reconnect_attempts` marca o peer `GONE` até ele reaparecer em um `DISCOVER`
- [ ] Um método que force a reconciliação imediata, para o comando `/reconnect` da CLI chamar
- [ ] Testes com `base_backoff` pequeno, conferindo a sequência de esperas

## Fora do escopo

- Reconexão **da partida** (o jogador reenviar `JOIN` ao voltar é da issue 02.6)

## Critérios de aceite

- [ ] As esperas seguem 2, 4, 8, 16, 32 s com os valores padrão e nunca passam de `max_backoff`
- [ ] Depois de `max_reconnect_attempts` falhas o peer vira `GONE`; um novo `DISCOVER` com ele o traz de volta a `DISCOVERED`
- [ ] Peer que reconecta volta a `CONNECTED` e zera as tentativas
- [ ] Nenhuma tentativa bloqueia as demais conexões

## Itens a estudar

- Backoff exponencial e por que se adiciona um pouco de jitter
- `loop.call_later` ou uma tarefa por peer com `asyncio.sleep`

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/01-6-reconexao-backoff.md`. Releia na `docs/especificacao.md` as seções: Gerenciamento de Conexões e Reconexões. Entre em plan mode e proponha o plano para a issue 01.6. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
