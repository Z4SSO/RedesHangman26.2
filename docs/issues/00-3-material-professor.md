# [00.3] Obter o material do professor e testar o Rendezvous

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | fundação |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/00-3-material-professor` |
| **Depende de** | nenhuma |
| **Etiquetas** | `todos` `fundação` `Sprint Backlog` |
| **Especificação** | Material Disponibilizado; Protocolo Peer–Rendezvous |

## Contexto atual

A especificação cita itens que o repositório do Rendezvous não contém: cliente de referência `pyp2p-forca`, peer-bot `forca-bot`, `words.txt`, `config.json` oficial e roteiro de testes. O item 7 da avaliação (interoperabilidade) depende deles.

## Objetivo

Ter o material (ou a confirmação de que não existe) e confirmar que o servidor Rendezvous público responde.

## Dentro do escopo

- [ ] Pedir ao professor/monitor os cinco itens acima, mais as dúvidas da seção 9 do contrato (uma mensagem só, agrupando tudo)
- [ ] Confirmar onde o `forca-bot` fica registrado (namespace `FORCA`, segundo a especificação)
- [ ] Testar o Rendezvous à mão: enviar um `REGISTER` e um `DISCOVER` (ex.: `rc_tester.py` do repositório `mfcaetano/pyp2p-rdv`, ou `nc`)
- [ ] Anotar as respostas na seção 9 do `docs/CONTRATO.md` e mover decisões para a seção 6
- [ ] Se o `words.txt` oficial chegar, substituir o da raiz

## Fora do escopo

- Escrever o cliente do Rendezvous (issue 01.1)

## Critérios de aceite

- [ ] Um `REGISTER` seguido de `DISCOVER` retorna `status: OK`, ou o problema está registrado
- [ ] A seção 9 do contrato tem uma resposta (ou "sem resposta até Seg 12h") para cada item
- [ ] Se não houver cliente de referência, o grupo decide como cumprir o cenário 11 (ex.: testar entre os próprios clientes) e anota

## Itens a estudar

- O Rendezvous aceita **um comando por conexão** e fecha em seguida
- `DISCOVER`/`UNREGISTER` só funcionam depois de um `REGISTER` do mesmo IP
- Limite de 50 requisições/min por IP: um `while True` sem pausa bloqueia o IP por 1 min

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/00-3-material-professor.md`. Releia na `docs/especificacao.md` as seções: Material Disponibilizado, Protocolo Peer–Rendezvous. Entre em plan mode e proponha o plano para a issue 00.3. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
