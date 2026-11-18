# Testes e evidências

Gerado em 17/11/2026 sobre o commit `f9a25ab` (branch `feat/04-integracao`). A contagem de testes foi atualizada em 18/11/2026 (368, após o bônus de chat); a saída abaixo é a **saída literal** dos scripts; para reproduzir, veja a seção seguinte.

## Como reproduzir

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
python -m pytest -q                    # 368 testes (unitários e de rede em 127.0.0.1)
python tools/scenarios.py              # cenários 1 a 10, processos reais, ~25 s; --list / --only 7a,8
python tools/bot_check.py all          # cenário 11 contra o bot oficial; precisa de internet, ~5 min
```

`tools/scenarios.py` sobe um Rendezvous local (`tools/rdv_local.py`) e `python -m forca.main` para alice, bob e carol (tempos curtos: PING 1 s, turno 6 s), manda comandos pela entrada de cada peer e **confere as linhas que a especificação espera**. Cada peer grava `logs/cenarios/<cenário>/<nome>.log` (DEBUG, com o JSON bruto) e a tela fica em `tela.txt`. Os logs não vão para o repositório (`.gitignore`).

## Cenários 1 a 10 (peers reais, Rendezvous local)

```
PASSOU  cenário 1: malha de descoberta (3 peers, /conn, kill -9)  (3.0 s)
   ✓ alice: /conn mostra exatamente 2 conexões
   ✓ bob: /conn mostra exatamente 2 conexões
   ✓ carol: /conn mostra exatamente 2 conexões
   ✓ alice: uma conexão por vizinho (sem duplicadas)
   ✓ RTT preenchido no /conn
   ✓ alice marca carol STALE após o kill -9
   ✓ bob marca carol STALE após o kill -9
   ✓ alice: /conn deixa de listar carol

PASSOU  cenário 2: partida completa com vitória  (0.5 s)
   ✓ bob: GAME_OVER WON, winner=bob e hash OK
   ✓ bob: placar com bob=3
   ✓ bob: STATE com seq 1..N sem falhas ([1, 2, 3])
   ✓ carol: GAME_OVER WON, winner=bob e hash OK
   ✓ carol: placar com bob=3
   ✓ carol: STATE com seq 1..N sem falhas ([1, 2, 3])

PASSOU  cenário 3: partida com derrota  (0.7 s)
   ✓ bob: GAME_OVER LOST, palavra revelada, winner=None, hash OK
   ✓ carol: GAME_OVER LOST, palavra revelada, winner=None, hash OK

PASSOU  cenário 4: jogada fora do turno  (2.0 s)
   ✓ carol recebe not_your_turn
   ✓ nenhum STATE novo foi gerado (seq continua [1])

PASSOU  cenário 5: letra repetida e palpite de palavra  (1.6 s)
   ✓ letter_already_used
   ✓ jogada recusada não gera STATE nem consome o turno
   ✓ /word errado custou 1 vida (5), nada foi revelado e o turno passou ao bob
   ✓ bob: /word certo encerra a partida com WON
   ✓ carol: /word certo encerra a partida com WON

PASSOU  cenário 6: timeout de turno  (6.4 s)
   ✓ host: Turn timeout ... skipping
   ✓ STATE indica timeout (carol vê)
   ✓ o turno passou para carol e as vidas continuam 6

PASSOU  cenário 7a: queda de jogador com kill -9  (0.6 s)
   ✓ alice remove carol da partida
   ✓ bob recebe o STATE da remoção
   ✓ bob: a partida segue só com bob
   ✓ a partida continua: bob joga e a jogada é aceita

PASSOU  cenário 7b: queda de jogador congelado (SIGSTOP, 3 PINGs perdidos)  (4.3 s)
   ✓ alice: missed 3 PINGs — marking STALE
   ✓ alice remove carol da partida
   ✓ bob recebe o STATE da remoção
   ✓ bob: a partida segue só com bob
   ✓ a partida continua: bob joga e a jogada é aceita

PASSOU  cenário 8: reconexão de jogador (rejoin)  (0.8 s)
   ✓ carol removida
   ✓ carol reconecta em alice
   ✓ carol: JOIN_OK com rejoin=true
   ✓ alice: carol rejoined
   ✓ carol recebe o STATE corrente
   ✓ carol volta ao FIM do rodízio

PASSOU  cenário 9: queda do host  (0.6 s)
   ✓ bob: Host alice unreachable — game aborted
   ✓ carol: Host alice unreachable — game aborted
   ✓ bob volta a IDLE

PASSOU  cenário 10a: /quit no host com partida RUNNING  (0.5 s)
   ✓ alice: o processo termina sozinho com código 0 (código=0)
   ✓ alice (host RUNNING): GAME_OVER ABORTED → BYE → UNREGISTER, nessa ordem (linhas [49, 51, 59] do log)
   ✓ bob volta a IDLE

PASSOU  cenário 10b: /quit em jogador durante a partida  (0.5 s)
   ✓ bob: o processo termina sozinho com código 0 (código=0)
   ✓ bob (jogador em partida): LEAVE → BYE → UNREGISTER (linhas [44, 45, 55] do log)

PASSOU  cenário 10c: /quit sem partida  (0.2 s)
   ✓ bob: o processo termina sozinho com código 0 (código=0)
   ✓ bob (sem partida): BYE → UNREGISTER (linhas [33, 41] do log)
   ✓ o UNREGISTER removeu o bob do Rendezvous
   ✓ alice e carol continuam registradas
   ✓ o Rendezvous recebeu o UNREGISTER

PASSOU  cenário 10d: Ctrl+C no host com partida RUNNING  (0.5 s)
   ✓ alice: o processo termina sozinho com código 0 (código=0)
   ✓ Ctrl+C (SIGINT) no host tem a mesma ordem do /quit (linhas [51, 53, 61] do log)

14/14 cenários passaram. Logs em logs/cenarios/
```

Notas de leitura:

- **Cenário 7.** Em `127.0.0.1`, o `kill -9` faz o sistema operacional fechar o socket e o vizinho vê a queda na hora; isso **não** exercita a contagem de 3 PINGs. Por isso há duas variantes: **7a** (`kill -9`) e **7b** (`SIGSTOP`: o processo congela, o socket continua aberto, e só o `KeepAlive` percebe, após `missed 3 PINGs — marking STALE`). A especificação lista os dois modos de detecção ("PONG ausente ×3 ou socket fechado").
- **Cenário 8.** Carol volta como **processo novo** na mesma porta, reconecta e envia `/join`; recebe `rejoin: true`, o `STATE` corrente e fica no **fim** do rodízio (decisão 3 do contrato).
- **Cenário 10.** A ordem é comprovada pelo log `Wire` do próprio processo (número da linha crescente): `GAME_OVER ABORTED` (host) ou `LEAVE` (jogador), depois `BYE`, depois `[RDV] unregistered`. No 10c confere-se o estado do Rendezvous (o registro do bob some). O 10d repete o 10a com `SIGINT` (Ctrl+C).
- Todos os processos terminam com código 0 e não sobra processo órfão.

## Cenário 11: interoperabilidade

O nosso cliente como **jogador** contra o bot oficial dos monitores (`bot@CIC`, `45.171.101.167:8081`, Rendezvous público), em 17/11/2026:

```
PASSOU  cenário 11 (win, 2 jogador(es)) contra bot@CIC
   ✓ a partida terminou para todos os jogadores
   ✓ GAME_OVER WON recebido por todos (2 mensagens)
   ✓ winner é um dos nossos jogadores
   ✓ o word_hash do GAME_START confere (hash OK)
   ✓ nenhum STATE descartado por seq fora de ordem
   ✓ nenhum aviso 'host cheated: hash mismatch'
   ✓ STATE aplicados pelo nosso jogador (seq [1]..[5])
PASSOU  cenário 11 (lose, 1 jogador(es)) contra bot@CIC
   ✓ a partida terminou para todos os jogadores
   ✓ GAME_OVER LOST com winner=None e palavra revelada
   ✓ o word_hash do GAME_START confere (hash OK)
   ✓ nenhum STATE descartado por seq fora de ordem
   ✓ nenhum aviso 'host cheated: hash mismatch'
   ✓ STATE aplicados pelo nosso jogador (seq [1]..[7])
PASSOU  cenário 11 (timeout) contra bot@CIC
   ✓ o bot enviou BYE reason:"idle" após os timeouts
   ✓ respondemos BYE_OK com o mesmo msg_id
   ✓ STATE com timeout:true anunciado (5x no log)
   ✓ a perda de vez não custou vida
   ✓ voltar à partida é recusado pelo bot (Cannot join bot@CIC/6678f990: game_running)
```

O JSON bruto trocado com o bot ficou em `logs/bot/*.wire.log` (não versionado). Pontos que o teste comprova: `HELLO`/`HELLO_OK` e `PING`/`PONG` com o bot; `GAME_LIST_OK`, `JOIN_OK`, `GAME_START` com `word_hash`, `STATE` com `seq` crescente, `GUESS_RESULT`; `GAME_OVER` com `word`, `winner` (`null` na derrota) e `scores`, e o hash da palavra conferindo; e a política do bot para jogador inativo (3 timeouts sem custo de vida, depois `BYE reason:"idle"`, que respondemos com `BYE_OK` do mesmo `msg_id`, e `JOIN_ERR game_running` ao tentar voltar).

**Não foi possível testar:** o cliente de referência `pyp2p-forca` nunca foi disponibilizado. Portanto **host nosso com um cliente de terceiros como jogador não foi exercitado**; o papel de host só foi testado contra os nossos próprios jogadores (cenários 2 a 10).

## Critérios de avaliação (1 a 8)

| # | Critério | Onde está | O que cobre (testes e evidência) |
|---|---|---|---|
| 1 | Rendezvous | `forca/rendezvous_connection.py`, `forca/p2p_client.py` | `tests/test_rendezvous.py` (REGISTER/DISCOVER/UNREGISTER, `bad_port`, bloqueio, timeout, filtro do próprio peer, `/peers *` sem `namespace`); `tests/test_p2p_client.py` (refresh do TTL, `peer_not_registered`, nenhum laço sem pausa, UNREGISTER no `stop()`). Real: REGISTER/DISCOVER/UNREGISTER no servidor público. |
| 2 | Conexão TCP | `forca/peer_connection.py`, `forca/keep_alive.py`, `forca/peer_table.py` | `tests/test_peer_connection.py` (HELLO com `features`, desempate de duplicadas com uma conexão por lado, linha de 32 KiB, `bad_json`, `BYE`), `tests/test_keep_alive.py` (RTT, 3 PINGs ⇒ `STALE`), `tests/test_peer_table.py` (estados, reconciliação, backoff). Cenários 1, 7b. |
| 3 | Lobby | `forca/game_host.py`, `forca/message_router.py`, `forca/cli.py` | `tests/test_game_host.py` (`GAME_LIST_OK`, `JOIN_OK`, os cinco `JOIN_ERR`, `LEAVE`), `tests/test_cli_game.py`, `tests/test_message_router.py`. Real: `/games` e `/join` contra o bot. |
| 4 | Partida como host | `forca/game_host.py`, `forca/hangman.py` | `tests/test_game_host.py` e `tests/test_hangman.py` (`word_hash`, `seq`, validação de `GUESS`, turnos, timeout, `scores`). Cenários 2 a 6. |
| 5 | Partida como jogador | `forca/game_player.py` | `tests/test_game_player.py` (descarte por `seq`, `word_hash`, `rejoin`). Cenário 11 (`hash OK`, `seq` sem falhas). |
| 6 | Tolerância a falhas | `game_host.py`, `game_player.py`, `peer_table.py`, `p2p_client.py` | Cenários 7a, 7b, 8, 9 e 10a a 10d. |
| 7 | Interoperabilidade | tudo | Cenário 11 como jogador contra o bot oficial. **Parcial:** sem o cliente de referência, o papel de host não foi testado contra terceiros. |
| 8 | CLI e logs | `forca/cli.py`, `forca/main.py` | `tests/test_cli.py`, `tests/test_cli_game.py`, `tests/test_main.py`; os textos de log da seção "Observabilidade" foram conferidos contra o código pelo `spec-reviewer` (os 15 exemplos existem com o texto esperado). |

## Desvios conscientes e limitações

- **Linha que não é JSON antes do HELLO** só fecha a conexão, sem `ERROR` (contrato 5.1): o vizinho ainda não tem `peer_id` e um `ERROR` sairia sem `dst`. A especificação pede `ERROR` + fechar; depois do HELLO fazemos exatamente isso (`on_bad_line`).
- **Conexão em `127.0.0.1` para vizinho com o mesmo IP público** (regra do `P2PClient`): o Rendezvous divulga o IP público e muitos roteadores não alcançam o próprio IP público por dentro. Sem isso, 3 peers na mesma máquina não fecham a malha pelo servidor público.
- **NAT entre máquinas:** peers em redes diferentes só se alcançam com a porta de escuta acessível; o Rendezvous não ajuda nisso. Não foi testado entre máquinas diferentes.
- **RTT** é registrado em `INFO` (`[KeepAlive] bob@CIC RTT=41.7 ms (avg 43.2 ms)`), uma linha por vizinho a cada `ping_interval`.
- **Pendências menores já identificadas, fora da parte A** (a repassar ao dono de cada módulo): a mensagem `Host ... unreachable — game aborted` sai duas vezes (loggers `Player` e `Game`); a linha `STATE seq=N ignored` está em `DEBUG` (não aparece na tela com o nível padrão). O `/reconnect` e o "É a sua vez!" num `STATE` final já foram corrigidos (PR #9).
- **Bônus:** o chat na partida foi implementado (PR #11, testes em `tests/test_game_wiring.py`); migração de host, modo competitivo e múltiplas partidas não fazem parte desta entrega.
- Os cenários automatizados usam tempos curtos (PING 1 s, turno 6 s) para rodar em segundos; os valores padrão da especificação (30 s) foram exercitados contra o bot.
