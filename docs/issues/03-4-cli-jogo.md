# [03.4] CLI (2/2): comandos de jogo e /games

| | |
|---|---|
| **Responsável** | Parte C: CLI e integração |
| **Área** | cli |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/03-4-cli-jogo` |
| **Depende de** | [03.3](03-3-cli-rede.md), [02.2](02-2-host-lobby.md), [02.6](02-6-game-player.md) |
| **Etiquetas** | `parte-C` `cli` `Sprint Backlog` |
| **Especificação** | Interface de Usuário (CLI); GAME_LIST / GAME_LIST_OK; Exibição mínima do /status |

## Contexto atual

Os comandos de jogo ligam a CLI ao `GameHost` e ao `GamePlayer` e aplicam a regra de **uma partida por vez**.

## Objetivo

Implementar `/games`, `/create`, `/start`, `/cancel`, `/join`, `/leave`, `/guess`, `/word`, `/status`.

## Dentro do escopo

- [ ] `/games`: `router.request(GAME_LIST)` a **todos** os vizinhos conectados com a feature `hangman`, em paralelo, consolidando as respostas (formato do exemplo da especificação)
- [ ] `/create <palavra> [max_players]` e `/create --random [max_players]` (sorteia de `words_file`)
- [ ] `/start`, `/cancel`, `/leave`, `/guess <letra>`, `/word <palavra>`
- [ ] `/join <host_peer_id>`: usa `/games` internamente para achar o `game_id` aberto desse host; mensagem clara em `JOIN_ERR`
- [ ] `/status`: delega a `GameHost`/`GamePlayer.status_lines()`
- [ ] Exclusão mútua: criar ou entrar com partida ativa é recusado com mensagem (contrato 5.8)
- [ ] Validação local antes de enviar (letra única `a-z`, palavra válida) e saída `[CLI]`/`[Game]` clara

## Fora do escopo

- Regras do jogo e mensagens (Parte B)

## Critérios de aceite

- [ ] `/games` com 3 vizinhos, um deles com partida aberta, lista só essa partida; vizinho que não responde não trava o comando (timeout)
- [ ] `/create` e `/join` simultâneos no mesmo peer são recusados
- [ ] `/start` sem jogadores mostra erro local
- [ ] `/status` mostra palavra, vidas, erradas, jogadores e vez de quem

## Itens a estudar

- `asyncio.gather` para consultar todos os vizinhos em paralelo
- `random.choice` + leitura de `words.txt` (já normalizado)

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/03-4-cli-jogo.md`. Releia na `docs/especificacao.md` as seções: Interface de Usuário (CLI), GAME_LIST / GAME_LIST_OK, Exibição mínima do /status. Entre em plan mode e proponha o plano para a issue 03.4. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
