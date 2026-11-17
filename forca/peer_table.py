"""Tabela de peers: estados, eventos e reconciliação com o Rendezvous.

Dono: Pessoa A. Issues 01.2 (este arquivo) e 01.6 (backoff). Logger: "PeerTable".

Especificação, "Gerenciamento de Conexões e Reconexões":
- estados: DISCOVERED (visto no Rendezvous, sem conexão), CONNECTING,
  CONNECTED (após HELLO_OK), STALE (conexão perdida), GONE (removido do
  Rendezvous ou limite de tentativas atingido);
- reconciliação: após cada DISCOVER, peers novos entram DISCOVERED e recebem
  tentativa de conexão; peers ausentes viram GONE e a conexão fecha com BYE.

A tabela NÃO abre sockets: recebe `connect_fn` (na prática `PeerServer.connect`)
e é avisada pelo PeerServer quando uma conexão fica pronta (`attach`) ou cai
(`detach`). Assim ela é testável sem rede, com conexões falsas.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

from .config import Config
from .models import PeerState

if TYPE_CHECKING:  # só para type hints; evita import circular em tempo de execução
    from .peer_connection import PeerConnection

log = logging.getLogger("PeerTable")

# Eventos que os outros módulos assinam (ver CONTRATO.md, seção 5.2).
EVENT_CONNECTED = "peer_connected"  # callback(peer_id)
EVENT_STALE = "peer_stale"  # callback(peer_id)  -> host remove jogador / jogador aborta
EVENT_GONE = "peer_gone"  # callback(peer_id)
EVENTS = (EVENT_CONNECTED, EVENT_STALE, EVENT_GONE)

ConnectFn = Callable[[str, int], Awaitable["PeerConnection | None"]]
Callback = Callable[[str], Awaitable[None]]


def backoff_delay(n: int, base: float, max_: float) -> float:
    """Espera antes da tentativa de reconexão número `n` (0, 1, 2, ...):
    `base × 2^n`, limitada a `max_` (especificação, "Gerenciamento de
    Conexões e Reconexões"). Com os padrões: 2, 4, 8, 16, 32, 60, 60..."""
    return min(base * 2**n, max_)


@dataclass
class PeerEntry:
    """Uma linha da tabela. `ip`/`port` vêm do DISCOVER (None se o peer só
    apareceu por conexão de entrada e ainda não foi visto no Rendezvous)."""

    peer_id: str
    ip: str | None = None
    port: int | None = None
    state: PeerState = PeerState.DISCOVERED
    conn: "PeerConnection | None" = None
    attempts: int = 0  # reconexões já agendadas desde que o peer ficou STALE
    next_retry: float | None = None  # instante (loop.time()) da próxima tentativa
    retry_task: asyncio.Task | None = field(default=None, repr=False)  # espera pendente


class PeerTable:
    def __init__(self, cfg: Config, connect_fn: ConnectFn) -> None:
        self.cfg = cfg
        self._connect_fn = connect_fn
        self._entries: dict[str, PeerEntry] = {}
        self._subscribers: dict[str, list[Callback]] = {e: [] for e in EVENTS}
        self._tasks: set[asyncio.Task] = set()
        self._closing = False  # depois de close_all(), quedas não geram eventos

    # --- consulta -----------------------------------------------------------

    def subscribe(self, event: str, callback: Callback) -> None:
        """Assina um evento. `callback` é `async def cb(peer_id: str)`."""
        if event not in self._subscribers:
            raise ValueError(f"unknown event {event!r}")
        self._subscribers[event].append(callback)

    def state_of(self, peer_id: str) -> PeerState | None:
        entry = self._entries.get(peer_id)
        return entry.state if entry else None

    def peers(self) -> list[PeerEntry]:
        """Todas as entradas (para o /peers da CLI)."""
        return list(self._entries.values())

    def connected(self) -> list["PeerConnection"]:
        """Conexões CONNECTED (exatamente uma por vizinho)."""
        return [
            e.conn
            for e in self._entries.values()
            if e.state == PeerState.CONNECTED and e.conn is not None
        ]

    # --- envio --------------------------------------------------------------

    async def send_to(self, peer_id: str, msg: dict) -> bool:
        """Implementação do `Sender` (models.Sender).

        True se escreveu no socket; False se o peer não está conectado.
        Nunca levanta por peer ausente.
        """
        entry = self._entries.get(peer_id)
        if entry is None or entry.state != PeerState.CONNECTED or entry.conn is None:
            log.debug("send_to %s: not connected, dropping %s", peer_id, msg.get("type"))
            return False
        try:
            return await entry.conn.send(msg)
        except Exception:  # send() não deveria levantar; defesa extra
            log.exception("send_to %s failed", peer_id)
            return False

    async def broadcast(self, msg_factory: Callable[[str], dict]) -> None:
        """Envia a todos os conectados; `msg_factory(peer_id)` monta a mensagem
        de cada um (o `dst` muda). Uma falha não impede os outros envios."""
        peer_ids = [c.peer_id for c in self.connected()]
        results = await asyncio.gather(
            *(self.send_to(pid, msg_factory(pid)) for pid in peer_ids),
            return_exceptions=True,
        )
        for pid, res in zip(peer_ids, results):
            if isinstance(res, BaseException):
                log.warning("broadcast to %s failed: %r", pid, res)

    # --- reconciliação com o Rendezvous --------------------------------------

    async def reconcile(self, discovered: list[dict]) -> None:
        """Aplica o resultado de um DISCOVER.

        - peer novo (ou que estava GONE) -> DISCOVERED + tentativa de conexão
          em segundo plano (não espera a conexão terminar);
        - peer que estava na tabela e sumiu -> GONE, fecha com BYE, evento
          `peer_gone`.
        """
        if self._closing:
            return
        seen: set[str] = set()
        for item in discovered:
            name, namespace = item.get("name"), item.get("namespace")
            ip, port = item.get("ip"), item.get("port")
            if not (isinstance(name, str) and isinstance(namespace, str)
                    and isinstance(ip, str) and isinstance(port, int)):
                log.debug("ignoring malformed DISCOVER item %r", item)
                continue
            peer_id = f"{name}@{namespace}"
            if peer_id == self.cfg.peer_id:
                continue  # rdv.discover() já filtra; defesa extra
            seen.add(peer_id)

            entry = self._entries.get(peer_id)
            if entry is None:
                entry = PeerEntry(peer_id, ip, port)
                self._entries[peer_id] = entry
                log.info("%s DISCOVERED at %s:%s", peer_id, ip, port)
                self._spawn_connect(entry)
                continue

            entry.ip, entry.port = ip, port
            if entry.state == PeerState.GONE:
                # voltou ao Rendezvous: recomeça do zero
                entry.state = PeerState.DISCOVERED
                entry.attempts, entry.next_retry = 0, None
                log.info("%s DISCOVERED again at %s:%s", peer_id, ip, port)
                self._spawn_connect(entry)
            elif entry.state == PeerState.STALE and entry.retry_task is None:
                # caiu quando ainda não sabíamos o endereço (só tinha conexão de
                # entrada): agora o DISCOVER trouxe, então tenta
                self._spawn_connect(entry)

        absent = [e for pid, e in list(self._entries.items())
                  if pid not in seen and e.state != PeerState.GONE]
        # cada fechamento espera o BYE_OK por até 2 s: em paralelo, para vários
        # peers ausentes não atrasarem a reconciliação em 2 s por peer
        await asyncio.gather(*(self._mark_gone(e, "absent from DISCOVER") for e in absent))

    # --- avisos do PeerServer ----------------------------------------------

    async def attach(self, conn: "PeerConnection") -> None:
        """Uma conexão concluiu o HELLO (de entrada ou de saída).

        O PeerServer já resolveu duplicadas (01.4) antes de chamar aqui; se
        mesmo assim chegar outra conexão para o mesmo peer, a nova substitui a
        antiga. Chamar duas vezes com a mesma conexão não faz nada.
        """
        if self._closing:
            return
        entry = self._entries.get(conn.peer_id)
        if entry is None:
            # conexão de entrada de quem ainda não vimos no DISCOVER
            entry = PeerEntry(conn.peer_id)
            self._entries[conn.peer_id] = entry
        if entry.conn is conn and entry.state == PeerState.CONNECTED:
            return
        was_connected = entry.state == PeerState.CONNECTED
        self._cancel_retry(entry)  # reconectou (por nós ou pelo vizinho): sem espera pendente
        entry.conn = conn
        entry.state = PeerState.CONNECTED
        entry.attempts, entry.next_retry = 0, None
        if was_connected:
            # troca de conexão do mesmo vizinho (desempate de duplicada): o
            # vizinho nunca deixou de estar conectado, então não há evento
            log.info("%s connection replaced (%s)", conn.peer_id, getattr(conn, "direction", "?"))
            return
        log.info("%s CONNECTED (%s)", conn.peer_id, getattr(conn, "direction", "?"))
        await self._emit(EVENT_CONNECTED, conn.peer_id)

    async def detach(self, conn: "PeerConnection") -> None:
        """Uma conexão caiu (socket fechado, 3 PINGs sem PONG, BYE recebido).

        Só conta se `conn` for a conexão atual do peer: o fechamento de uma
        duplicada descartada ou de um peer já GONE é ignorado. Senão o peer
        vira STALE e o evento `peer_stale` é emitido (gatilho de falha do jogo).
        """
        entry = self._entries.get(conn.peer_id)
        if self._closing or entry is None or entry.conn is not conn:
            return
        entry.conn = None
        if entry.state == PeerState.GONE:
            return
        entry.state = PeerState.STALE
        log.warning("%s STALE (connection lost)", conn.peer_id)
        await self._emit(EVENT_STALE, conn.peer_id)
        await self._schedule_retry(entry)

    # --- encerramento -------------------------------------------------------

    async def close_all(self, reason: str = "shutdown") -> None:
        """BYE a todos os vizinhos (cada um espera BYE_OK por até 2 s, em
        paralelo) e cancela as tentativas de conexão pendentes. Usado no /quit."""
        self._closing = True
        for task in list(self._tasks):
            task.cancel()
        conns = self.connected()
        await asyncio.gather(*(c.close(reason) for c in conns), return_exceptions=True)
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for entry in self._entries.values():
            entry.conn = None

    # --- interno ------------------------------------------------------------

    def _spawn_connect(self, entry: PeerEntry) -> None:
        """Dispara a conexão em segundo plano e guarda a tarefa (cancelada no
        close_all). Uma conexão lenta não atrasa a reconciliação dos outros."""
        self._track(asyncio.create_task(self._connect(entry), name=f"connect {entry.peer_id}"))

    async def _connect(self, entry: PeerEntry) -> None:
        if entry.state not in (PeerState.DISCOVERED, PeerState.STALE):
            return
        if entry.ip is None or entry.port is None:
            return
        entry.state = PeerState.CONNECTING
        try:
            conn = await self._connect_fn(entry.ip, entry.port)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("connect to %s crashed", entry.peer_id)
            conn = None

        if self._closing:
            return
        if conn is not None and entry.state == PeerState.GONE:
            # sumiu do Rendezvous enquanto conectávamos: desfaz
            await conn.close("gone")
        elif conn is not None:
            await self.attach(conn)
        elif entry.state == PeerState.CONNECTING:
            # falhou, e nenhuma conexão de entrada apareceu nesse meio tempo:
            # STALE e nova tentativa com backoff
            entry.state = PeerState.STALE
            log.info("%s unreachable at %s:%s", entry.peer_id, entry.ip, entry.port)
            await self._schedule_retry(entry)
        # se virou CONNECTED por uma conexão de entrada (desempate de
        # duplicada, 01.4) ou GONE durante a espera, não mexe.

    # --- reconexão com backoff (01.6) ---------------------------------------

    async def _schedule_retry(self, entry: PeerEntry) -> None:
        """Agenda a próxima tentativa de reconexão de um peer STALE.

        A espera é `backoff_delay(attempts)` e usa `asyncio.sleep` dentro de uma
        tarefa própria: não bloqueia nada nem as outras conexões. Depois de
        `max_reconnect_attempts` tentativas o peer vira GONE (até reaparecer
        num DISCOVER).
        """
        if self._closing or entry.ip is None or entry.port is None:
            return  # sem endereço não há o que tentar; o próximo DISCOVER traz
        if entry.retry_task is not None:
            return  # já há uma espera pendente
        if entry.attempts >= self.cfg.max_reconnect_attempts:
            await self._mark_gone(entry, f"gave up after {entry.attempts} reconnect attempts")
            return
        delay = backoff_delay(entry.attempts, self.cfg.base_backoff, self.cfg.max_backoff)
        entry.attempts += 1
        entry.next_retry = asyncio.get_running_loop().time() + delay
        log.info("%s reconnect attempt %d/%d in %.1f s",
                 entry.peer_id, entry.attempts, self.cfg.max_reconnect_attempts, delay)
        entry.retry_task = self._track(
            asyncio.create_task(self._retry(entry, delay), name=f"retry {entry.peer_id}")
        )

    async def _retry(self, entry: PeerEntry, delay: float) -> None:
        await asyncio.sleep(delay)
        entry.retry_task = None  # a espera acabou: daqui em diante não se cancela
        entry.next_retry = None
        await self._connect(entry)

    def _cancel_retry(self, entry: PeerEntry) -> None:
        """Cancela a espera pendente (se houver e se não for a tarefa atual)."""
        task, entry.retry_task = entry.retry_task, None
        entry.next_retry = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def retry_now(self) -> None:
        """Para o `/reconnect`: tenta já todos os peers STALE, sem esperar o
        backoff, e recomeça a contagem de tentativas deles."""
        if self._closing:
            return
        for entry in self._entries.values():
            if entry.state == PeerState.STALE and entry.ip is not None:
                self._cancel_retry(entry)
                entry.attempts = 0
                self._spawn_connect(entry)

    def _track(self, task: asyncio.Task) -> asyncio.Task:
        """Guarda a tarefa para o close_all() cancelar."""
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _mark_gone(self, entry: PeerEntry, why: str) -> None:
        self._cancel_retry(entry)
        entry.state = PeerState.GONE
        conn, entry.conn = entry.conn, None
        log.info("%s GONE (%s)", entry.peer_id, why)
        if conn is not None:
            try:
                await conn.close("gone")
            except Exception:
                log.exception("closing %s failed", entry.peer_id)
        await self._emit(EVENT_GONE, entry.peer_id)

    async def _emit(self, event: str, peer_id: str) -> None:
        """Chama os assinantes em ordem. Um callback com erro é registrado no
        log e não impede os outros (mensagem/evento nunca derruba o programa)."""
        for cb in list(self._subscribers[event]):
            try:
                await cb(peer_id)
            except Exception:
                log.exception("%s callback failed for %s", event, peer_id)
