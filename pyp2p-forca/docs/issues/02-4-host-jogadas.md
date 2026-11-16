# [02.4] GameHost (3/4): GUESS, turnos, GAME_OVER e pontuação

| | |
|---|---|
| **Responsável** | Parte B: Jogo |
| **Área** | jogo |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/02-4-host-jogadas` |
| **Depende de** | [02.3](02-3-host-start.md) |
| **Etiquetas** | `parte-B` `jogo` `Sprint Backlog` |
| **Especificação** | GUESS / GUESS_RESULT; GAME_OVER; Regras do jogo; Máquina de estados (host) |

## Contexto atual

É o coração do jogo: o host valida cada jogada, passa o turno, atualiza vidas e encerra a partida.

## Objetivo

Implementar `on_guess`, o fim de partida, `cancel`/`shutdown` e a volta a `IDLE`.

## Dentro do escopo

- [ ] `on_guess` valida: partida `RUNNING`, vez de quem jogou, exatamente `letter` ou `word`; rejeição devolve `GUESS_RESULT accepted:false` com `not_your_turn`, `letter_already_used`, `invalid_letter`, `invalid_word` ou `game_not_running`, **sem consumir o turno e sem gerar `STATE`**
- [ ] Aceita: `GUESS_RESULT accepted:true, correct:<bool>` ao autor e um `STATE` a **todos** os jogadores; o turno passa ao próximo **independente de acerto**
- [ ] Fim: `WON` quando `masked` não tem `_`; `LOST` quando `lives == 0`; `GAME_OVER` com `word`, `winner` (quem completou; `null` se `LOST`) e `scores` (letras reveladas por jogador; `/word` certo soma as letras que faltavam)
- [ ] `cancel()`/`shutdown()`: `GAME_OVER ABORTED reason:"host_shutdown"` aos jogadores e volta a `IDLE`
- [ ] Após o fim, `GAME_LIST_OK` informa `FINISHED` por 60 s e depois a partida some
- [ ] Logs: `[Host] GUESS bob@CIC letter=n → correct, masked=_ana_a` e `[Host] Game ... finished: WON by bob@CIC`
- [ ] Testes com `Sender` falso: vitória por letras, vitória por palavra, derrota, fora do turno, letra repetida, `/word` errado custa vida, rejeição não gera `STATE`

## Fora do escopo

- Timeout de turno e quedas de jogador (02.5)

## Critérios de aceite

- [ ] Cenários 2 a 5 da especificação passam contra o `GameHost` com `Sender` falso
- [ ] Uma jogada rejeitada não altera `seq`, vidas nem turno
- [ ] `scores` soma corretamente (inclui o `/word` vencedor)
- [ ] `GAME_OVER LOST` traz `winner: null` e a palavra revelada

## Itens a estudar

- `asyncio.sleep` + tarefa para expirar o `FINISHED` em 60 s sem bloquear
- Diferença entre `result` (`WON`/`LOST`/`ABORTED`) e `reason` (só no `ABORTED`)

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/02-4-host-jogadas.md`. Releia na `docs/especificacao.md` as seções: GUESS / GUESS_RESULT, GAME_OVER, Regras do jogo, Máquina de estados (host). Entre em plan mode e proponha o plano para a issue 02.4. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
