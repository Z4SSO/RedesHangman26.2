# [02.3] GameHost (2/4): /start, GAME_START e STATE

| | |
|---|---|
| **Responsável** | Parte B: Jogo |
| **Área** | jogo |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/02-3-host-start` |
| **Depende de** | [02.2](02-2-host-lobby.md) |
| **Etiquetas** | `parte-B` `jogo` `Sprint Backlog` |
| **Especificação** | GAME_START; STATE; Regras do jogo (turnos) |

## Contexto atual

Com ao menos um jogador inscrito, o host dispara a partida: manda `GAME_START` a cada jogador e logo em seguida o primeiro `STATE`.

## Objetivo

Implementar `start()` e a difusão de `STATE` com `seq` correto.

## Dentro do escopo

- [ ] `start()`: exige pelo menos 1 jogador (`ValueError` caso contrário); `OPEN` → `RUNNING`
- [ ] `GAME_START` a cada jogador: `players` (ordem definitiva dos turnos), `lives`, `word_length`, `word_hash` (da palavra normalizada), `turn_timeout`
- [ ] `STATE seq=1` logo depois, com `turn` = primeiro jogador, `masked` todo `_`, `wrong_letters: []`, `last_guess: null`
- [ ] Função única de difusão de `STATE` que incrementa o `seq` a cada chamada (1, 2, 3, ...)
- [ ] Log `[Host] Turn: bob@CIC (timeout 30 s)`
- [ ] Testes: `start` com 0 jogadores, ordem das mensagens, `seq` crescente, hash correto

## Fora do escopo

- Jogadas e fim de partida (02.4)
- Timeout de turno (02.5)

## Critérios de aceite

- [ ] `/start` sem jogadores é recusado localmente com mensagem clara
- [ ] Cada jogador recebe `GAME_START` e depois `STATE seq=1`
- [ ] O `word_hash` de `casa` é o SHA-256 esperado
- [ ] O `seq` nunca repete nem pula

## Itens a estudar

- Por que o host manda um `STATE` completo (não um delta): o jogador pode ter perdido mensagens
- Round-robin com índice e módulo

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/02-3-host-start.md`. Releia na `docs/especificacao.md` as seções: GAME_START, STATE, Regras do jogo (turnos). Entre em plan mode e proponha o plano para a issue 02.3. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
