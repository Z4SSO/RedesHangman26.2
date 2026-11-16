# [04.4] Integração 3: falhas de jogador e de host (cenários 7 a 9)

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | integração |
| **Prazo** | Ter 17/11 |
| **Branch** | `feat/04-4-integrar-falhas` |
| **Depende de** | [04.3](04-3-integrar-partida.md), [02.5](02-5-host-falhas.md), [01.6](01-6-reconexao-backoff.md) |
| **Etiquetas** | `todos` `integração` `Sprint Backlog` |
| **Especificação** | Cenários de Teste Mínimos (7 a 9); Tratamento de falhas |

## Contexto atual

Tolerância a falhas vale um critério inteiro da avaliação e é onde mais se perde ponto por detalhe.

## Objetivo

Passar os cenários 7 (queda de jogador), 8 (reconexão com rejoin) e 9 (queda do host).

## Dentro do escopo

- [ ] Cenário 7: `kill -9` em `carol` durante a partida; após 3 PINGs perdidos `alice` a remove, difunde `STATE` e a partida continua com `bob`
- [ ] Cenário 8: `carol` reabre, reconecta e envia `JOIN`; recebe `rejoin: true` e o `STATE` corrente; volta ao rodízio
- [ ] Cenário 9: `kill -9` em `alice` (host); `bob` e `carol` mostram `[Game] Host alice@CIC unreachable — game aborted` e voltam a `IDLE`
- [ ] Registrar a evidência em `docs/testes.md` e corrigir o que falhar

## Fora do escopo

- Migração de host (bônus 05.1)

## Critérios de aceite

- [ ] Os três cenários passam, com logs que mostram a detecção e a ação
- [ ] Depois da queda do host, os jogadores conseguem entrar em outra partida

## Itens a estudar

- `kill -9` não deixa o peer mandar `BYE`: é a única forma de testar a detecção por PING

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/04-4-integrar-falhas.md`. Releia na `docs/especificacao.md` as seções: Cenários de Teste Mínimos (7 a 9), Tratamento de falhas. Entre em plan mode e proponha o plano para a issue 04.4. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
