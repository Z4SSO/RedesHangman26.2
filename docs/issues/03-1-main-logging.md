# [03.1] main.py: argumentos, config.json e logging

| | |
|---|---|
| **Responsável** | Parte C: CLI e integração |
| **Área** | cli |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/03-1-main-logging` |
| **Depende de** | [00.2](00-2-contrato.md) |
| **Etiquetas** | `parte-C` `cli` `Sprint Backlog` |
| **Especificação** | Arquivo de configuração; Observabilidade e Logs |

## Contexto atual

`forca/main.py` e `forca/config.py` já leem o `config.json` e os argumentos. Falta o que a avaliação mais olha por fora: logging correto, com módulo, timestamp e nível, e o JSON bruto em DEBUG.

## Objetivo

Configurar o logging (tela × arquivo) e a inicialização do programa.

## Dentro do escopo

- [ ] Formato único `%(asctime)s %(levelname)-7s [%(name)s] %(message)s` (contrato, seção 7)
- [ ] Tela: `INFO` ou acima, mais tudo de `CLI` e `Game`; arquivo (`--log-file` / `log_file`): tudo, incluindo `DEBUG` e o logger `Wire` com o JSON bruto
- [ ] `/log <nível>` troca o nível da tela em tempo de execução (função que a CLI chama)
- [ ] Criar `P2PClient` e `CLI`, rodar o loop e encerrar limpo em `Ctrl+C`
- [ ] Erro de configuração (chave desconhecida, porta inválida) vira mensagem clara, não traceback
- [ ] Testes: `parse_args`, precedência linha de comando > `config.json` > padrão

## Fora do escopo

- Os comandos em si (03.3 e 03.4)

## Critérios de aceite

- [ ] Com `--log-file x.log`, o arquivo recebe `DEBUG` e a tela só `INFO`
- [ ] Mudar o nível com `/log DEBUG` passa a mostrar `DEBUG` na tela sem reiniciar
- [ ] `--name`, `--namespace` e `--port` sobrescrevem o `config.json`
- [ ] `Ctrl+C` encerra pelo mesmo caminho do `/quit`

## Itens a estudar

- `logging.Handler` com níveis diferentes por handler (tela × arquivo)
- `argparse` e precedência de configuração

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/03-1-main-logging.md`. Releia na `docs/especificacao.md` as seções: Arquivo de configuração, Observabilidade e Logs. Entre em plan mode e proponha o plano para a issue 03.1. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
