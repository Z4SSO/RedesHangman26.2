# [02.6] GamePlayer: entrar, jogar, aplicar STATE e reagir à queda do host

| | |
|---|---|
| **Responsável** | Parte B: Jogo |
| **Área** | jogo |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/02-6-game-player` |
| **Depende de** | [02.1](02-1-hangman.md) |
| **Etiquetas** | `parte-B` `jogo` `Sprint Backlog` |
| **Especificação** | JOIN / JOIN_OK / JOIN_ERR; STATE; GAME_OVER; Máquina de estados (jogador); Tratamento de falhas |

## Contexto atual

Do outro lado da partida está o jogador: manda `JOIN`, aplica os `STATE` recebidos, envia palpites e confere se o host não trapaceou.

## Objetivo

Implementar `GamePlayer` completo conforme o contrato (seção 5.7), testado com um `Sender` falso.

## Dentro do escopo

- [ ] `join(host_peer_id, game_id)`: envia `JOIN`; `JOIN_OK` → `JOINED`; `JOIN_ERR` → `IDLE` com mensagem ao usuário
- [ ] `on_game_start` guarda `word_hash`, `lives`, `players`, `turn_timeout`; `on_state` aplica só se `seq` > último (senão descarta e registra `[Player] STATE seq=3 ignored (already at seq=4)` em DEBUG); log `[Player] STATE seq=4 applied: _ana_a lives=5 turn=carol@CIC`
- [ ] `guess_letter`/`guess_word`: envia `GUESS`; avisa o usuário no `GUESS_RESULT` rejeitado (`not_your_turn`, ...)
- [ ] `on_game_over`: calcula `sha256(word)` e compara com o `word_hash`; diferente → `WARNING host cheated: hash mismatch`; log `[Player] GAME_OVER WON word=banana winner=bob@CIC — hash OK`; volta a `IDLE`
- [ ] `on_peer_stale(host)`: `[Game] Host alice@CIC unreachable — game aborted` e volta a `IDLE` (sem tentar virar host)
- [ ] Ao reconectar a um host que a partida estava `RUNNING`, reenviar `JOIN` (rejoin)
- [ ] `status_lines()` com o formato mínimo do `/status` (palavra, vidas, erradas, jogadores, vez de quem)
- [ ] Testes: `seq` repetido/menor descartado, hash divergente, host que cai, `JOIN_ERR`

## Fora do escopo

- Migração de host (bônus 05.1)

## Critérios de aceite

- [ ] `STATE` com `seq` menor ou igual ao último é ignorado sem alterar o estado
- [ ] Hash adulterado gera `WARNING` e a partida termina normalmente
- [ ] Queda do host leva a `IDLE` e não deixa estado pendurado
- [ ] `/status` mostra todos os campos exigidos pela especificação

## Itens a estudar

- Idempotência e ordenação: por que o `seq` existe
- Como o jogador sabe que é a vez dele (`STATE.turn == meu_peer_id`)

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/02-6-game-player.md`. Releia na `docs/especificacao.md` as seções: JOIN / JOIN_OK / JOIN_ERR, STATE, GAME_OVER, Máquina de estados (jogador), Tratamento de falhas. Entre em plan mode e proponha o plano para a issue 02.6. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
