# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Apoio dos testes de jogo: Sender falso e fábrica de mensagens recebidas."""

from forca import protocol as p


class FakeSender:
    """Guarda (peer_id, msg) e valida cada envio: 'rígido ao enviar' (decisão 11)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def __call__(self, peer_id: str, msg: dict) -> bool:
        p.validate_envelope(msg, peer_id)
        self.sent.append((peer_id, msg))
        return True

    def of_type(self, type_: str, to: str | None = None) -> list[dict]:
        return [m for pid, m in self.sent if m["type"] == type_ and (to is None or pid == to)]

    def last(self) -> dict:
        return self.sent[-1][1]

    def clear(self) -> None:
        self.sent.clear()


def incoming(type_: str, src: str, dst: str, **fields) -> dict:
    """Mensagem recebida de outro peer, montada pelo protocol."""
    return p.new_message(type_, src=src, dst=dst, **fields)
