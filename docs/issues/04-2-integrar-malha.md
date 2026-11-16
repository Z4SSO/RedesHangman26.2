# [04.2] Integração 1: malha de descoberta (cenário 1)

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | integração |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/04-2-integrar-malha` |
| **Depende de** | [01.7](01-7-p2p-client.md), [03.3](03-3-cli-rede.md) |
| **Etiquetas** | `todos` `integração` `Sprint Backlog` |
| **Especificação** | Cenários de Teste Mínimos (1) |

## Contexto atual

Primeira vez que os módulos de A e C rodam juntos. É o ponto em que a maioria dos erros de integração aparece, por isso vale a pena fazer **cedo**, antes de ter o jogo pronto.

## Objetivo

Três peers no mesmo namespace se registram, se descobrem e mantêm exatamente duas conexões cada.

## Dentro do escopo

- [ ] Subir 3 peers com `tools/run_local.py` e conferir `/conn` em cada um: duas conexões, sem duplicadas, RTT preenchido
- [ ] Matar um peer com `kill -9`: os outros o marcam `STALE` após 3 PINGs e `/conn` deixa de listá-lo
- [ ] Corrigir o que quebrar (no módulo do dono, por PR pequeno)
- [ ] Escrever o resultado em `docs/testes.md` (comando, saída, data)

## Fora do escopo

- Partida (04.3)

## Critérios de aceite

- [ ] `/conn` mostra exatamente 2 conexões em cada um dos 3 peers
- [ ] Nenhuma conexão duplicada, mesmo reiniciando os peers em ordens diferentes
- [ ] O peer encerrado com `kill -9` some da lista em até 3 × `ping_interval`

## Itens a estudar

- Usar `ping_interval` curto (ex.: `--ping-interval 5` via config) só para testar

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/04-2-integrar-malha.md`. Releia na `docs/especificacao.md` as seções: Cenários de Teste Mínimos (1). Entre em plan mode e proponha o plano para a issue 04.2. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
