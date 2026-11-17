# Logs: evento da especificação → logger → código

Issue 03.5. Referência: `docs/especificacao.md`, seção "Observabilidade e Logs" e "Exemplo Completo de Sessão".

Formato de toda linha (`forca/main.py`, `LOG_FORMAT`): `2026-11-17 14:51:23,411 INFO    [Player] texto`, isto é, timestamp, nível e módulo.

## Onde cada saída aparece

| Destino | O que mostra | Como |
|---|---|---|
| Tela | nível escolhido (`--log-level`, padrão `INFO`, muda com `/log`) **mais** tudo de `[CLI]` e `[Game]` em qualquer nível | `ScreenFilter` / `setup_logging` (`forca/main.py`) |
| Arquivo (`--log-file`) | **tudo**: `DEBUG`, `[Wire]` e `[RDV]` com o JSON bruto | `add_log_file` (`forca/main.py`) |

Testes: `tests/test_main.py` (`test_screen_shows_info_and_file_gets_everything`, `test_cli_and_game_always_reach_the_screen`, `test_set_level_at_runtime_shows_debug_without_restart`, `test_log_format_has_time_level_and_module`).

## JSON bruto em DEBUG

| Tráfego | Logger | Onde |
|---|---|---|
| Peer → peer, enviado (`->`) | `Wire` | `forca/peer_connection.py:113` (único ponto de escrita) |
| Peer → peer, recebido (`<-`) | `Wire` | `forca/peer_connection.py:143` (antes do decode: linha que não é JSON também aparece) |
| Rendezvous, enviado e recebido | `RDV` | `forca/rendezvous_connection.py:148` e `:169` |

## Eventos da especificação

| Exemplo da especificação | Logger | Nível | Código | Teste |
|---|---|---|---|---|
| `registered alice@CIC as IP:8081 (ttl=7200)` | `RDV` | INFO | `rendezvous_connection.py:76` | `test_rendezvous.py` |
| `Inbound connected: bob@CIC (features=hangman)` | `PeerServer` | INFO | `peer_connection.py:473` | `test_peer_connection.py` |
| `Duplicate connection with carol@CIC — keeping outbound (lower peer_id)` | `PeerServer` | INFO | `peer_connection.py:444` | `test_peer_connection.py` |
| `bob@CIC RTT=41.7 ms (avg 43.2 ms)` | `KeepAlive` | DEBUG | `keep_alive.py:91` | `test_keep_alive.py` |
| `carol@CIC missed 3 PINGs — marking STALE` | `KeepAlive` | WARNING | `keep_alive.py:102` | `test_keep_alive.py` |
| `Game alice@CIC/3f9a2c1b created (word_length=6, lives=6)` | `Host` | INFO | `game_host.py:96` | `test_game_host.py` |
| `bob@CIC joined (2/4)` | `Host` | INFO | `game_host.py:198` (`rejoined` no rejoin: `:192`) | `test_game_host.py` |
| `Turn: bob@CIC (timeout 30 s)` | `Host` | INFO | `game_host.py:316` | `test_game_host.py` |
| `GUESS bob@CIC letter=n → correct, masked=_ana_a` | `Host` | INFO | `game_host.py:235` | `test_game_host.py` |
| `Turn timeout for carol@CIC — skipping` | `Host` | INFO | `game_host.py:306` | `test_game_host.py` |
| `Player carol@CIC STALE — removed from game` | `Host` | WARNING | `game_host.py:258` | `test_game_host.py` |
| `STATE seq=4 applied: _ana_a lives=5 turn=carol@CIC` (com ` (você)` quando a vez é do próprio peer, como no Exemplo de Sessão) | `Player` | INFO | `game_player.py:184` | `test_game_player.py` |
| `STATE seq=3 ignored (already at seq=4)` | `Player` | DEBUG | `game_player.py:176` | `test_game_player.py` |
| `GAME_OVER WON word=banana winner=bob@CIC — hash OK` | `Player` | INFO | `game_player.py:217` | `test_game_player.py` |
| `Host alice@CIC unreachable — game aborted` | `Player` e `Game` | WARNING | `game_player.py:236-237` (o `[Game]` é o que a tela sempre mostra) | `test_game_player.py` |
| `Game alice@CIC/7d2e9f01 finished: WON by bob@CIC` (Exemplo de Sessão) | `Host` | INFO | `game_host.py:352` | `test_game_host.py` |
| `Partidas abertas:` (Exemplo de Sessão) | `CLI` | INFO | `cli.py:253` | `test_cli_game.py` |

Níveis que a especificação não fixa: RTT e `STATE ignored` ficam em DEBUG (saem a cada PING ou STATE repetido e poluiriam a tela em INFO).

## Verificação (17/11/2026)

- `python -m pytest -q`: 325 passed.
- Partida real entre dois processos `forca.main` (alice host, bob jogador, palavra `casa`, Rendezvous falso em 127.0.0.1; o público não serve para dois peers do mesmo IP atrás de NAT): `/create`, `/games`, `/join`, `/start`, `/guess a`, `/guess a` (recusada), `/guess e` (errada), `/word casa` → `GAME_OVER WON`, `hash OK`. Linhas `[Host]`, `[Player]`, `[Game]` e `[CLI]` idênticas às do Exemplo de Sessão. No arquivo, em cada peer: `[Wire] ->`/`<-` de HELLO, HELLO_OK, PING, PONG, GAME_LIST, GAME_LIST_OK, JOIN, JOIN_OK, GAME_START, STATE, GUESS, GUESS_RESULT, GAME_OVER, BYE e BYE_OK, mais `[RDV] ->`/`<-`; `Duplicate connection` e `RTT=` também apareceram.
- **Não exercitados em execução real** (só por teste unitário): `missed 3 PINGs`, `STALE — removed from game`, `Turn timeout`, `Host … unreachable` e `ERROR`. Dependem de `kill -9`/inatividade (cenários 6, 7 e 9, issues 04.3/04.4).

## Revisão com o `spec-reviewer` (17/11/2026)

Nenhuma divergência de texto, argumento ou logger. Pontos levantados e decisão:

- `RTT=` em DEBUG: a especificação não fixa o nível; fica em DEBUG (aparece no arquivo e com `/log DEBUG`).
- `unreachable — game aborted` sai em `[Player]` (texto da especificação) e em `[Game]` (garante a tela em qualquer nível): duas linhas de propósito.
- `[Wire]` não registra mensagem cujo `write`/`drain` falhou, nem linha truncada ou acima do limite (só um WARNING). Mudar isso é comportamento da rede (fora do escopo da 03.5); para mensagens válidas não há lacuna.
