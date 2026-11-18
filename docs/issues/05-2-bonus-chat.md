# [05.2] Bônus: chat na partida

| | |
|---|---|
| **Responsável** | Parte C: CLI e integração |
| **Área** | bônus |
| **Prazo** | Qua 18/11 (manhã) |
| **Branch** | `feat/05-2-bonus-chat` |
| **Depende de** | [04.3](04-3-integrar-partida.md) |
| **Etiquetas** | `parte-C` `bônus` `Sprint Backlog` |
| **Especificação** | Critérios de Avaliação (Bônus) |

## Contexto atual

**Só se todo o restante estiver pronto.** Mensagem `CHAT` enviada ao host e difundida por ele aos jogadores.

## Objetivo

Adicionar `CHAT` ao protocolo (contrato primeiro) e o comando `/chat <texto>`.

## Dentro do escopo

- [x] Definir `CHAT` em `docs/CONTRATO.md` e `protocol.py`
- [x] `GameHost` difunde o texto a todos com o remetente
- [x] `/chat <texto>` na CLI e exibição `[Game]`

## Fora do escopo

- Qualquer item obrigatório

## Critérios de aceite

- [x] Mensagem de um jogador aparece para todos os demais
- [x] Peers sem suporte ignoram sem quebrar (`unknown_type` não derruba a conexão)

## Itens a estudar

- Como adicionar um tipo ao `ALL_TYPES` e a `REQUIRED_FIELDS`

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/05-2-bonus-chat.md`. Releia na `docs/especificacao.md` as seções: Critérios de Avaliação (Bônus). Entre em plan mode e proponha o plano para a issue 05.2. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
