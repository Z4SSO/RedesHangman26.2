# [04.5] Integração 4: encerramento limpo (cenário 10)

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | integração |
| **Prazo** | Ter 17/11 |
| **Branch** | `feat/04-5-integrar-quit` |
| **Depende de** | [04.3](04-3-integrar-partida.md), [01.7](01-7-p2p-client.md) |
| **Etiquetas** | `todos` `integração` `Sprint Backlog` |
| **Especificação** | Cenários de Teste Mínimos (10); BYE / BYE_OK |

## Contexto atual

O `/quit` precisa fazer tudo na ordem certa; a avaliação confere a sequência.

## Objetivo

Passar o cenário 10: `/quit` no host durante a partida gera `GAME_OVER ABORTED` → `BYE/BYE_OK` → `UNREGISTER`, nessa ordem.

## Dentro do escopo

- [ ] `/quit` no host com partida `RUNNING`: conferir a ordem pelo log `Wire` (timestamps)
- [ ] `/quit` num jogador em partida: `LEAVE` → `BYE` → `UNREGISTER`
- [ ] `/quit` sem partida: `BYE` e `UNREGISTER`; depois um `DISCOVER` de outro peer não o lista mais
- [ ] `Ctrl+C` tem o mesmo comportamento

## Fora do escopo

- (nada em especial)

## Critérios de aceite

- [ ] A ordem das mensagens bate com o contrato (seção 8) nos três casos
- [ ] O processo termina sozinho em poucos segundos, sem tarefa pendente
- [ ] O peer some do `DISCOVER` dos outros logo após sair

## Itens a estudar

- Ordem dos eventos nos timestamps do arquivo de log

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/04-5-integrar-quit.md`. Releia na `docs/especificacao.md` as seções: Cenários de Teste Mínimos (10), BYE / BYE_OK. Entre em plan mode e proponha o plano para a issue 04.5. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
