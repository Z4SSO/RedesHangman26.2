# [02.1] hangman.py: lógica pura do jogo + testes unitários

| | |
|---|---|
| **Responsável** | Parte B: Jogo |
| **Área** | jogo |
| **Prazo** | Seg 16/11 |
| **Branch** | `feat/02-1-hangman` |
| **Depende de** | [00.2](00-2-contrato.md) |
| **Etiquetas** | `parte-B` `jogo` `Sprint Backlog` |
| **Especificação** | Regras do jogo; GAME_START (word_hash); STATE; GUESS / GUESS_RESULT |

## Contexto atual

Toda regra do jogo cabe numa classe sem rede, o que permite testá-la a fundo e é o único ponto do trabalho que dá para terminar sem esperar ninguém. `forca/hangman.py` já tem as assinaturas.

## Objetivo

Implementar `normalize_word`, `Hangman` e `GuessOutcome` conforme o contrato (seção 5.5), com testes que cubram as 10 regras do jogo.

## Dentro do escopo

- [ ] `normalize_word`: minúsculas, remove acentos (`unicodedata`), recusa o que não for `a-z` e tamanho fora de 3..20 (`ValueError`)
- [ ] `Hangman(word, lives)`: `masked`, `wrong_letters` (em ordem), `lives`, `word_length`, `is_won`, `is_lost`
- [ ] `guess_letter`: certa revela todas as ocorrências; errada custa 1 vida e vai para `wrong_letters`; repetida (certa ou errada) é rejeitada com `letter_already_used`; fora de `a-z`, `invalid_letter`
- [ ] `guess_word`: certa vence (`revealed` = letras ainda ocultas); errada custa 1 vida e não revela nada; palavra inválida é `invalid_word` (sem custo)
- [ ] `word_hash` sobre a palavra **normalizada**
- [ ] `GuessOutcome.revealed` = número de ocorrências reveladas (base da pontuação)
- [ ] Testes unitários em `tests/test_hangman.py`: acento, palavra curta/longa/com hífen, letra repetida, vitória por letras, vitória por palavra, derrota, `masked` com letra repetida na palavra, hash conhecido (`casa`)

## Fora do escopo

- Turnos, jogadores, `STATE` e qualquer mensagem (issues 02.3 e 02.4)

## Critérios de aceite

- [ ] `normalize_word("Açaí")` devolve `"acai"`; `"ab"` e `"co-op"` levantam `ValueError`
- [ ] Com `banana`, adivinhar `a` dá `masked == "_a_a_a"` e `revealed == 3`
- [ ] Letra repetida **não** custa vida
- [ ] `is_lost` fica `True` exatamente quando `lives == 0`
- [ ] O módulo não importa `asyncio`, `socket` nem nada de `forca.*` além do que for puro
- [ ] `python -m pytest tests/test_hangman.py` verde

## Itens a estudar

- `unicodedata.normalize("NFKD", ...)` para tirar acentos
- `hashlib.sha256` e `hexdigest()` (minúsculo por padrão)

## Prompt sugerido para o Claude Code

```text
Leia `CLAUDE.md`, `docs/CONTRATO.md` e `docs/issues/02-1-hangman.md`. Releia na `docs/especificacao.md` as seções: Regras do jogo, GAME_START (word_hash), STATE, GUESS / GUESS_RESULT. Entre em plan mode e proponha o plano para a issue 02.1. Só implemente depois que eu aprovar, com os testes, e confira os critérios de aceite um a um no final.
```
