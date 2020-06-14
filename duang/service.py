""""""
import typing as t  # noqa
from common import PROJECT_NAME, APP_NAME, LOGGER, ServiceBase  # noqa

from flask import Flask
from flask_restful import Resource, Api

from common import create_g_consult, get_health_service_rpc_proxy

create_g_consult()

app = Flask(__name__)
api = Api(app)


class HelloWorld(Resource):
    def get(self):
        rpc_proxy = get_health_service_rpc_proxy('pong')
        LOGGER.info(rpc_proxy.dev_ping(1, src='duang'))
        return {'hello': 'world'}


api.add_resource(HelloWorld, '/')
