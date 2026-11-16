# PyP2P-Forca: instruções para o Claude Code

Cliente P2P do **Jogo da Forca** (trabalho de Redes de Computadores, UnB). Cada peer registra-se num servidor Rendezvous, descobre os outros peers, conecta por TCP e joga forca em turnos: um peer vira **host** (conhece a palavra e coordena) e os outros são **jogadores**. Grupo de 3 pessoas, entrega na **quarta-feira 18/11**.

## Leia antes de qualquer tarefa

1. `docs/CONTRATO.md`: interfaces entre módulos, donos e decisões. **Siga à risca.**
2. `docs/especificacao.md`: especificação do professor. É a fonte de verdade do protocolo; abra a seção que a tarefa cita em vez de lembrar de memória.
3. A issue em `docs/issues/` que está sendo trabalhada (escopo, fora de escopo e critérios de aceite).

## Stack e comandos

- Python 3.11+, `asyncio`, **apenas biblioteca padrão** em `forca/`. `pytest` só para testes.
- Rodar um peer: `python -m forca.main --name alice --port 8081 --namespace CIC`
- Testes: `python -m pytest -q`
- Subir 3 peers locais para teste: `python tools/run_local.py` (issue 04.1)

## Regras de código

- Mensagens **sempre** por `forca/protocol.py` (`new_message`, `reply`, `validate_envelope`, `encode`, `decode`). Nunca dicionário de mensagem escrito à mão.
- `hangman.py` **não importa nada de rede**. `game_host.py` e `game_player.py` falam com a rede só pelo `Sender` injetado, nunca importam `peer_connection` nem `peer_table`.
- Nada bloqueante no event loop (`time.sleep`, `input()` direto, I/O pesado). Use `asyncio.sleep`, `asyncio.to_thread`.
- Toda tarefa em segundo plano é guardada e cancelada no `stop()`.
- Mensagem inválida nunca derruba o programa.
- `logging.getLogger("<nome do contrato>")`, nunca `print`. Nomes e textos de log da especificação (`[Host] Turn: bob@CIC (timeout 30 s)`) são usados na avaliação: reproduza-os.
- O Rendezvous bloqueia o IP por 1 min acima de **50 requisições/min**. Nenhum laço que chame o Rendezvous pode rodar sem `await asyncio.sleep`.
- Type hints nas assinaturas públicas; docstring curta dizendo a regra da especificação que o código cumpre.

## Fluxo de trabalho

- **Cada pessoa é dona de módulos** (tabela em `docs/CONTRATO.md`, seção 2). Não edite módulo de outra pessoa; se precisar, avise ou abra issue.
- Uma issue por branch: `feat/NN-N-slug` (ex.: `feat/01-1-rendezvous`). Commits pequenos: `feat(rede): ...`, `fix(jogo): ...`, `test(...)`, `docs(...)`.
- Merge só por PR/MR, **revisado por outra pessoa** (A revisa B, B revisa C, C revisa A), merge commit normal, sem squash.
- Antes de abrir o PR: `python -m pytest -q` verde e os critérios de aceite da issue conferidos um a um.
- Atualize `docs/CONTRATO.md` **no mesmo PR** se mudar uma interface.

## Como trabalhar comigo (Claude)

- Para módulos grandes (`game_host`, `peer_connection`), comece em **plan mode** e só edite depois do plano aprovado.
- Escreva o teste junto com o código. Lógica pura (`hangman`) com testes unitários; rede com testes `asyncio` usando sockets locais (`127.0.0.1`, porta 0).
- Teste o que a especificação exige, inclusive os casos de erro (`JOIN_ERR`, `not_your_turn`, `letter_already_used`, `seq` repetido, `ttl != 1`).
- Ao terminar uma issue, confira cada critério de aceite e diga o que **não** foi possível verificar (ex.: interoperabilidade sem o cliente de referência).
- Subagentes em `.claude/agents/`: `spec-reviewer` (confere o código contra a seção da especificação) e `scenario-tester` (roda os cenários de teste em peers locais e reporta falhas sem editar código).
- Não invente campos de mensagem. Se a especificação não cobre, pare, registre a dúvida na seção 9 do contrato e use a decisão provisória mais simples.

## Armadilhas conhecidas

- `DISCOVER` devolve o **próprio** peer: filtre por `name`+`namespace`.
- `PONG` e todas as respostas (`*_OK`, `JOIN_ERR`, `GUESS_RESULT`) **repetem o `msg_id`** da requisição. `ERROR` leva `msg_id` novo e `ref_msg_id` apontando para a causa.
- `ttl` é sempre `1`; qualquer outro valor é descartado em silêncio.
- `word_hash` é calculado sobre a palavra **normalizada** (minúsculas, sem acentos).
- `STATE.seq` começa em 1 e sobe a cada mudança; o jogador descarta `seq` menor ou igual ao último aplicado.
- Jogada rejeitada **não** gera `STATE` nem consome o turno.
- O host **não joga**.
- Conexões duplicadas (os dois lados conectam ao mesmo tempo): `/conn` deve mostrar uma só por vizinho.
- Cada conexão com o Rendezvous é **um comando só**; abrir uma nova a cada operação.
