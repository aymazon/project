""""""
import typing as t  # noqa
from common import PROJECT_NAME, APP_NAME, LOGGER, ServiceBase  # noqa

from nameko.constants import NON_PERSISTENT
from nameko.events import EventDispatcher, event_handler, BROADCAST
from nameko.rpc import RpcProxy
from nameko.timer import timer
import Pyro4

from common import get_redis_client, get_health_service_rpc_proxy


def count_daemon_process() -> int:
    return 1


g_dev_start_xxx_i = 0


@Pyro4.expose
class Service(ServiceBase):
    name = APP_NAME

    dispatch = EventDispatcher(delivery_mode=NON_PERSISTENT)

    pong = RpcProxy("pong", delivery_mode=NON_PERSISTENT)

    @event_handler("pong", "processed", handler_type=BROADCAST, reliable_delivery=False)
    def handle_processed_event(self, event_data: t.Dict[str, t.Any]) -> None:
        r = get_redis_client()
        processing_key = (f"{PROJECT_NAME}.{APP_NAME}.is_processing." f"{event_data['xxx_id']}")
        with r.Lock(f"{processing_key}-lock", expire=5):
            key_num = r.get(processing_key)
            if key_num is None:
                r.set(processing_key, '1', ex=60)
                detecting_num = 1
            else:
                detecting_num = int(key_num)  # type: ignore

        if detecting_num > 4:
            # LOGGER.info(f"ignore processing {event_data['xxx_id']}")
            return

        try:
            r.expire(processing_key, 60)
            r.incr(processing_key)
            # TODO: process something
        finally:
            r.decr(processing_key)

    @timer(interval=3)
    def dev_start_xxx(self):
        global g_dev_start_xxx_i
        g_dev_start_xxx_i += 1
        if g_dev_start_xxx_i > 5:
            return

        self.pong.start_pong(g_dev_start_xxx_i)

    @timer(interval=1.1)
    def dev_ping(self):
        rpc_proxy = get_health_service_rpc_proxy('pong')
        LOGGER.info(rpc_proxy.dev_pyro4_ping(1, src='ping'))
