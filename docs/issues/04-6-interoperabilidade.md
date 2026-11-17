# [04.6] Interoperabilidade com o cliente de referência e o forca-bot (cenário 11)

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | integração |
| **Prazo** | Ter 17/11 |
| **Branch** | `feat/04-6-interoperabilidade` |
| **Depende de** | [04.3](04-3-integrar-partida.md), [00.3](00-3-material-professor.md) |
| **Etiquetas** | `todos` `integração` `Sprint Backlog` |
| **Especificação** | Cenários de Teste Mínimos (11); Material Disponibilizado |

## Contexto atual

O item 7 da avaliação exige jogar contra o cliente de referência nos dois papéis. É onde diferenças sutis de interpretação do protocolo aparecem.

## Objetivo

Jogar uma partida completa como jogador contra o `forca-bot` e como host com o cliente de referência como jogador.

## Dentro do escopo

- [ ] Entrar numa partida do bot oficial (`bot@CIC`, namespace `CIC`, `45.171.101.167:8081`; **não** é `FORCA`) e jogar até o `GAME_OVER`: `python tools/bot_check.py all`
- [ ] Criar partida e ter o cliente de referência como jogador
- [ ] Se alguma mensagem for recusada, comparar o JSON com a especificação (campo faltando, tipo errado, `msg_id`)
- [ ] Registrar o resultado em `docs/testes.md`; se o material não existir, escrever isso e o que foi feito no lugar

## Fora do escopo

- (nada em especial)

## Critérios de aceite

- [ ] Partida completa nos dois papéis, ou justificativa registrada de por que não foi possível
- [ ] Nenhum `ERROR` inesperado nos logs

## Itens a estudar

- Ler o JSON bruto (`Wire`) do cliente de referência para ver o formato exato que ele envia

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/04-6-interoperabilidade.md`. Releia na `docs/especificacao.md` as seções: Cenários de Teste Mínimos (11), Material Disponibilizado. Entre em plan mode e proponha o plano para a issue 04.6. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
