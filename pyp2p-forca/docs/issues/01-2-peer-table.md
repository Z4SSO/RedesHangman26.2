# [01.2] PeerTable: estados, eventos e reconciliação

| | |
|---|---|
| **Responsável** | Parte A: Rede |
| **Área** | rede |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/01-2-peer-table` |
| **Depende de** | [00.2](00-2-contrato.md) |
| **Etiquetas** | `parte-A` `rede` `Sprint Backlog` |
| **Especificação** | Gerenciamento de Conexões e Reconexões |

## Contexto atual

A malha de descoberta precisa saber, a todo momento, quem foi descoberto, quem está conectado e quem caiu. O resto do sistema (host, jogador, CLI) consulta essa tabela e assina seus eventos.

## Objetivo

Implementar `PeerTable` conforme o contrato (seção 5.2), testável sem rede, com conexões falsas.

## Dentro do escopo

- [ ] Entrada por `peer_id` com `ip`, `port`, `state`, `conn`, `attempts`, `next_retry`
- [ ] `reconcile(discovered)`: peers novos entram `DISCOVERED` e disparam a conexão; peers que sumiram do Rendezvous viram `GONE` e a conexão fecha com `BYE`
- [ ] `connected()`, `state_of()`, `send_to()` (é o `Sender` do contrato) e `broadcast(msg_factory)`
- [ ] `subscribe(event, cb)` e emissão de `peer_connected`, `peer_stale`, `peer_gone`
- [ ] Receber por parâmetro a função que abre conexões (`connect_fn`), para testar sem rede; atualize o contrato 5.2 se mudar o construtor
- [ ] Testes: peer novo, peer que some, `send_to` de peer ausente (retorna `False`), eventos disparados

## Fora do escopo

- Abrir sockets (01.3) e backoff de reconexão (01.6)
- Decidir o que host/jogador fazem nos eventos (issues 02.5 e 02.6)

## Critérios de aceite

- [ ] Após um `reconcile`, peers novos ficam `DISCOVERED` e o conector é chamado uma vez por peer
- [ ] `send_to` de peer não conectado devolve `False` sem lançar exceção
- [ ] Os três eventos chegam aos assinantes com o `peer_id` correto
- [ ] Peer ausente do `DISCOVER` vira `GONE` e é desconectado

## Itens a estudar

- Padrão observer/pub-sub simples com lista de callbacks assíncronos
- `asyncio.gather` com `return_exceptions=True` para o `broadcast` não parar no primeiro erro

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/01-2-peer-table.md`. Releia na `docs/especificacao.md` as seções: Gerenciamento de Conexões e Reconexões. Entre em plan mode e proponha o plano para a issue 01.2. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
