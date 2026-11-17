# CONTRATO entre módulos

Este arquivo é o que permite as três pessoas trabalharem em paralelo. **Se algo aqui estiver errado ou faltando, corrija neste arquivo primeiro e avise o grupo**; só depois mude o código. A especificação do professor (`docs/especificacao.md`) manda em caso de dúvida sobre o protocolo.

Legenda: **A** = rede, **B** = jogo, **C** = CLI/roteador/logs.

---

## 1. Convenções gerais

- Python 3.11+, `asyncio`, **só biblioteca padrão** em `forca/` (pytest só para testes).
- Uma mensagem = um objeto JSON em uma linha, UTF-8, terminada em `\n`, no máximo 32 KiB. Toda mensagem é montada com `protocol.new_message()` / `protocol.reply()` e validada com `protocol.validate_envelope()`. **Nunca** monte dicionário de mensagem à mão.
- `peer_id` = `name@namespace`. `game_id` = `<host_peer_id>/<8 hex>`.
- Comparação de `peer_id` para desempate: comparação de strings normal do Python (`a < b`).
- Nenhum handler pode bloquear o event loop (nada de `time.sleep`, `input()` direto, leitura de arquivo grande).
- Uma mensagem inválida **nunca derruba o programa**: responde `ERROR` (ou descarta) e segue.
- Toda tarefa criada com `asyncio.create_task` é guardada e cancelada no `stop()`.
- Erro de leitura/escrita no socket: fecha a conexão e avisa `on_closed`.

## 2. Quem é dono de quê

| Módulo | Dono | Issues |
|---|---|---|
| `protocol.py`, `models.py`, `config.py` | todos (já prontos; mudar só com acordo) | 00.2 |
| `rendezvous_connection.py` | A | 01.1 |
| `peer_table.py` | A | 01.2, 01.6 |
| `peer_connection.py` | A | 01.3, 01.4 |
| `keep_alive.py` | A | 01.5 |
| `p2p_client.py` | A (ciclo de vida) + C (ligações) | 01.7 |
| `hangman.py` | B | 02.1 |
| `game_host.py` | B | 02.2 a 02.5 |
| `game_player.py` | B | 02.6 |
| `message_router.py` | C | 03.2 |
| `game_wiring.py` | C | 01.7 (ligação do jogo à rede) |
| `cli.py` | C | 03.3, 03.4 |
| `main.py`, logging | C | 03.1, 03.5 |

Regra: **não edite módulo de outra pessoa**. Precisa de uma mudança lá? Abra uma issue ou peça no grupo, ou faça um PR pequeno só com isso e marque o dono para revisar.

## 3. Tipos compartilhados (`forca/models.py`)

- `PeerState`: `DISCOVERED`, `CONNECTING`, `CONNECTED`, `STALE`, `GONE`.
- `GameStatus` (host): `IDLE`, `OPEN`, `RUNNING`, `FINISHED`.
- `PlayerState`: `IDLE`, `JOINED`, `PLAYING`.
- `Sender = Callable[[str, dict], Awaitable[bool]]`: envia `msg` ao `peer_id` dado. Devolve `True` se escreveu no socket, `False` se o peer não está conectado. **Nunca levanta** por peer ausente.

## 4. Camadas e fluxo de uma mensagem

```
socket ──► PeerConnection ──(HELLO, PING/PONG, BYE tratados aqui)──┐
              │ resto                                              │
              ▼                                                    │
        MessageRouter.on_message(conn, msg)                        │
              │ validate_envelope → ERROR/descarta                 │
              ▼                                                    │
   GameHost.on_*  /  GamePlayer.on_*   ──► send(peer_id, msg) ─────┘
                                            (= PeerTable.send_to)
```

- **A** (`PeerConnection`) resolve sozinho `HELLO/HELLO_OK`, `PING/PONG` (entrega o PONG ao `KeepAlive`) e `BYE/BYE_OK`. Tudo o mais sobe para o roteador via `on_message(conn, msg)`.
- **C** (`MessageRouter`) valida o envelope, responde `ERROR` quando couber e despacha por `type`.
- **B** só fala com a rede por `Sender` e recebe mensagens por handlers. **B não importa `peer_connection`, `peer_table` nem `asyncio.open_connection`.** Isso é o que o deixa testável sem rede.

## 5. Interfaces

### 5.1 `PeerConnection` (A)

```python
class PeerConnection:
    peer_id: str            # do outro lado, conhecido após o HELLO
    features: list[str]     # anunciadas no HELLO/HELLO_OK do outro lado (o roteador confere "hangman")
    direction: str          # "inbound" | "outbound"
    state: PeerState
    rtt_ms: float | None    # média móvel dos últimos 10 PING/PONG
    missed_pings: int
    async def send(self, msg: dict) -> bool        # False se já caiu; nunca levanta
    async def close(self, reason: str = "shutdown")  # BYE, espera BYE_OK ≤ 2 s, fecha
```

`PeerServer(cfg, on_message, on_closed)` com `start()`, `stop()` e `connect(ip, port) -> PeerConnection | None`.

- Até o `HELLO_OK` (ou, para quem aceita, até o `HELLO`), **nenhuma outra mensagem é aceita**: A descarta e não sobe nada ao roteador. `on_message` só é chamado com a conexão já identificada (`peer_id` e `features` preenchidos).
- `connect()` devolve `None` se a conexão falhar **ou** se perder o desempate de duplicada (seção 6, item 1); nesse caso quem chamou não faz nada, porque já existe uma conexão válida para aquele vizinho.

### 5.2 `PeerTable` (A)

```python
table.subscribe(event, callback)       # callback: async def cb(peer_id: str)
table.state_of(peer_id) -> PeerState | None
table.connected() -> list[PeerConnection]
await table.send_to(peer_id, msg) -> bool      # implementa Sender
await table.broadcast(msg_factory)             # msg_factory(peer_id) -> dict
await table.reconcile(discovered: list[dict])  # resultado do DISCOVER
```

Eventos: `peer_connected`, `peer_stale`, `peer_gone`. **`peer_stale` é o gatilho de falha**: o host remove o jogador; o jogador, se era o host, aborta a partida. `peer_gone` também deve ser tratado como queda.

### 5.3 `RendezvousConnection` (A)

```python
await rdv.register() -> dict           # guarda rdv.public_ip; serve de refresh
await rdv.discover(namespace=None) -> list[dict]   # SEM o próprio peer
await rdv.unregister() -> None
```

Lança `RendezvousError(message)` quando `status == "ERROR"`. Uma conexão TCP por comando. Intervalo mínimo entre chamadas: o `discover_interval` (nunca em laço sem pausa: o servidor bloqueia o IP por 1 min acima de 50 req/min).

### 5.4 `MessageRouter` (C)

```python
router = MessageRouter(local_peer_id, send: Sender)   # send = PeerTable.send_to (o request() envia por ele)
router.register(msg_type: str, handler)        # handler: async def h(conn, msg)
await router.on_message(conn, msg)             # ponto de entrada vindo do PeerServer
await router.on_bad_line(conn, exc)            # linha que não é JSON: responde ERROR bad_json
await router.request(peer_id, msg, timeout=5.0) -> dict | None
```

- **A, ao ler o socket:** linha que não decodifica → `await router.on_bad_line(conn, exc)` e **depois** fecha a conexão (especificação, seção Transporte). Linha válida → `await router.on_message(conn, msg)` só depois do HELLO (5.1).
- **`conn` precisa ter** `peer_id`, `features` (lista) e `async send(msg)`. O roteador não importa `peer_connection`.
- **`request()` devolve a resposta de mesmo `msg_id` ou um `ERROR`** cujo `ref_msg_id` aponta para ele (o `ERROR` tem `msg_id` novo): quem chama confere `reply["type"]`. O `/games` trata `ERROR` como "sem resposta".
- **Limite do Rendezvous na CLI:** `/peers` e `/reconnect` dividem um intervalo mínimo de 5 s entre consultas (o limite é de 50 req/min **por IP**, e os peers do `run_local` saem pelo mesmo IP).
- **Anti-spoof (decisão 21):** mensagem com `src` diferente do `conn.peer_id` é descartada com WARNING, sem resposta. Sem isso qualquer vizinho conectado jogaria no lugar de outro. Uma resposta de `request()` também só vale se vier do peer para quem foi enviada.

`request()` envia e espera a resposta de **mesmo `msg_id`**; usado por `/games` (GAME_LIST → GAME_LIST_OK) e `/join` (JOIN → JOIN_OK/JOIN_ERR). Uma resposta casada com um `request` pendente **não** vai para os handlers.

Tabela de despacho (quem trata cada tipo):

| Tipo | Quem envia | Handler que trata |
|---|---|---|
| `HELLO`, `HELLO_OK`, `PING`, `PONG`, `BYE`, `BYE_OK` | A | interno de A (`PeerConnection`/`KeepAlive`) |
| `ERROR` | qualquer | roteador (só registra no log; nunca responde) |
| `GAME_LIST` | jogador (via CLI) | `GameHost.on_game_list` (responde `GAME_LIST_OK`, mesmo vazio) |
| `GAME_LIST_OK` | host | resposta de `request()` |
| `JOIN` | jogador | `GameHost.on_join` |
| `JOIN_OK`, `JOIN_ERR` | host | `GamePlayer.on_join_ok` / `on_join_err`. O `/join` chama só `player.join()`; **não usar `request()` para o JOIN**, senão o `JOIN_ERR` nunca chega ao `on_join_err` e o jogador fica preso em `JOINED` |
| `LEAVE` | jogador | `GameHost.on_leave` |
| `LEAVE_OK` | host | `GamePlayer.on_leave_ok` |
| `GAME_START` | host | `GamePlayer.on_game_start` |
| `STATE` | host | `GamePlayer.on_state` |
| `GUESS` | jogador | `GameHost.on_guess` |
| `GUESS_RESULT` | host | `GamePlayer.on_guess_result` |
| `GAME_OVER` | host | `GamePlayer.on_game_over` |

Peer que não anunciou `"hangman"` no HELLO (`conn.features`): o roteador não entrega nem aceita mensagens de lobby/partida dele.

**Quem responde `ERROR`:**

- Envelope inválido (`unknown_type`, `bad_request`, `not_for_me`, `bad_json`): o **roteador** (C). `ttl != 1` é descartado em silêncio. `ProtocolError.silent` indica isso.
- Mensagem válida em contexto errado (`invalid_state`, ex.: `GUESS` sem partida, `GAME_START` de quem não é o host do jogador): o **handler de B**, montando com `protocol.make_error(msg, ErrorCode.INVALID_STATE, "...", src=cfg.peer_id)` e enviando por `Sender`. O roteador não conhece o estado do jogo.
- `ERROR` recebido nunca gera resposta.

### 5.5 `Hangman` (B), lógica pura

```python
normalize_word(raw: str) -> str            # a-z, 3..20, sem acentos; ValueError se inválida
word_hash(normalized: str) -> str          # sha256 hex minúsculo
Hangman(word: str, lives: int = 6)
  .masked -> str                           # "b_n_n_"
  .wrong_letters -> list[str]
  .lives -> int; .word_length -> int; .is_won -> bool; .is_lost -> bool
  .guess_letter(letter) -> GuessOutcome    # accepted / correct / reason / revealed
  .guess_word(word) -> GuessOutcome
```

`GuessOutcome.reason` usa os valores de `protocol.GuessRejectReason`. `revealed` é o número de ocorrências reveladas (base da pontuação).

### 5.6 `GameHost` (B)

```python
host = GameHost(cfg, send: Sender, busy: Callable[[], bool] = lambda: False)   # C: busy=lambda: player.active
host.status: GameStatus; host.active: bool; host.game_id: str | None
await host.create(word, max_players=None) -> game_id   # ValueError se palavra inválida
await host.start()          # exige >= 1 jogador (ValueError se não)
await host.cancel()
await host.shutdown()       # no /quit
host.describe() -> dict | None        # item de games[] do GAME_LIST_OK
host.status_lines() -> list[str]      # texto do /status do host; [] se não há partida
# handlers: on_game_list, on_join, on_leave, on_guess   (async, (conn, msg))
# evento:   on_peer_stale(peer_id)
```

- **`/status` (C):** mostrar `host.status_lines()` se não for vazio; senão, `player.status_lines()`. As linhas já vêm com o prefixo `[Game]`. O host também mostra a palavra secreta (só ele a conhece).
- **Timeout de turno:** o host mantém um timer de `turn_timeout` s, reiniciado a cada `STATE`. Ao estourar, passa o turno sem custar vida e difunde `STATE` com `last_guess {"player", "timeout": true}`. O timer é cancelado em todo fim de partida e no `shutdown()`; não há nada para a C ligar.
- `turn_timeout` é **inteiro >= 1**, validado em `config.load_config` (o `GAME_START` exige inteiro no `protocol`, e 0 faria o timer estourar sem parar).

### 5.7 `GamePlayer` (B)

```python
player = GamePlayer(cfg, send: Sender, busy: Callable[[], bool] = lambda: False)   # C: busy=lambda: host.active
player.state: PlayerState; player.active: bool
await player.join(host_peer_id, game_id); await player.leave()
await player.guess_letter(l); await player.guess_word(w)
player.status_lines() -> list[str]          # texto do /status
# handlers: on_join_ok, on_join_err, on_leave_ok, on_game_start, on_state,
#           on_guess_result, on_game_over   (async, (conn, msg))
# eventos:  on_peer_stale(peer_id), on_peer_connected(peer_id)
```

- `join()` já deixa o jogador em `JOINED` (ocupa o peer para a exclusão mútua); `JOIN_ERR` ou host fora do ar voltam a `IDLE`.
- `leave()` envia `LEAVE` e vai a `IDLE` na hora, sem esperar o `LEAVE_OK` (o `/quit` não trava se o host caiu).
- `on_peer_connected(peer_id)`: se o host de uma partida que estava `RUNNING` caiu e voltou **em até 120 s** (`REJOIN_WINDOW`), reenvia `JOIN` (rejoin). Se o peer já virou host ou jogador de outra partida (`busy()`), descarta o rejoin sem enviar nada. **C:** assinar `peer_connected` além de `peer_stale` e `peer_gone`.
- `status_lines()` já devolve as linhas com o prefixo `[Game]`, prontas para imprimir.

### 5.8 Exclusão mútua (um peer = uma partida)

Quem cria uma partida ou entra em uma verifica `not (host.active or player.active)`. Essa checagem fica na **CLI (C)** antes de chamar B, e B repete a checagem (defesa em profundidade) e levanta `RuntimeError("already in a game")`.

Para B conseguir olhar o outro objeto sem importá-lo, **quem liga os objetos (C) passa `busy`**: `host = GameHost(cfg, send, busy=lambda: player.active)` e `player = GamePlayer(cfg, send, busy=lambda: host.active)`. `GameHost.create` e `GamePlayer.join` levantam `RuntimeError` se `self.active or busy()`. Sem o `busy`, a defesa só olha o próprio objeto.

### 5.9 `P2PClient` (A) e a ligação (C)

A **ligação** do jogo é da C e está em `forca/game_wiring.py`; o ciclo de vida do `P2PClient` é da A. O que cada um faz:

```python
# C: forca/game_wiring.py
host, player = wire_game(cfg, table, router)   # cria GameHost/GamePlayer, registra no router (tabela 5.4),
                                               # assina peer_stale/peer_gone/peer_connected e passa busy= (5.8)
```

**A, no `P2PClient`** (a CLI e o `main` usam estes nomes):

```python
client.cfg: Config
client.rdv: RendezvousConnection        # /peers usa client.rdv.discover(namespace | None)
client.table: PeerTable                 # /conn e /rtt usam table.connected()
client.router: MessageRouter            # /games usa router.request(...)
client.host: GameHost; client.player: GamePlayer
await client.start(); await client.stop()
await client.reconcile_now()            # /reconnect: DISCOVER + reconcile imediatos
```

Em `__init__`/`start()`, nesta ordem: `table = PeerTable()` → `router = MessageRouter(cfg.peer_id, table.send_to)` → `host, player = wire_game(cfg, table, router)` → `PeerServer(cfg, on_message=router.on_message, ...)`. Os callbacks de `table.subscribe` são uma **lista** por evento (o `wire_game` assina `peer_stale` duas vezes: host e jogador).

`stop()` segue a seção 8: `await host.shutdown()` e `await player.leave()` **antes** do `BYE`. O `main` chama `client.stop()` no `finally`, inclusive depois de `Ctrl+C` e de `/quit`.

`PeerConnection` (5.1) precisa expor `peer_id`, `features`, `direction`, `state`, `rtt_ms` e `send`: a CLI e o roteador leem esses atributos.

## 6. Decisões já tomadas (onde a especificação deixa margem)

Se o professor responder diferente, altere aqui e avise.

1. **Desempate de conexão duplicada:** mantém-se a conexão aberta pelo peer de **menor** `peer_id`. Localmente: se `meu_id < id_remoto`, vale a minha conexão de saída e fecho a de entrada com `BYE reason:"duplicate"`; senão vale a de entrada.
2. **`/cancel`** envia `GAME_OVER result:"ABORTED" reason:"host_shutdown"`.
3. **Jogador que volta** (`rejoin:true`) vai para o **fim** do rodízio.
4. **`JOIN_OK.players`** inclui o jogador que acabou de entrar, na ordem de entrada.
5. **Timeout de turno:** `STATE.last_guess = {"player": "<quem perdeu a vez>", "timeout": true}` e o `seq` sobe normalmente.
6. **Pontuação de quem saiu** é mantida no `scores` do `GAME_OVER`.
7. **`GAME_LIST_OK` de partida `FINISHED`** é mantido por 60 s e depois a partida some (`games: []`).
8. **`max_players` padrão:** `cfg.max_players`.
9. **Reconexão ao Rendezvous** quando `peer_not_registered`: fazer `REGISTER` de novo e repetir o `DISCOVER` uma vez.
10. **Palpite de palavra** é normalizado como a palavra secreta antes de comparar (`/word BANANA` = `banana`). Se não normalizar para a-z, a jogada é recusada com `invalid_word`.
11. **Rígido ao enviar, tolerante ao receber.** `validate_envelope` não exige `STATE.last_guess` nem `word`/`winner`/`scores` do `GAME_OVER` (um `ABORTED` de outro cliente pode omiti-los). **Ao enviar**, sempre preencha todos os campos da especificação (`null` quando não se aplica). Quem lê (`GamePlayer`) usa `msg.get(...)`. `validate_envelope` confere o **tipo** de todo campo presente (`FIELD_TYPES`, ex.: `seq` inteiro, `players` lista de strings, `rejoin` booleano); tipo errado vira `bad_request`. Por isso os handlers de B podem confiar nos tipos dos campos que listam em `REQUIRED_FIELDS`, mas não na presença dos opcionais.
12. **`LEAVE`/queda do último jogador** de uma partida `RUNNING`: o host termina com `GAME_OVER result:"ABORTED" reason:"no_players"` (só registrado, sem destinatário), vai a `FINISHED` (visível por 60 s, como no item 7) e depois a `IDLE`. Em partida `OPEN`, sair o último jogador **não** encerra: a partida segue aberta, sem jogadores.
13. **`/cancel` com partida `OPEN`** também envia `GAME_OVER ABORTED reason:"host_shutdown"` (item 2) aos jogadores já inscritos.
14. **`GAME_START` ou `STATE` de `src` que não é o host do jogador** (ou de `game_id` diferente do atual): o jogador ignora e responde `ERROR invalid_state`. Mensagem de partida de peer sem `"hangman"` é descartada pelo roteador sem resposta.
15. **`GUESS` de quem não é jogador da partida** (e `GUESS` sem partida `RUNNING`): `GUESS_RESULT accepted:false reason:"game_not_running"` se há partida do host mas não está `RUNNING`; `ERROR invalid_state` se o host não tem partida alguma ou o `src` não está nela.
16. **Palpite de letra com mais de um caractere ou fora de `a-z`**: `GUESS_RESULT reason:"invalid_letter"`. Letra maiúscula é normalizada para minúscula antes de checar.
17. **Sem cliente de referência nem `forca-bot`:** a interoperabilidade (cenário 11 e issue 04.6) é testada entre **os próprios clientes do grupo**, em máquinas diferentes quando possível, e o que não puder ser verificado contra um cliente de terceiros é registrado como tal na entrega.

18. **Sem `STATE` final** na vitória ou derrota: o `GAME_OVER` vem logo depois do `GUESS_RESULT` da última jogada, como no "Exemplo Completo de Sessão" da especificação.
19. **Todo `GAME_OVER` do host passa por `FINISHED`** (60 s, depois `IDLE`): `WON`, `LOST` e `ABORTED` (`host_shutdown` e `no_players`), como no diagrama e na decisão 12. Só o `/quit` (`shutdown`) limpa tudo na hora.
20. **`last_guess` repetido:** o jogador só anuncia o `last_guess` quando ele muda (o `STATE` de um `LEAVE`, queda ou rejoin repete o anterior).
21. **Anti-spoof:** o roteador descarta (WARNING, sem resposta) toda mensagem cujo `src` não é o `peer_id` da conexão por onde chegou, e só aceita a resposta de um `request()` vinda do peer para quem ele foi enviado. A especificação não cobre; sem isso um vizinho conectado jogaria no lugar de outro.

## 7. Logging

Cada módulo usa `logging.getLogger("<nome>")`, nunca `print`. Formato único: `%(asctime)s %(levelname)-7s [%(name)s] %(message)s`.

| Logger | Módulo |
|---|---|
| `RDV` | `rendezvous_connection` |
| `PeerServer` | `peer_connection` |
| `PeerTable` | `peer_table` |
| `KeepAlive` | `keep_alive` |
| `Router` | `message_router` |
| `Host` / `Player` | `game_host` / `game_player` |
| `Game` | mensagens de jogo para a tela (`[Game] ...`) |
| `CLI` | `cli` |
| `Wire` | JSON bruto de cada mensagem, **nível DEBUG**, `->` enviado e `<-` recebido (só `peer_connection` escreve aqui) |

Na tela: `INFO` ou acima, mais tudo de `CLI` e `Game`. No arquivo (`--log-file`): tudo, incluindo `DEBUG`. Os exemplos de mensagens esperadas estão na especificação, seção "Observabilidade e Logs": copie o texto, porque a avaliação usa esses nomes.

## 8. Ordem de encerramento (`/quit`)

1. Se for host com partida ativa: `GAME_OVER ABORTED` (`reason: host_shutdown`) a todos os jogadores.
2. Se for jogador em partida: `LEAVE` ao host.
3. `BYE` a todos os vizinhos; aguarda `BYE_OK` até 2 s por conexão.
4. `UNREGISTER` no Rendezvous.
5. Cancela as tarefas e fecha o servidor TCP.

## 9. Pontos para confirmar com o professor

Anote a resposta ao lado e depois mova para a seção 6.

- [ ] `/cancel` deve mesmo usar `reason: "host_shutdown"`? (a especificação só lista `host_shutdown` e `no_players`)
- [x] O `forca-bot` e o cliente de referência estão disponíveis em qual endereço/namespace? (`FORCA`) **Resposta (15/11): não existem.** O repositório `mfcaetano/pyp2p-rdv` só contém o servidor Rendezvous (`pyp2p.mfcaetano.cc:8080`). Ver decisão 17.
- [x] Onde obter `words.txt`, `config.json` oficiais e o roteiro de testes? **Resposta (15/11): não existem.** Usamos o `words.txt` e o `config.json` de exemplo do repositório; o roteiro é a seção "Cenários de Teste Mínimos" da especificação. Se o professor publicar versões oficiais, substituir.
- [ ] Há apresentação ou só entrega de código? O que entregar (repositório, relatório, vídeo)?
- [ ] Política de uso de IA no trabalho.
- [ ] **Quando o relógio do turno reinicia?** Hoje reinicia a cada `STATE` (como a issue 02.5 pede), então o `LEAVE`, a queda ou o rejoin de *outro* jogador dá tempo extra a quem está na vez. A especificação fala em "não jogar em `turn_timeout` segundos", ou seja, um tempo por turno. Para seguir a especificação, reiniciar só quando o turno muda, com uma ficha própria (contador de turnos) no lugar do `seq` na checagem do timer. **Decisão do grupo.**