# [04.7] Revisão final, README e entrega

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | integração |
| **Prazo** | Qua 18/11 (manhã) |
| **Branch** | `feat/04-7-entrega` |
| **Depende de** | [04.4](04-4-integrar-falhas.md), [04.5](04-5-integrar-quit.md), [04.6](04-6-interoperabilidade.md), [03.5](03-5-logs-spec.md) |
| **Etiquetas** | `todos` `integração` `Sprint Backlog` |
| **Especificação** | Critérios de Avaliação; Cenários de Teste Mínimos |

## Contexto atual

Último dia: nada de funcionalidade nova. É hora de conferir tudo contra os oito critérios de avaliação.

## Objetivo

Entregar um repositório que roda do zero e cumpre os critérios.

## Dentro do escopo

- [ ] Clonar o repositório numa pasta limpa, criar o venv e rodar os **11 cenários** do início ao fim
- [ ] Passar o `spec-reviewer` em cada seção principal e fechar o que sobrar
- [ ] Percorrer a tabela de Critérios de Avaliação (1 a 8) marcando o que está coberto e onde
- [ ] `README.md` com como instalar, rodar, comandos, estrutura, limitações conhecidas e o nome de cada integrante
- [ ] Conferir `config.json`, `words.txt` e que nenhum segredo/log foi para o repositório
- [ ] Cada integrante lê o diff do que entrega e se prepara para explicar o próprio módulo
- [ ] Entregar da forma que o professor pedir (anotada na seção 9 do contrato)

## Fora do escopo

- Qualquer funcionalidade nova (bônus só se tudo acima estiver pronto)

## Critérios de aceite

- [ ] O repositório clonado do zero roda e passa nos cenários
- [ ] `python -m pytest -q` verde
- [ ] README completo e sem pendências no `docs/CONTRATO.md`
- [ ] A entrega foi feita no formato e prazo combinados

## Itens a estudar

- Reler a tabela de Critérios de Avaliação da especificação, item por item

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/04-7-entrega.md`. Releia na `docs/especificacao.md` as seções: Critérios de Avaliação, Cenários de Teste Mínimos. Entre em plan mode e proponha o plano para a issue 04.7. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
