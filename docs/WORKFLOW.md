# Fluxo de trabalho do grupo

## Git

```
main  ←  feat/NN-N-slug        (uma branch por issue)
```

- Crie a branch **a partir da `main` atualizada**: `git switch main && git pull && git switch -c feat/01-1-rendezvous`.
- Commits pequenos, mensagem `tipo(escopo): resumo`. Tipos: `feat`, `fix`, `test`, `docs`, `refactor`. Escopo: `rede`, `jogo`, `cli`, `contrato`.
- Abra o PR/MR cedo (pode ser rascunho). Descrição: `Closes #NN.N`, o que mudou, como testar e quais critérios de aceite foram conferidos.
- **Revisão cruzada:** A revisa B, B revisa C, C revisa A. Revisão obrigatória antes do merge, merge commit normal (sem squash).
- Mudou uma interface? Atualize `docs/CONTRATO.md` **no mesmo PR** e avise no grupo.
- **Integre todo dia.** Branch com mais de um dia sem merge é risco: o grosso do trabalho de rede quebra na integração.
- Nunca faça commit direto na `main`, nem `push --force` nela.

## Etiquetas das issues

| Etiqueta | Uso |
|---|---|
| `parte-A` / `parte-B` / `parte-C` / `todos` | dono da issue |
| `rede`, `jogo`, `cli`, `integração`, `bônus`, `fundação` | área |
| `Sprint Backlog` → `Doing` → `Review` → `Done` | andamento (quadro Kanban) |
| `bloqueada` | espera outra issue (ver "Depende de") |

## Cronograma (hoje é domingo 15/11; entrega quarta 18/11)

| Quando | Meta |
|---|---|
| **Dom 15/11 à noite** | Fundação: repositório criado e contrato congelado (00.1, 00.2). Quem terminar cedo já começa a primeira issue da sua trilha, pois todas só dependem do contrato |
| **Seg 16/11** (dia pesado, ~16 issues) | **Todos os módulos funcionando e testados isoladamente** (A: 01.1 a 01.5 e 01.7; B: 02.1 a 02.4 e 02.6; C: 03.1 a 03.4 e 04.1) + material do professor (00.3). À noite: primeira integração da malha (04.2). Merges na `main` ao longo do dia, não só no fim |
| **Ter 17/11** | Partida completa (04.3), falhas e reconexão (01.6, 02.5, 04.4), `/quit` (04.5), interoperabilidade (04.6), passada de logs (03.5) |
| **Qua 18/11 manhã** | Revisão final, README, rodar os 11 cenários do zero (04.7), entregar. Bônus (05.x) só se tudo isso estiver pronto |

**Se segunda fechar atrasada:** dentro de cada trilha, a ordem das issues já é a de prioridade. A parte da rede (A) é o caminho crítico, porque B e C só conseguem testar em rede de verdade depois dela; por isso B e C testam com `Sender` e `FakeConnection` falsos e, ao terminar, **ajudam A** (revisão e testes) em vez de esperar.

Se o prazo apertar, **corte nesta ordem** (do que dá menos nota para o que dá mais): bônus → `/rtt`/`/reconnect` refinados → reconexão com backoff completa → tolerância a falhas fina. Nunca corte: Rendezvous, HELLO/PING, partida completa como host e como jogador, CLI e logs.

## Usando o Claude Code (uma instância por pessoa)

1. Cada um clona o repositório e abre o Claude Code na raiz (ele lê o `CLAUDE.md` sozinho).
2. Primeiro prompt da sessão, para a issue que vai fazer:
   > Leia `CLAUDE.md`, `docs/CONTRATO.md` e a issue `docs/issues/NN-N-....md`. Entre em plan mode e proponha o plano. Só implemente depois que eu aprovar.
3. Peça sempre o código **com** os testes. Rode `python -m pytest -q` e leia o resultado você mesmo.
4. Para conferir o resultado contra o enunciado, chame o subagente: `use o subagente spec-reviewer para revisar forca/<módulo>.py contra a seção "<título>" da especificação`.
5. Para validar o comportamento em rede: `use o subagente scenario-tester para rodar o cenário N`.
6. Revisem o diff de verdade antes do PR. Em protocolo de rede, os erros são sutis (campo faltando, `msg_id` errado, ordem de mensagens). **Cada integrante deve conseguir explicar o código que entrega.**

Não use duas instâncias do Claude no mesmo módulo. Uma instância extra só para **testar** (sem editar código de produção) costuma valer a pena.

## Definição de pronto (para fechar uma issue)

- [ ] Todos os critérios de aceite da issue conferidos.
- [ ] Testes escritos e `python -m pytest -q` verde.
- [ ] Logs com o nome de módulo e o texto da especificação, quando houver.
- [ ] `docs/CONTRATO.md` atualizado se uma interface mudou.
- [ ] PR revisado por outra pessoa e mesclado.
