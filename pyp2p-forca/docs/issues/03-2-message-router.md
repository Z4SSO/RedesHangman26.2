# [03.2] MessageRouter: validar o envelope e despachar por tipo

| | |
|---|---|
| **Responsável** | Parte C: CLI e integração |
| **Área** | cli |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/03-2-message-router` |
| **Depende de** | [00.2](00-2-contrato.md) |
| **Etiquetas** | `parte-C` `cli` `Sprint Backlog` |
| **Especificação** | Envelope comum; Regras de processamento; ERROR |

## Contexto atual

Toda mensagem que não é de conexão (HELLO/PING/BYE) passa por aqui. O roteador é a única porta de entrada para `GameHost` e `GamePlayer` e a razão de eles serem testáveis sem rede.

## Objetivo

Implementar `MessageRouter` conforme o contrato (seção 5.4), testado com conexões falsas.

## Dentro do escopo

- [ ] `register(type, handler)` e `on_message(conn, msg)`
- [ ] `validate_envelope` antes de despachar: `unknown_type`, `bad_request`, `not_for_me` viram `ERROR` ao remetente; `ttl != 1` é descartada em silêncio; a conexão **permanece aberta**
- [ ] Mensagem de contexto inválido (`GUESS` fora de partida) responde `ERROR invalid_state` (o handler levanta e o roteador traduz)
- [ ] `ERROR` recebido só é registrado no log e **nunca** gera resposta
- [ ] Peer sem a feature `hangman` nunca recebe nem entrega mensagens de lobby/partida
- [ ] `request(peer_id, msg, timeout)`: envia e espera a resposta de mesmo `msg_id`; `None` no timeout; resposta casada não vai aos handlers
- [ ] Exceção dentro de um handler é registrada e não derruba o roteador
- [ ] Testes com `FakeConnection`: cada código de erro, `ttl` errado, `request` com e sem resposta, handler que levanta

## Fora do escopo

- Implementar os handlers de jogo (Parte B)
- HELLO/PING/BYE (Parte A)

## Critérios de aceite

- [ ] Mensagem com `type` desconhecido gera `ERROR unknown_type` e a conexão segue aberta
- [ ] Mensagem com `dst` de outro peer gera `ERROR not_for_me`
- [ ] Duas chamadas simultâneas de `request` para peers diferentes não se misturam
- [ ] Um handler que levanta exceção não impede as mensagens seguintes

## Itens a estudar

- `asyncio.Future` para casar requisição e resposta pelo `msg_id`
- `asyncio.wait_for` e limpar o dicionário de pendentes em caso de timeout

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/03-2-message-router.md`. Releia na `docs/especificacao.md` as seções: Envelope comum, Regras de processamento, ERROR. Entre em plan mode e proponha o plano para a issue 03.2. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
