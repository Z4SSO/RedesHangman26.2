# [03.5] Passada final de logs: textos e níveis da especificação

| | |
|---|---|
| **Responsável** | Parte C: CLI e integração |
| **Área** | cli |
| **Prazo** | Ter 17/11 |
| **Branch** | `feat/03-5-logs-spec` |
| **Depende de** | [01.5](01-5-keep-alive.md), [02.4](02-4-host-jogadas.md), [02.6](02-6-game-player.md), [03.1](03-1-main-logging.md) |
| **Etiquetas** | `parte-C` `cli` `Sprint Backlog` |
| **Especificação** | Observabilidade e Logs |

## Contexto atual

O item 8 da avaliação confere os logs: módulo, timestamp, nível e o JSON bruto em DEBUG. Os textos de exemplo da especificação servem de referência.

## Objetivo

Percorrer todos os módulos e garantir que cada evento da lista de exemplos da especificação é logado com o texto e o logger certos.

## Dentro do escopo

- [x] Montar uma tabela `evento da especificação → logger → arquivo:linha` ([`docs/LOGS.md`](../LOGS.md))
- [x] Corrigir textos divergentes por PR pequeno ao dono do módulo (ou pedir a ele)
- [x] Conferir que `DEBUG` mostra o JSON bruto de **toda** mensagem enviada/recebida
- [x] Conferir que a tela mostra `[CLI]`, `[Game]` e `INFO`, e o arquivo mostra tudo
- [x] Rodar o `spec-reviewer` na seção "Observabilidade e Logs"

## Fora do escopo

- Mudar o comportamento dos módulos

## Critérios de aceite

- [x] Cada linha de exemplo da especificação tem o evento correspondente no código
- [x] Uma partida completa gera log legível de ponta a ponta no arquivo

## Itens a estudar

- `logging.getLogger(name)` e propagação entre loggers

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/03-5-logs-spec.md`. Releia na `docs/especificacao.md` as seções: Observabilidade e Logs. Entre em plan mode e proponha o plano para a issue 03.5. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
