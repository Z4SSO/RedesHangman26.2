# [00.1] Criar o repositório e subir o esqueleto

| | |
|---|---|
| **Responsável** | Todos |
| **Área** | fundação |
| **Prazo** | Dom 15/11 (noite) |
| **Branch** | `feat/00-1-repositorio` |
| **Depende de** | nenhuma |
| **Etiquetas** | `todos` `fundação` `Sprint Backlog` |
| **Especificação** | Material Disponibilizado |

## Contexto atual

O esqueleto do projeto (README, CLAUDE.md, contrato, módulos vazios, `protocol.py` e `config.py` prontos com testes) já foi gerado. Falta colocá-lo num repositório do grupo e deixar os três com o ambiente funcionando.

## Objetivo

Ter o repositório criado, protegido e com as issues importadas, e os três integrantes com o projeto rodando localmente.

## Dentro do escopo

- [ ] Criar o repositório privado do grupo (GitLab ou GitHub) e adicionar os três integrantes (e o professor, se for exigido)
- [ ] Subir o esqueleto na `main` e proteger a `main` (merge só por PR/MR, sem push direto)
- [ ] Criar o quadro com as colunas `Sprint Backlog`, `Doing`, `Review`, `Done` e as etiquetas de `docs/WORKFLOW.md`
- [ ] Importar `docs/issues/issues.csv` (GitLab: Issues → Import CSV) e atribuir cada issue à parte certa
- [ ] Preencher os nomes da equipe na tabela do `README.md`
- [ ] Cada pessoa: clonar, criar o venv, `pip install -r requirements-dev.txt`, rodar `python -m pytest -q`
- [ ] Cada pessoa: abrir o Claude Code na raiz e confirmar que ele leu o `CLAUDE.md`

## Fora do escopo

- Qualquer código de módulo (as issues 01 a 03 cuidam disso)

## Critérios de aceite

- [ ] Os três clonaram e `python -m pytest -q` passa
- [ ] Push direto na `main` é recusado
- [ ] As issues aparecem no quadro, com responsável e etiquetas
- [ ] Os nomes da equipe estão no `README.md`

## Itens a estudar

- Proteção de branch no GitLab/GitHub: Settings → Repository → Protected branches
- Importação de issues por CSV no GitLab (colunas `Title` e `Description`)

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/00-1-repositorio.md`. Releia na `docs/especificacao.md` as seções: Material Disponibilizado. Entre em plan mode e proponha o plano para a issue 00.1. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
