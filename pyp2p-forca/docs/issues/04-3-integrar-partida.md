# [04.3] Integração 2: partida completa (cenários 2 a 6)

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | integração |
| **Prazo** | Ter 17/11 |
| **Branch** | `feat/04-3-integrar-partida` |
| **Depende de** | [04.2](04-2-integrar-malha.md), [02.4](02-4-host-jogadas.md), [02.6](02-6-game-player.md), [03.4](03-4-cli-jogo.md) |
| **Etiquetas** | `todos` `integração` `Sprint Backlog` |
| **Especificação** | Cenários de Teste Mínimos (2 a 6); Exemplo Completo de Sessão |

## Contexto atual

Com a malha estável, B e C encaixam o jogo: host cria, dois jogadores entram, jogam e a partida termina.

## Objetivo

Passar os cenários 2 (vitória), 3 (derrota), 4 (fora do turno), 5 (letra repetida e `/word`) e 6 (timeout).

## Dentro do escopo

- [ ] Rodar cada cenário com 3 peers locais; registrar saída e logs em `docs/testes.md`
- [ ] Comparar o log de uma partida com o "Exemplo Completo de Sessão" da especificação, mensagem por mensagem
- [ ] Conferir `GAME_OVER` (`winner`, `scores`, hash `OK`) e `STATE` (`seq` sem falhas)
- [ ] Corrigir falhas por PR pequeno ao dono do módulo
- [ ] Opcional: automatizar um destes cenários como teste `asyncio` com dois `P2PClient` em `127.0.0.1`

## Fora do escopo

- Falhas e quedas (04.4)

## Critérios de aceite

- [ ] Cenários 2 a 6 passam, com evidência nos logs
- [ ] Nenhum `STATE` é gerado por jogada rejeitada
- [ ] O hash confere em todas as partidas

## Itens a estudar

- Ler o exemplo de sessão da especificação com a ferramenta de diff do seu editor ao lado do seu log

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/04-3-integrar-partida.md`. Releia na `docs/especificacao.md` as seções: Cenários de Teste Mínimos (2 a 6), Exemplo Completo de Sessão. Entre em plan mode e proponha o plano para a issue 04.3. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
