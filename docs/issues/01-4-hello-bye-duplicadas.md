# [01.4] HELLO/HELLO_OK, desempate de duplicadas e BYE/BYE_OK

| | |
|---|---|
| **Responsável** | Parte A: Rede |
| **Área** | rede |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/01-4-hello-bye-duplicadas` |
| **Depende de** | [01.3](01-3-peer-connection.md) |
| **Etiquetas** | `parte-A` `rede` `Sprint Backlog` |
| **Especificação** | HELLO / HELLO_OK; BYE / BYE_OK; Conexões duplicadas |

## Contexto atual

Todos os peers tentam conectar em todos. É comum dois peers abrirem conexão um para o outro ao mesmo tempo, e o `/conn` precisa mostrar **uma** conexão por vizinho.

## Objetivo

Implementar o handshake, o desempate determinístico e o encerramento controlado.

## Dentro do escopo

- [ ] Quem abre a conexão envia `HELLO` (`peer_id`, `version: "1.0"`, `features: ["hangman"]`); quem aceita responde `HELLO_OK` com o mesmo `msg_id`
- [ ] Antes do `HELLO_OK`, qualquer outra mensagem é recusada
- [ ] Guardar `features` do vizinho em `conn.features`; sem `"hangman"` a conexão existe mas não recebe lobby/partida
- [ ] Desempate (contrato, seção 6.1): vale a conexão aberta pelo menor `peer_id`; a outra recebe `BYE reason:"duplicate"`
- [ ] `close(reason)`: envia `BYE`, espera `BYE_OK` por até 2 s e fecha o socket de qualquer forma; quem recebe `BYE` responde `BYE_OK` e fecha
- [ ] Logs: `[PeerServer] Inbound connected: bob@CIC (features=hangman)` e `[PeerServer] Duplicate connection with carol@CIC — keeping outbound (lower peer_id)`
- [ ] Teste: dois peers conectam ao mesmo tempo → exatamente uma conexão sobrevive em cada lado

## Fora do escopo

- Reconexão com backoff (01.6)

## Critérios de aceite

- [ ] Após conexões simultâneas, cada peer tem exatamente uma conexão com o outro (a mesma nos dois lados)
- [ ] `HELLO_OK` repete o `msg_id` do `HELLO`
- [ ] Peer sem a feature `hangman` é aceito na malha mas marcado como sem jogo
- [ ] `close()` nunca demora mais que ~2 s, mesmo sem `BYE_OK`

## Itens a estudar

- Comparação lexicográfica de `peer_id` e por que o resultado é igual nos dois lados
- Condição de corrida: o `HELLO_OK` do desempate pode chegar depois do fechamento

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/01-4-hello-bye-duplicadas.md`. Releia na `docs/especificacao.md` as seções: HELLO / HELLO_OK, BYE / BYE_OK, Conexões duplicadas. Entre em plan mode e proponha o plano para a issue 01.4. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
