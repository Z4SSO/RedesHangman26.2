# [01.3] PeerServer e PeerConnection: TCP e framing JSON por linha

| | |
|---|---|
| **Responsável** | Parte A: Rede |
| **Área** | rede |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/01-3-peer-connection` |
| **Depende de** | [00.2](00-2-contrato.md) |
| **Etiquetas** | `parte-A` `rede` `Sprint Backlog` |
| **Especificação** | Transporte e Codificação; Arquitetura da Solução (duas camadas) |

## Contexto atual

Todas as mensagens entre peers (descoberta e partida) usam a mesma conexão TCP, que é aberta pelos dois lados: cada peer escuta e também conecta nos vizinhos.

## Objetivo

Implementar o servidor TCP, o cliente TCP e o framing de uma mensagem JSON por linha, entregando as mensagens ao `on_message`.

## Dentro do escopo

- [ ] `PeerServer.start()/stop()` escutando em `listen_port` e `connect(ip, port)` para conexões de saída
- [ ] Leitura por linha com limite de 32 KiB; linha acima do limite fecha a conexão
- [ ] `decode`/`encode` de `forca/protocol.py` em toda leitura/escrita; JSON inválido gera `ERROR bad_json` e fecha a conexão
- [ ] `PeerConnection.send(msg)` seguro com várias tarefas escrevendo (um `asyncio.Lock`) e que devolve `False` se a conexão caiu
- [ ] Erro de leitura/escrita fecha a conexão imediatamente e chama `on_closed`
- [ ] Log `Wire` em DEBUG com o JSON bruto: `-> {...}` enviado e `<- {...}` recebido
- [ ] Testes com dois `PeerServer` em `127.0.0.1` (porta 0): troca de mensagem, linha gigante, JSON inválido, fechamento do outro lado

## Fora do escopo

- HELLO e desempate de duplicadas (01.4)
- PING/PONG (01.5)
- Validação do envelope e despacho por tipo (03.2)

## Critérios de aceite

- [ ] Duas mensagens enviadas em sequência chegam como duas linhas separadas, na ordem
- [ ] Uma linha com mais de 32768 bytes não derruba o processo
- [ ] `send()` em conexão fechada devolve `False`, sem exceção
- [ ] O log DEBUG mostra o JSON bruto de cada mensagem nos dois sentidos

## Itens a estudar

- `asyncio.start_server`, `StreamReader.readline` e o parâmetro `limit`
- Por que escrever com `writer.write` + `await writer.drain()` sob um lock
- Detectar fim de conexão: `readline()` devolve `b""`

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/01-3-peer-connection.md`. Releia na `docs/especificacao.md` as seções: Transporte e Codificação, Arquitetura da Solução (duas camadas). Entre em plan mode e proponha o plano para a issue 01.3. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
