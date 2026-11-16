# [05.1] Bônus: migração de host

| | |
|---|---|
| **Responsável** | Parte B: Jogo |
| **Área** | bônus |
| **Prazo** | Qua 18/11 (manhã) |
| **Branch** | `feat/05-1-bonus-migracao-host` |
| **Depende de** | [04.4](04-4-integrar-falhas.md) |
| **Etiquetas** | `parte-B` `bônus` `Sprint Backlog` |
| **Especificação** | Tratamento de falhas (Bônus: migração de host) |

## Contexto atual

**Só se todo o restante estiver pronto.** Ao detectar a queda do host, o jogador de menor `peer_id` assume como novo host e recomeça a partida.

## Objetivo

Implementar a eleição e o recomeço de partida conforme o bônus da especificação.

## Dentro do escopo

- [ ] Ao `peer_stale` do host, o menor `peer_id` entre os `players` do último `STATE` vira host
- [ ] Novo host sorteia palavra, calcula novo `word_hash` e envia `GAME_START` com o mesmo `game_id` aos demais
- [ ] A partida recomeça com as vidas do último `STATE`
- [ ] Atualizar contrato e testes

## Fora do escopo

- Qualquer item obrigatório

## Critérios de aceite

- [ ] Com `kill -9` no host, a partida continua com um novo host
- [ ] O cenário 9 original continua válido quando o bônus está desligado/ não há jogadores suficientes

## Itens a estudar

- Eleição de líder pelo menor identificador

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/05-1-bonus-migracao-host.md`. Releia na `docs/especificacao.md` as seções: Tratamento de falhas (Bônus: migração de host). Entre em plan mode e proponha o plano para a issue 05.1. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
