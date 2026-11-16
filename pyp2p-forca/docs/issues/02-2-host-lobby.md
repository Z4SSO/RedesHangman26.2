# [02.2] GameHost (1/4): criar partida e lobby (GAME_LIST, JOIN, LEAVE)

| | |
|---|---|
| **Responsável** | Parte B: Jogo |
| **Área** | jogo |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/02-2-host-lobby` |
| **Depende de** | [02.1](02-1-hangman.md) |
| **Etiquetas** | `parte-B` `jogo` `Sprint Backlog` |
| **Especificação** | GAME_LIST / GAME_LIST_OK; JOIN / JOIN_OK / JOIN_ERR; LEAVE / LEAVE_OK; Identidade e Escopo |

## Contexto atual

Antes da partida começar, o host anuncia a partida aos vizinhos (`GAME_LIST`), aceita e recusa jogadores (`JOIN`) e deixa jogadores saírem (`LEAVE`).

## Objetivo

Implementar `create`, `describe` e os handlers `on_game_list`, `on_join`, `on_leave` do `GameHost`, testando com um `Sender` falso (sem rede).

## Dentro do escopo

- [ ] `create(word, max_players)`: normaliza a palavra, gera `game_id` (`<host>/<8 hex>`), status `OPEN`; log `[Host] Game alice@CIC/3f9a2c1b created (word_length=6, lives=6)`
- [ ] `describe()`: o item de `games[]` (`game_id`, `host`, `status`, `players`, `max_players`, `lives`, `word_length`)
- [ ] `on_game_list`: responde `GAME_LIST_OK` com `games: []` quando não há partida (mesmo `msg_id`)
- [ ] `on_join`: `JOIN_OK` (com `players` na ordem de entrada e `rejoin: false`) ou `JOIN_ERR` com `unknown_game`, `game_full`, `game_running`, `game_finished`, `already_joined`; log `[Host] bob@CIC joined (2/4)`
- [ ] `on_leave`: remove o jogador e responde `LEAVE_OK`
- [ ] O host **não** é jogador; checagem de exclusão mútua (`RuntimeError` se já estiver numa partida)
- [ ] Testes com `Sender` falso (uma lista) cobrindo cada motivo de `JOIN_ERR`

## Fora do escopo

- `/start` e partida em andamento (02.3 e 02.4)
- `rejoin` durante `RUNNING` (02.5)

## Critérios de aceite

- [ ] Cada motivo de `JOIN_ERR` da especificação é produzido pelo caso certo
- [ ] `GAME_LIST_OK` de um peer sem partida tem `games: []`
- [ ] Resposta sempre repete o `msg_id` da requisição e inverte `src`/`dst`
- [ ] A mesma pessoa mandar `JOIN` duas vezes resulta em `already_joined`

## Itens a estudar

- `secrets.token_hex(4)` ou `uuid.uuid4().hex[:8]` para o sufixo do `game_id`
- Injeção de dependência: por que o `GameHost` recebe o `Sender` em vez de importar a rede

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/02-2-host-lobby.md`. Releia na `docs/especificacao.md` as seções: GAME_LIST / GAME_LIST_OK, JOIN / JOIN_OK / JOIN_ERR, LEAVE / LEAVE_OK, Identidade e Escopo. Entre em plan mode e proponha o plano para a issue 02.2. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
