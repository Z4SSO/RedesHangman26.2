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

Para testar sozinho, abra 3 terminais com `--name alice --port 8081`, `--name bob --port 8082` e `--name carol --port 8083` no mesmo namespace. Todos saem do mesmo IP, o que o Rendezvous aceita, pois ele identifica cada peer por IP + namespace + nome.

Todas as opções têm padrão em [`config.json`](config.json) e podem ser sobrescritas na linha de comando (`--help`).

## Comandos do jogo

`/peers` `/conn` `/rtt` `/reconnect` `/games` `/create <palavra> [max]` `/create --random [max]` `/start` `/cancel` `/join <host>` `/leave` `/guess <letra>` `/word <palavra>` `/status` `/log <nível>` `/help` `/quit`

## Estrutura

```
forca/                 código (um arquivo por módulo da especificação)
  protocol.py          formato das mensagens (fonte única de verdade)
  models.py, config.py tipos e configuração compartilhados
tests/                 testes (pytest)
tools/                 scripts de apoio (subir peers locais, cenários)
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
