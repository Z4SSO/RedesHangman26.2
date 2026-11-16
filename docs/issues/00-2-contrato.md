# [00.2] Revisar e congelar o contrato entre módulos

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | fundação |
| **Prazo** | Dom 15/11 (noite) |
| **Branch** | `feat/00-2-contrato` |
| **Depende de** | [00.1](00-1-repositorio.md) |
| **Etiquetas** | `todos` `fundação` `Sprint Backlog` |
| **Especificação** | Protocolo Peer–Peer (todas as mensagens); Regras do jogo; Máquina de estados |

## Contexto atual

`docs/CONTRATO.md` e `forca/protocol.py` foram escritos a partir da especificação e definem como A, B e C se encaixam. Um erro aqui se repete nos três módulos, então vale ler com atenção antes de codar.

## Objetivo

Os três concordam com o contrato e o congelam (`contrato-v1`). Depois disso, mudanças só por PR avisando o grupo.

## Dentro do escopo

- [ ] Reunião de 30 min: ler `docs/CONTRATO.md` inteiro, em voz alta, seção por seção
- [ ] Cada pessoa confere a sua parte: A confere 5.1 a 5.3, B confere 5.5 a 5.7, C confere 5.4 e a seção 7
- [ ] Conferir `REQUIRED_FIELDS` de `forca/protocol.py` contra as tabelas de campos da especificação, mensagem por mensagem
- [ ] Revisar as decisões da seção 6 (ver se alguma contradiz a especificação)
- [ ] Registrar as dúvidas para o professor na seção 9 (a 00.3 envia)
- [ ] Corrigir o que for preciso por PR e criar a tag `contrato-v1`

## Fora do escopo

- Implementar qualquer módulo

## Critérios de aceite

- [ ] Cada pessoa consegue dizer quais funções dos outros módulos vai chamar e quais vai expor
- [ ] `REQUIRED_FIELDS` confere com a especificação (revisado por alguém que não escreveu a lista)
- [ ] Dúvidas abertas estão na seção 9 do contrato
- [ ] A tag `contrato-v1` existe na `main`

## Itens a estudar

- Por que `GAME_START`, `STATE` e `GAME_OVER` só trafegam host ↔ jogador (estrela da partida)
- Diferença entre `ERROR` (msg_id novo + `ref_msg_id`) e as respostas `*_OK` (repetem o `msg_id`)

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/00-2-contrato.md`. Releia na `docs/especificacao.md` as seções: Protocolo Peer–Peer (todas as mensagens), Regras do jogo, Máquina de estados. Entre em plan mode e proponha o plano para a issue 00.2. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
