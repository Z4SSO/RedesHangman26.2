# [01.1] Cliente do Rendezvous (REGISTER / DISCOVER / UNREGISTER)

| | |
|---|---|
| **Responsável** | Parte A: Rede |
| **Área** | rede |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/01-1-rendezvous` |
| **Depende de** | [00.2](00-2-contrato.md) |
| **Etiquetas** | `parte-A` `rede` `Sprint Backlog` |
| **Especificação** | Protocolo Peer–Rendezvous |

## Contexto atual

Nenhum peer enxerga outro sem passar pelo Rendezvous. `forca/rendezvous_connection.py` existe só como esqueleto com as assinaturas do contrato.

## Objetivo

Implementar `RendezvousConnection` com os três comandos, abrindo uma conexão TCP nova por comando.

## Dentro do escopo

- [ ] `register()`: envia `REGISTER` com `namespace`, `name`, `port=listen_port`, `ttl=register_ttl`; guarda `public_ip` e registra `[RDV] registered alice@CIC as IP:PORT (ttl=7200)`
- [ ] `discover(namespace=None)`: devolve a lista de peers **sem o próprio peer** (filtro por `name` + `namespace`)
- [ ] `unregister()`: envia `UNREGISTER` com `namespace`, `name` e `port`
- [ ] `RendezvousError(message)` quando `status == "ERROR"` (inclui o texto do bloqueio por excesso de requisições)
- [ ] Timeout de conexão e de leitura (ex.: 5 s) e leitura de exatamente uma linha de resposta
- [ ] Testes com um servidor falso (`asyncio.start_server` em `127.0.0.1`, porta 0) cobrindo: sucesso, `bad_port`, `peer_not_registered`, resposta de bloqueio, timeout e filtro do próprio peer

## Fora do escopo

- Laço periódico de DISCOVER e refresh do TTL (issue 01.7)
- Conectar nos peers descobertos (issues 01.2 e 01.3)

## Critérios de aceite

- [ ] Contra o servidor falso, os três comandos produzem o JSON da especificação, uma linha terminada em `\n`
- [ ] `discover()` nunca devolve o próprio peer
- [ ] `status: ERROR` vira `RendezvousError` com o `message` do servidor
- [ ] Nenhuma chamada fica pendurada: tudo com timeout
- [ ] Contra o servidor público (se acessível), `register()` devolve o IP observado

## Itens a estudar

- `asyncio.open_connection` e `asyncio.wait_for` para timeouts
- Peer atrás de NAT: o `ip` do `REGISTER` é o IP público; conexões de entrada só funcionam com a porta encaminhada (registrar isso no log)
- Por que a resposta do `DISCOVER` inclui o próprio peer

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/01-1-rendezvous.md`. Releia na `docs/especificacao.md` as seções: Protocolo Peer–Rendezvous. Entre em plan mode e proponha o plano para a issue 01.1. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
