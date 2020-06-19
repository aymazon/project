""""""
import typing as t  # noqa
from common import PROJECT_NAME, APP_NAME, LOGGER, ServiceBase  # noqa

import traceback
import Pyro4

from flask import Flask
from flask_restful import Resource, Api

from common import create_g_consult, get_health_service_rpc_proxy

create_g_consult()

app = Flask(__name__)
api = Api(app)


class HelloWorld(Resource):
    def get(self) -> t.Dict[str, t.Any]:
        try:
            rpc_proxy: Pyro4.Proxy = get_health_service_rpc_proxy('pong')
        except LookupError as e:
            LOGGER.error(f"{e}: {traceback.format_exc()}")
            return {'hello': f'error {e}'}
        LOGGER.info(rpc_proxy.dev_ping(1, src='duang'))
        return {'hello': 'world'}


api.add_resource(HelloWorld, '/')
