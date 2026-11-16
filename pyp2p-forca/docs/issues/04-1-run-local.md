# [04.1] tools/run_local.py: subir N peers locais

| | |
|---|---|
| **Responsável** | Parte C: CLI e integração |
| **Área** | integração |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/04-1-run-local` |
| **Depende de** | [03.1](03-1-main-logging.md) |
| **Etiquetas** | `parte-C` `integração` `Sprint Backlog` |
| **Especificação** | Cenários de Teste Mínimos |

## Contexto atual

Para testar sozinho a malha e as partidas é preciso subir 3 peers em portas diferentes, com logs separados, e conseguir mandar comandos a cada um.

## Objetivo

Script que inicia N peers locais e permite enviar comandos a cada um e ver os logs.

## Dentro do escopo

- [ ] `python tools/run_local.py --names alice,bob,carol --base-port 8081 --namespace CIC`
- [ ] Um subprocesso por peer com `--log-file logs/<nome>.log` e `--log-level DEBUG`
- [ ] Entrada interativa `bob> /join alice@CIC` que envia a linha à `stdin` do peer certo
- [ ] Encerramento limpo de todos (e opção para matar um com `kill -9`, para os cenários 7 e 9)
- [ ] Pasta `logs/` no `.gitignore`

## Fora do escopo

- Automatizar as asserções dos cenários (04.2 a 04.5)

## Critérios de aceite

- [ ] Um comando sobe 3 peers que se descobrem no servidor público
- [ ] É possível mandar comandos a cada peer e matar um deles de forma abrupta
- [ ] Ao sair, nenhum processo fica órfão

## Itens a estudar

- `subprocess.Popen` com `stdin=PIPE` e `python -u`
- `os.kill(pid, signal.SIGKILL)`

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/04-1-run-local.md`. Releia na `docs/especificacao.md` as seções: Cenários de Teste Mínimos. Entre em plan mode e proponha o plano para a issue 04.1. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
