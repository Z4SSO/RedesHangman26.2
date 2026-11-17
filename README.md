# PyP2P-Forca

Cliente P2P do **Jogo da Forca** para a disciplina de Redes de Computadores (UnB), semestre 2026/2. Cada peer registra-se num servidor Rendezvous, descobre os demais, mantém conexões TCP persistentes e joga forca por turnos, com um peer assumindo o papel temporário de **host** em cada partida.

> Entrega: **quarta-feira, 18/11/2026**. Especificação completa em [`docs/especificacao.md`](docs/especificacao.md).

## Equipe

| Parte | Responsável | Módulos |
|---|---|---|
| **A: Rede** | _(Luís Felipe de Lima Benvegnú)_ | `rendezvous_connection`, `peer_connection`, `peer_table`, `keep_alive`, `p2p_client` |
| **B: Jogo** | _(Caio Bonini Sampaio)_ | `hangman`, `game_host`, `game_player` |
| **C: CLI e integração** | _(Lucas Diógenes)_ | `message_router`, `cli`, `main`, logs, testes de cenários |

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# um peer (o servidor Rendezvous público já está no ar)
python -m forca.main --name alice --namespace CIC --port 8081

# testes
python -m pytest -q
```

Para testar sozinho, abra 3 terminais com `--name alice --port 8081`, `--name bob --port 8082` e `--name carol --port 8083` no mesmo namespace (ou use `python tools/run_local.py`, que sobe os três e deixa mandar comandos a cada um). Todos saem do mesmo IP, o que o Rendezvous aceita, pois ele identifica cada peer por IP + namespace + nome. Como o Rendezvous divulga o IP **público**, o cliente conecta por `127.0.0.1` nos vizinhos que têm o mesmo IP público que ele (roteadores costumam não alcançar o próprio IP público por dentro).

Num servidor compartilhado, prefira um namespace só seu (ex.: `--namespace CIC-grupo`) para não misturar com peers de outros grupos.

Todas as opções têm padrão em [`config.json`](config.json) e podem ser sobrescritas na linha de comando (`--help`).

## Testes

```bash
python -m pytest -q                      # testes unitários e de rede (127.0.0.1)
python tools/scenarios.py                # os cenários 1 a 10 da especificação, com processos reais
python tools/scenarios.py --only 7a,8    # só alguns (--list mostra todos)
python tools/bot_check.py all            # cenário 11: jogar contra o bot oficial (precisa de internet)
```

`tools/scenarios.py` sobe um Rendezvous local (`tools/rdv_local.py`) e `python -m forca.main` para alice, bob e carol com tempos curtos, manda os comandos, **confere as linhas esperadas** e imprime PASSOU/FALHOU. Os logs (com o JSON bruto) ficam em `logs/cenarios/`. Os resultados e a cobertura dos critérios de avaliação estão em [`docs/testes.md`](docs/testes.md).

## Comandos do jogo

`/peers` `/conn` `/rtt` `/reconnect` `/games` `/create <palavra> [max]` `/create --random [max]` `/start` `/cancel` `/join <host>` `/leave` `/guess <letra>` `/word <palavra>` `/status` `/log <nível>` `/help` `/quit`

## Estrutura

```
forca/                 código (um arquivo por módulo da especificação)
  protocol.py          formato das mensagens (fonte única de verdade)
  models.py, config.py tipos e configuração compartilhados
tests/                 testes (pytest)
tools/                 scripts de apoio
  run_local.py         sobe N peers locais e deixa mandar comandos / matar um deles
  rdv_local.py         Rendezvous local mínimo, para testar sem o servidor público
  scenarios.py         cenários 1 a 10 da especificação em processos reais
  bot_check.py         cenário 11: o nosso cliente contra o bot oficial
docs/
  especificacao.md     enunciado do professor
  CONTRATO.md          interfaces entre módulos, donos, decisões
  WORKFLOW.md          git, revisão, uso do Claude Code, cronograma
  issues/              tarefas numeradas (+ issues.csv para importar no GitLab)
CLAUDE.md              instruções para o Claude Code
.claude/agents/        subagentes (revisor de especificação, testador de cenários)
```

## Por onde começar

1. Leia [`docs/CONTRATO.md`](docs/CONTRATO.md) e [`docs/WORKFLOW.md`](docs/WORKFLOW.md).
2. Pegue a sua trilha em [`docs/issues/README.md`](docs/issues/README.md) e vá na ordem das issues.
3. Uma issue por branch, um PR por issue, revisão cruzada.

## Estado

Veja o quadro de progresso em [`docs/issues/README.md`](docs/issues/README.md).

## Limitações conhecidas

- **Interoperabilidade:** o cliente de referência `pyp2p-forca` não foi disponibilizado; testamos o nosso cliente como jogador contra o bot oficial (`bot@CIC`) e como host/jogador entre os nossos próprios clientes.
- **NAT:** peers em redes diferentes só se alcançam se a porta de escuta estiver acessível (encaminhamento de porta); o Rendezvous só divulga o IP público. Entre máquinas da mesma rede local atrás do mesmo roteador, a conexão depende de o roteador permitir *hairpin*.
- Bônus (migração de host, chat, modo competitivo) não implementados.
