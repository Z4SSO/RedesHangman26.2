# [03.3] CLI (1/2): laço de comandos e comandos de rede

| | |
|---|---|
| **Responsável** | Parte C: CLI e integração |
| **Área** | cli |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/03-3-cli-rede` |
| **Depende de** | [03.1](03-1-main-logging.md), [03.2](03-2-message-router.md) |
| **Etiquetas** | `parte-C` `cli` `Sprint Backlog` |
| **Especificação** | Interface de Usuário (CLI) |

## Contexto atual

A CLI é como o grupo e o professor vão ver o programa funcionando. A leitura do teclado não pode bloquear as tarefas de rede.

## Objetivo

Implementar o laço da CLI e os comandos `/peers`, `/conn`, `/rtt`, `/reconnect`, `/log`, `/help`, `/quit`.

## Dentro do escopo

- [ ] Leitura de `stdin` sem bloquear o event loop (`asyncio.to_thread(input)` ou leitor assíncrono)
- [ ] Parser de comandos, argumentos e mensagem de uso para comando inválido; comando desconhecido não derruba o programa
- [ ] `/peers [* | #namespace]`: `DISCOVER` e lista (padrão: namespace local); respeitar o limite do Rendezvous
- [ ] `/conn`: conexões ativas (`peer_id`, entrada/saída, estado, RTT) com exatamente uma por vizinho
- [ ] `/rtt`: RTT médio por peer
- [ ] `/reconnect`: chama a reconciliação imediata (issue 01.6)
- [ ] `/log <nível>`, `/help` (lista todos os comandos) e `/quit` (chama `P2PClient.stop()`)
- [ ] Testes do parser (sem rede)

## Fora do escopo

- Comandos de jogo (03.4)

## Critérios de aceite

- [ ] Todos os comandos desta issue respondem com saída legível
- [ ] `/help` lista os 17 comandos da especificação
- [ ] Digitar `/foo` mostra um aviso e o programa segue
- [ ] Enquanto espera o teclado, o `PING/PONG` continua funcionando

## Itens a estudar

- `asyncio.to_thread` e por que `input()` direto trava o event loop
- `shlex.split` para argumentos com aspas

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/03-3-cli-rede.md`. Releia na `docs/especificacao.md` as seções: Interface de Usuário (CLI). Entre em plan mode e proponha o plano para a issue 03.3. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
