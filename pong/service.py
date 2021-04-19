""""""
import typing as t  # noqa
from common import PROJECT_NAME, APP_NAME, LOGGER, ServiceBase  # noqa

import os
import signal
import time
import psutil
import threading

from nameko.constants import NON_PERSISTENT
from nameko.events import EventDispatcher, event_handler, BROADCAST
from nameko.rpc import rpc
import Pyro4

from common import get_redis_client


def count_daemon_process() -> int:
    return psutil.cpu_count(logical=False) + 1


g_processing_xxx_id = 0


@Pyro4.expose
class Service(ServiceBase):
    name = APP_NAME

    dispatch = EventDispatcher(delivery_mode=NON_PERSISTENT)

    @rpc
    def start_pong(self, xxx_id: int) -> None:
        global g_processing_xxx_id
        r = get_redis_client()
        processing_key = (f"{PROJECT_NAME}.{APP_NAME}.xxx.is_processing.{xxx_id}")
        if r.get(processing_key) == '1':
            LOGGER.info(f"ignore processing xxx {xxx_id}")
            return
        r.set(processing_key, '1', ex=30)
        g_processing_xxx_id = xxx_id

        list(range(10000))

        def start() -> None:
            LOGGER.info(f"start_work with {xxx_id}")
            list(range(20000))
            try:
                while True:
                    list(range(3000))
                    self.dispatch("processed", {
                        'xxx_id': xxx_id,
                        'info': {},
                    })
                    r.expire(processing_key, 3)
                    time.sleep(1)
            finally:
                r.delete(processing_key)

        # threading.Thread(target=start, daemon=True).start()

    @event_handler("ping", "stop_pong", handler_type=BROADCAST, reliable_delivery=False)
    def handle_stop_pong_event(self, event_data: t.Dict[str, t.Any]) -> None:
        global g_processing_xxx_id
        xxx_id = event_data['xxx_id']
        if xxx_id != g_processing_xxx_id:
            return
        LOGGER.info("stop self")

        def kill_self() -> None:
            time.sleep(0.1)
            os.kill(os.getpid(), signal.SIGQUIT)

        threading.Thread(target=kill_self, daemon=True).start()

    @rpc
    def dev_nameko_ping(self, i: int, src: str):
        return f"pong {i} from {src} by nameko"

    def dev_pyro4_ping(self, i: int, src: str):
        return f"pong {i} from {src} by Pyro4"
