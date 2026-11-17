"""Mensagens peer–peer: envelope, codificação e validação.

Este módulo é a ÚNICA fonte de verdade do formato das mensagens. Todos os
módulos montam e validam mensagens por aqui, nunca com dicionários soltos.
Não importa nada de rede nem de outros módulos do projeto.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

PROTOCOL_VERSION = "1.0"
FEATURE_HANGMAN = "hangman"
MAX_LINE_BYTES = 32768
FIXED_TTL = 1

# --- tipos de mensagem -----------------------------------------------------

# Mensagens de conexão: o par já é conhecido pelo socket, então omitem src/dst.
CONNECTION_TYPES = frozenset({"HELLO", "HELLO_OK", "PING", "PONG"})

SESSION_TYPES = frozenset(
    {"HELLO", "HELLO_OK", "PING", "PONG", "BYE", "BYE_OK", "ERROR"}
)
LOBBY_TYPES = frozenset(
    {
        "GAME_LIST",
        "GAME_LIST_OK",
        "JOIN",
        "JOIN_OK",
        "JOIN_ERR",
        "LEAVE",
        "LEAVE_OK",
    }
)
GAME_TYPES = frozenset(
    {"GAME_START", "STATE", "GUESS", "GUESS_RESULT", "GAME_OVER", "CHAT"}  # CHAT: bônus 05.2
)
CHAT_MAX_LEN = 200
ALL_TYPES = SESSION_TYPES | LOBBY_TYPES | GAME_TYPES

# Campos obrigatórios NA RECEPÇÃO por tipo, além do envelope (type, msg_id, ttl,
# src, dst). Regra do projeto: rígido ao enviar, tolerante ao receber. Por isso
# `STATE.last_guess` e `word`/`winner`/`scores` do GAME_OVER (que podem faltar num
# ABORTED de outro cliente) não são exigidos aqui. Ao ENVIAR, preencha-os sempre.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "HELLO": ("peer_id", "version", "features"),
    "HELLO_OK": ("peer_id", "version", "features"),
    "PING": ("timestamp",),
    "PONG": ("timestamp",),
    "BYE": ("reason",),
    "BYE_OK": (),
    "ERROR": ("code", "message"),
    "GAME_LIST": (),
    "GAME_LIST_OK": ("games",),
    "JOIN": ("game_id",),
    "JOIN_OK": ("game_id", "players", "rejoin"),
    "JOIN_ERR": ("game_id", "reason"),
    "LEAVE": ("game_id",),
    "LEAVE_OK": ("game_id",),
    "GAME_START": (
        "game_id",
        "players",
        "lives",
        "word_length",
        "word_hash",
        "turn_timeout",
    ),
    "STATE": (
        "game_id",
        "seq",
        "masked",
        "wrong_letters",
        "lives",
        "turn",
        "players",
    ),
    "GUESS": ("game_id",),  # + exatamente um entre "letter" e "word"
    "GUESS_RESULT": ("game_id", "accepted"),
    "GAME_OVER": ("game_id", "result"),
    "CHAT": ("game_id", "text"),  # bônus; `from` só no repasse do host
}


# Tipo esperado de cada campo (checado só se o campo estiver presente; a
# presença é checada por REQUIRED_FIELDS). Tipos: "str", "int", "bool",
# "list_str" (lista de strings), "list", "dict", "dict_or_null", "str_or_null".
FIELD_TYPES: dict[str, dict[str, str]] = {
    "HELLO": {"peer_id": "str", "version": "str", "features": "list_str"},
    "HELLO_OK": {"peer_id": "str", "version": "str", "features": "list_str"},
    "PING": {"timestamp": "str"},
    "PONG": {"timestamp": "str"},
    "BYE": {"reason": "str"},
    "ERROR": {"code": "str", "message": "str", "ref_msg_id": "str"},
    "GAME_LIST_OK": {"games": "list"},
    "JOIN": {"game_id": "str"},
    "JOIN_OK": {"game_id": "str", "players": "list_str", "rejoin": "bool"},
    "JOIN_ERR": {"game_id": "str", "reason": "str"},
    "LEAVE": {"game_id": "str"},
    "CHAT": {"game_id": "str", "text": "str", "from": "str"},
    "LEAVE_OK": {"game_id": "str"},
    "GAME_START": {
        "game_id": "str",
        "players": "list_str",
        "lives": "int",
        "word_length": "int",
        "word_hash": "str",
        "turn_timeout": "int",
    },
    "STATE": {
        "game_id": "str",
        "seq": "int",
        "masked": "str",
        "wrong_letters": "list_str",
        "lives": "int",
        "turn": "str",
        "players": "list_str",
        "last_guess": "dict_or_null",
    },
    "GUESS": {"game_id": "str", "letter": "str", "word": "str"},
    "GUESS_RESULT": {
        "game_id": "str",
        "accepted": "bool",
        "reason": "str",
        "correct": "bool",
    },
    "GAME_OVER": {
        "game_id": "str",
        "result": "str",
        "word": "str",
        "winner": "str_or_null",
        "scores": "dict",
        "reason": "str",
    },
}


def _type_ok(value: object, kind: str) -> bool:
    # bool é subclasse de int em Python: não aceitar True como inteiro.
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list)
    if kind == "list_str":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if kind == "dict":
        return isinstance(value, dict)
    if kind == "dict_or_null":
        return value is None or isinstance(value, dict)
    if kind == "str_or_null":
        return value is None or isinstance(value, str)
    return True


class ErrorCode:
    """Valores do campo `code` da mensagem ERROR."""

    UNKNOWN_TYPE = "unknown_type"
    BAD_REQUEST = "bad_request"
    NOT_FOR_ME = "not_for_me"
    INVALID_STATE = "invalid_state"
    BAD_JSON = "bad_json"


class JoinErrReason:
    UNKNOWN_GAME = "unknown_game"
    GAME_FULL = "game_full"
    GAME_RUNNING = "game_running"
    GAME_FINISHED = "game_finished"
    ALREADY_JOINED = "already_joined"


class GuessRejectReason:
    NOT_YOUR_TURN = "not_your_turn"
    LETTER_ALREADY_USED = "letter_already_used"
    INVALID_LETTER = "invalid_letter"
    INVALID_WORD = "invalid_word"
    GAME_NOT_RUNNING = "game_not_running"


class ProtocolError(Exception):
    """Mensagem inválida.

    `code` é um ErrorCode. Se `silent` for True, a mensagem deve ser apenas
    descartada, sem responder ERROR (ex.: ttl diferente de 1).
    """

    def __init__(
        self,
        code: str,
        message: str,
        ref_msg_id: str | None = None,
        silent: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.ref_msg_id = ref_msg_id
        self.silent = silent


# --- identidade -------------------------------------------------------------


def make_peer_id(name: str, namespace: str) -> str:
    return f"{name}@{namespace}"


def split_peer_id(peer_id: str) -> tuple[str, str]:
    name, _, namespace = peer_id.partition("@")
    return name, namespace


def new_msg_id() -> str:
    return str(uuid.uuid4())


def now_iso(millis: bool = False) -> str:
    """Instante atual em ISO 8601 UTC, ex.: 2026-10-27T10:00:00Z."""
    now = datetime.now(timezone.utc)
    if millis:
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- construção -------------------------------------------------------------


def new_message(
    type_: str,
    *,
    src: str | None = None,
    dst: str | None = None,
    msg_id: str | None = None,
    **fields: Any,
) -> dict:
    """Monta uma mensagem com o envelope preenchido.

    `src`/`dst` só entram se informados (HELLO/PING não os carregam).
    """
    msg: dict[str, Any] = {"type": type_, "msg_id": msg_id or new_msg_id()}
    if src is not None:
        msg["src"] = src
    if dst is not None:
        msg["dst"] = dst
    msg.update(fields)
    msg["ttl"] = FIXED_TTL
    return msg


def reply(request: dict, type_: str, **fields: Any) -> dict:
    """Resposta a `request`: repete o msg_id e inverte src/dst.

    Use para *_OK, JOIN_ERR, PONG, GUESS_RESULT, BYE_OK.
    """
    return new_message(
        type_,
        src=request.get("dst"),
        dst=request.get("src"),
        msg_id=request["msg_id"],
        **fields,
    )


def make_error(
    request: dict | None, code: str, message: str, src: str | None = None
) -> dict:
    """Monta um ERROR. Tem msg_id novo e aponta para a causa em ref_msg_id."""
    fields: dict[str, Any] = {"code": code, "message": message}
    if request is not None and "msg_id" in request:
        fields["ref_msg_id"] = request["msg_id"]
    return new_message(
        "ERROR",
        src=src,
        dst=request.get("src") if request else None,
        **fields,
    )


# --- codificação ------------------------------------------------------------


def encode(msg: dict) -> bytes:
    """Serializa para uma única linha JSON UTF-8 terminada em \\n."""
    data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) + 1 > MAX_LINE_BYTES:
        raise ProtocolError(ErrorCode.BAD_REQUEST, "line too long")
    return data + b"\n"


def decode(line: bytes | str) -> dict:
    """Converte uma linha em dict. Levanta ProtocolError(BAD_JSON) se inválida."""
    if isinstance(line, bytes):
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(ErrorCode.BAD_JSON, f"invalid utf-8: {exc}") from exc
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(ErrorCode.BAD_JSON, f"invalid json: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError(ErrorCode.BAD_JSON, "message must be a JSON object")
    return obj


# --- validação --------------------------------------------------------------


def validate_envelope(msg: dict, local_peer_id: str | None = None) -> None:
    """Valida envelope e campos obrigatórios. Levanta ProtocolError se inválida.

    Ordem das checagens (a mesma da especificação):
      1. type conhecido            -> unknown_type
      2. msg_id string, ttl == 1   -> ttl errado é descartada em silêncio
      3. src/dst (exceto tipos de conexão)
      4. dst == local_peer_id      -> not_for_me
      5. campos obrigatórios do tipo -> bad_request
      6. tipo de cada campo presente (FIELD_TYPES) -> bad_request
    """
    ref = msg.get("msg_id") if isinstance(msg.get("msg_id"), str) else None
    type_ = msg.get("type")

    if not isinstance(type_, str) or type_ not in ALL_TYPES:
        raise ProtocolError(ErrorCode.UNKNOWN_TYPE, f"unknown type {type_!r}", ref)

    if not isinstance(msg.get("msg_id"), str) or not msg["msg_id"]:
        raise ProtocolError(ErrorCode.BAD_REQUEST, "missing msg_id")

    if msg.get("ttl") != FIXED_TTL:
        raise ProtocolError(
            ErrorCode.BAD_REQUEST, f"ttl must be {FIXED_TTL}", ref, silent=True
        )

    if type_ not in CONNECTION_TYPES:
        for key in ("src", "dst"):
            if not isinstance(msg.get(key), str) or not msg[key]:
                raise ProtocolError(ErrorCode.BAD_REQUEST, f"missing {key}", ref)
        if local_peer_id is not None and msg["dst"] != local_peer_id:
            raise ProtocolError(
                ErrorCode.NOT_FOR_ME, f"dst {msg['dst']} is not {local_peer_id}", ref
            )

    for key in REQUIRED_FIELDS[type_]:
        if key not in msg:
            raise ProtocolError(ErrorCode.BAD_REQUEST, f"missing field {key}", ref)

    if type_ == "GUESS":
        if ("letter" in msg) == ("word" in msg):
            raise ProtocolError(
                ErrorCode.BAD_REQUEST, "GUESS needs exactly one of letter/word", ref
            )

    for key, kind in FIELD_TYPES.get(type_, {}).items():
        if key in msg and not _type_ok(msg[key], kind):
            raise ProtocolError(
                ErrorCode.BAD_REQUEST, f"field {key} must be {kind}", ref
            )
