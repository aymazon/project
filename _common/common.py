import typing as t  # noqa
from pysnooper import snoop  # noqa

import cProfile
import pstats
import io
import os
import sys
import time
import signal
import pprofile
import psutil
import subprocess
import threading
import logging
import logging.config
import socket
import random
import shutil

from functools import partial, wraps, total_ordering, lru_cache, update_wrapper

import yaml

import consul
import redis
import redis_lock

from nameko.timer import timer
from nameko.standalone.rpc import ClusterRpcProxy
from nameko.cli.main import setup_yaml_parser
import Pyro4

PROJECT_NAME = os.environ['PROJECT_NAME']
APP_NAME = os.environ['APP_NAME']


def cprofile_print_stats(max_call_num: int = 1,
                         step: int = 1,
                         sort_key: int = 2):
    """ cprofile print stats
    Args:
        sort_key: {-1: "stdname", 0: "calls", 1: "time", 2: "cumulative"}
    """
    def wrapper(func):
        r = get_redis_client()
        key = f"{PROJECT_NAME}.{APP_NAME}.cprofile_print_stats"
        with r.Lock(f"{key}-lock", expire=5):
            key_num = r.get(key)
            if key_num is None:
                r.set(key, '0')
            elif int(key_num) >= max_call_num:
                r.set(key, '0')

        @wraps(func)
        def inner_wrapper(*args, **kwargs):
            r.incr(key)
            call_num = int(r.get(key))
            if call_num > max_call_num or (call_num - 1) % step != 0:
                return func(*args, **kwargs)
            print_title = (' ' * 30 + f'-*-cprofile_print_stats-*-|{call_num}')

            pr = cProfile.Profile()
            pr.enable()
            result = func(*args, **kwargs)
            pr.disable()

            print('-' * 100)
            print(print_title)
            print('-' * 100)
            print('')
            s = io.StringIO()
            ps = pstats.Stats(pr, stream=s).sort_stats(sort_key)
            ps.print_stats()
            print(s.getvalue())
            return result

        return inner_wrapper

    return wrapper


def _pprofile_dump(prof: pprofile.Profile, file_path: str,
                   need_rmtree) -> None:
    def _pprofile_copy_files() -> None:
        name: str
        for name, lines in prof.iterSource():
            src_file = name
            if name.startswith('./'):
                dst_file = f"{dir_path}{name[1:]}"
            else:
                dst_file = f"{dir_path}{name}"
            dst_path = os.path.dirname(dst_file)
            os.makedirs(dst_path, exist_ok=True)
            if not os.path.exists(dst_file):
                shutil.copyfile(src_file, dst_file)

    dir_path = os.path.dirname(file_path)
    if need_rmtree:
        shutil.rmtree(dir_path, ignore_errors=True)
    os.makedirs(dir_path, exist_ok=True)
    with io.open(file_path, 'w', errors='replace') as fp:
        prof.callgrind(fp, relative_path=True)
    _pprofile_copy_files()


def pprofile_dump_stats(max_call_num: int = 1, step: int = 1):
    """ pprofile print stats """
    def wrapper(func):
        r = get_redis_client()
        key = f"{PROJECT_NAME}.{APP_NAME}.pprofile_print_stats"
        with r.Lock(f"{key}-lock", expire=5):
            key_num = r.get(key)
            if key_num is None:
                r.set(key, '0')
            elif int(key_num) >= max_call_num:
                r.set(key, '0')

        @wraps(func)
        def inner_wrapper(*args, **kwargs):
            r.incr(key)
            call_num = int(r.get(key))
            if call_num > max_call_num or (call_num - 1) % step != 0:
                return func(*args, **kwargs)
            print_title = (' ' * 30 + f'-*-pprofile_print_stats-*-|{call_num}')

            prof = pprofile.Profile()
            with prof():
                result = func(*args, **kwargs)
            print('-' * 100)
            print(print_title)
            print('-' * 100)
            print('')
            _pprofile_dump(
                prof, f"/tmp/{PROJECT_NAME}/pp/cachegrind.out.{call_num}",
                call_num == 1)
            return result

        return inner_wrapper

    return wrapper


def pprofile_dump_statistical_stats(max_call_num: int = 1, step: int = 1):
    """ pprofile dump statistical stats """
    def wrapper(func):
        r = get_redis_client()
        key = f"{PROJECT_NAME}.{APP_NAME}.pprofile_print_statistical_stats"
        with r.Lock(f"{key}-lock", expire=5):
            key_num = r.get(key)
            if key_num is None:
                r.set(key, '0')
            elif int(key_num) >= max_call_num:
                r.set(key, '0')

        @wraps(func)
        def inner_wrapper(*args, **kwargs):
            r.incr(key)
            call_num = int(r.get(key))
            if call_num > max_call_num or (call_num - 1) % step != 0:
                return func(*args, **kwargs)
            print_title = (
                ' ' * 30 +
                f'-*-pprofile_print_statistical_stats-*-|{call_num}')

            prof = pprofile.StatisticalProfile()
            with prof(period=0.001, single=True):
                result = func(*args, **kwargs)
            print('-' * 100)
            print(print_title)
            print('-' * 100)
            print('')
            _pprofile_dump(
                prof, f"/tmp/{PROJECT_NAME}/pp/cachegrind.out.{call_num}",
                call_num == 1)
            return result

        return inner_wrapper

    return wrapper


def synchronized(lock):  # type: ignore
    """ Synchronization decorator """
    def wrapper(f):  # type: ignore
        @wraps(f)
        def inner_wrapper(*args, **kw):  # type: ignore
            with lock:
                return f(*args, **kw)

        return inner_wrapper

    return wrapper


_g_singleton_type_lock = threading.RLock()


class Singleton(type):
    """ Singleton mix class """
    _instances = {}  # type: ignore

    def __call__(cls, *args, **kwargs):  # type: ignore
        if cls not in cls._instances:
            cls._locked_call(*args, **kwargs)
        return cls._instances[cls]

    @synchronized(_g_singleton_type_lock)  # type: ignore
    def _locked_call(cls, *args, **kwargs):  # type: ignore
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton,
                                        cls).__call__(*args, **kwargs)


_g_singleton_actor_proxy_type_lock = threading.RLock()


class SingletonActorProxy(type):
    """ SingletonActorProxy mix class """
    _instances = {}  # type: ignore
    _instance_creating = False

    def __call__(cls, *args, **kwargs):  # type: ignore
        if cls not in cls._instances:
            if cls._instance_creating:
                return super(SingletonActorProxy,
                             cls).__call__(*args, **kwargs)
            cls._locked_call(*args, **kwargs)
        return cls._instances[cls]['proxy']

    @synchronized(_g_singleton_actor_proxy_type_lock)  # type: ignore
    def _locked_call(cls, *args, **kwargs):  # type: ignore
        if cls not in cls._instances and not cls._instance_creating:
            cls._instance_creating = True
            instance = cls.start(*args, **kwargs)  # type: ignore
            cls._instance_creating = False
            cls._instances[cls] = {
                'instance': instance,
                'proxy': instance.proxy(),
            }


def global_call_only_once(func):
    """ Global call only once function decorator """
    instances: t.Dict[t.Callable, t.Any] = {}
    instances_lock = threading.Lock()

    @wraps(func)
    def wrapper(*args, **kwargs):
        if func not in instances:
            with instances_lock:
                if func not in instances:
                    instances[func] = func(*args, **kwargs)
        return instances[func]

    return wrapper


def update_logging(log_file_path: str,
                   log_level: str = 'DEBUG',
                   expand_str: str = '') -> None:
    assert log_file_path
    LOG_LEVEL = {
        '': 10,
        'DEBUG': 10,
        'INFO': 20,
        'WARN': 30,
        'ERROR': 40,
        'FATAL': 50,
    }[log_level]

    if '/' or '\\' in log_file_path:
        if not os.path.exists(os.path.dirname(log_file_path)):
            os.makedirs(os.path.dirname(log_file_path))

    proc_name = os.environ['PROC_ID'] if os.environ.get(
        'PROC_ID') else APP_NAME
    default_format = ('%(asctime)s %(levelname)-7s %(name)-10s ' + proc_name +
                      ' %(filename)-20s %(lineno)-4s ')
    default_format += expand_str
    default_format += ' - %(message)s'

    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': default_format,
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': LOG_LEVEL,
                'formatter': 'default'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': log_file_path,
                'level': LOG_LEVEL,
                'formatter': 'default',
                'maxBytes': 100 * 1024 * 1024,
                'backupCount': 20,
            },
        },
        'loggers': {
            '': {
                'handlers': ['console', 'file'],
                'level': LOG_LEVEL,
            },
        },
    }

    logging.config.dictConfig(config)
    logging.getLogger('parso').setLevel(logging.ERROR)
    logging.getLogger('asyncio').setLevel(logging.ERROR)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)
    logging.getLogger('pika').setLevel(logging.WARNING)
    logging.getLogger('pykka').setLevel(logging.WARNING)
    logging.getLogger('redis').setLevel(logging.WARNING)
    logging.getLogger('redis_lock').setLevel(logging.WARNING)


@global_call_only_once
def make_logger() -> logging.Logger:
    """ Make global logger """
    log_file_path: str = f"/tmp/{PROJECT_NAME}/trace/{APP_NAME}.log"
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_level: str = os.environ.get('LOGGING_LEVEL', 'DEBUG')
    update_logging(log_file_path, log_level)
    return logging.getLogger(APP_NAME)


LOGGER: logging.Logger = make_logger()


class Promise:
    """
    Base class for the proxy class created in the closure of the lazy function.
    It's used to recognize promises in code.
    """
    pass


def lazy(func, *resultclasses):
    """
    Turn any callable into a lazy evaluated callable. result classes or types
    is required -- at least one is needed so that the automatic forcing of
    the lazy evaluation code is triggered. Results are not memoized; the
    function is evaluated on every access.
    """
    @total_ordering
    class __proxy__(Promise):
        """
        Encapsulate a function call and act as a proxy for methods that are
        called on the result of that function. The function is not evaluated
        until one of the methods on the result is called.
        """
        __prepared = False

        def __init__(self, args, kw):
            self.__args = args
            self.__kw = kw
            if not self.__prepared:
                self.__prepare_class__()
            self.__prepared = True

        def __reduce__(self):
            return (_lazy_proxy_unpickle,
                    (func, self.__args, self.__kw) + resultclasses)

        def __repr__(self):
            return repr(self.__cast())

        @classmethod
        def __prepare_class__(cls):
            for resultclass in resultclasses:
                for type_ in resultclass.mro():
                    for method_name in type_.__dict__:
                        # All __promise__ return the same wrapper method, they
                        # look up the correct implementation when called.
                        if hasattr(cls, method_name):
                            continue
                        meth = cls.__promise__(method_name)
                        setattr(cls, method_name, meth)
            cls._delegate_bytes = bytes in resultclasses
            cls._delegate_text = str in resultclasses
            assert not (cls._delegate_bytes and cls._delegate_text), (
                "Cannot call lazy() with both bytes and text return types.")
            if cls._delegate_text:
                cls.__str__ = cls.__text_cast
            elif cls._delegate_bytes:
                cls.__bytes__ = cls.__bytes_cast

        @classmethod
        def __promise__(cls, method_name):
            # Builds a wrapper around some magic method
            def __wrapper__(self, *args, **kw):
                # Automatically triggers the evaluation of a lazy value and
                # applies the given magic method of the result type.
                res = func(*self.__args, **self.__kw)
                return getattr(res, method_name)(*args, **kw)

            return __wrapper__

        def __text_cast(self):
            return func(*self.__args, **self.__kw)

        def __bytes_cast(self):
            return bytes(func(*self.__args, **self.__kw))

        def __bytes_cast_encoded(self):
            return func(*self.__args, **self.__kw).encode()

        def __cast(self):
            if self._delegate_bytes:
                return self.__bytes_cast()
            elif self._delegate_text:
                return self.__text_cast()
            else:
                return func(*self.__args, **self.__kw)

        def __str__(self):
            # object defines __str__(), so __prepare_class__() won't overload
            # a __str__() method from the proxied class.
            return str(self.__cast())

        def __eq__(self, other):
            if isinstance(other, Promise):
                other = other.__cast()
            return self.__cast() == other

        def __lt__(self, other):
            if isinstance(other, Promise):
                other = other.__cast()
            return self.__cast() < other

        def __hash__(self):
            return hash(self.__cast())

        def __mod__(self, rhs):
            if self._delegate_text:
                return str(self) % rhs
            return self.__cast() % rhs

        def __deepcopy__(self, memo):
            # Instances of this class are effectively immutable. It's just a
            # collection of functions. So we don't need to do anything
            # complicated for copying.
            memo[id(self)] = self
            return self

    @wraps(func)
    def __wrapper__(*args, **kw):
        # Creates the proxy object, instead of the actual value.
        return __proxy__(args, kw)

    return __wrapper__


def _lazy_proxy_unpickle(func, args, kwargs, *resultclasses):
    return lazy(func, *resultclasses)(*args, **kwargs)


def lru_cache_time(seconds, maxsize=None):
    """
    Adds time aware caching to lru_cache
    """
    def wrapper(func):
        # Lazy function that makes sure the lru_cache() invalidate after X secs
        ttl_hash = lazy(lambda: round(time.time() / seconds), int)()

        @lru_cache(maxsize)
        def time_aware(__ttl, *args, **kwargs):
            """
            Main wrapper, note that the first argument ttl is not passed down.
            This is because no function should bother to know this that
            this is here.
            """
            def wrapping(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapping(*args, **kwargs)

        return update_wrapper(partial(time_aware, ttl_hash), func)

    return wrapper


def get_host_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    finally:
        s.close()

    return ip


def start_process(index: int) -> subprocess.Popen:
    """ Start a subprocess by nameko """
    cmd = [
        'nameko', 'run', '--config',
        f'/app/{PROJECT_NAME}_{APP_NAME}_service.yml', "service"
    ]
    LOGGER.info(f"{PROJECT_NAME}_{APP_NAME} [{index}] start")

    env = os.environ.copy()
    env['PROC_INDEX'] = "%03d" % index
    env['PROC_ID'] = f"{APP_NAME}_{env['PROC_INDEX']}"
    proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr, env=env)
    return proc


def monitor_process(num: t.Optional[int] = None) -> None:
    """ Monitor subprocess daemon """
    if num is None:
        num = psutil.cpu_count(logical=False)

    procs: t.Dict[int, subprocess.Popen] = {}
    for index in range(1, num + 1):
        proc = start_process(index)
        procs[index] = proc

    while True:
        time.sleep(1)
        need_delete_procs = set()
        for index in procs:
            proc = procs[index]
            if proc.poll() is not None:
                need_delete_procs.add(index)
        for index in need_delete_procs:
            procs[index] = start_process(index)


RPC_SERVICE_BASE_PORT = 8500


@global_call_only_once
def start_rpc_agent(cls: object) -> None:
    """ Start Pyro4 daemon server """
    ar = ({cls: os.environ["PROC_ID"]}, )
    kw = {
        'host': get_host_ip(),
        'port': RPC_SERVICE_BASE_PORT + int(os.environ['PROC_INDEX']),
        'ns': False
    }
    threading.Thread(target=Pyro4.Daemon.serveSimple,
                     args=ar,
                     kwargs=kw,
                     daemon=True).start()


_g_consul: consul.Consul = None


def create_g_consult():
    global _g_consul
    assert _g_consul is None
    _g_consul = consul.Consul(host=os.environ['CONSUL_HOST'])


@global_call_only_once
def start_consul_agent(service_name: str = os.environ['APP_NAME'],
                       address: str = get_host_ip(),
                       timeout: int = 10) -> None:
    """ Start consul agent server """
    create_g_consult()
    service_id = f"{service_name}:{os.environ['PROC_INDEX']}"
    port = RPC_SERVICE_BASE_PORT + int(os.environ['PROC_INDEX'])

    while True:
        try:
            _g_consul.agent.service.register(
                service_name,
                service_id=service_id,
                address=get_host_ip(),
                port=port,
                check=consul.Check.ttl(f'{timeout}s'))
            break
        except (ConnectionError, consul.ConsulException):
            LOGGER.warning('consul host is down, reconnecting...')
            time.sleep(0.5)

    def keep_ttl_pass():
        while True:
            try:
                _g_consul.agent.check.ttl_pass(f"service:{service_id}")
                time.sleep(1)
            except (ConnectionError, consul.ConsulException):
                LOGGER.warning('consul error, exit client')
                os.kill(os.getpid(), signal.SIGQUIT)

    threading.Thread(target=keep_ttl_pass, daemon=True).start()


def get_health_service_ids(service_name: str) -> t.List[str]:
    """ get health service ids from consul """
    index, nodes = _g_consul.health.service(service_name, passing=True)
    ids = []
    for node in nodes:
        ids.append(node["Service"]["ID"].split(':')[1])

    return ids


@global_call_only_once
def get_nameko_config():
    setup_yaml_parser()
    config_path: str = f'/app/{PROJECT_NAME}_{APP_NAME}_service.yml'
    assert os.path.exists(config_path)
    with open(config_path) as f:
        return yaml.unsafe_load(f)


def make_service_proxy() -> ClusterRpcProxy:
    """ Make a new nameko ClusterRpcProxy
    with make_service_proxy() as service_proxy:
        service_proxy.service_x.remote_method("hell")
        hello_res = service_proxy.service_x.remote_method.call_async("hello")
        world_res = service_proxy.service_x.remote_method.call_async("world")
        # do work while waiting
        hello_res.result()  # "hello-x-y"
        world_res.result()  # "world-x-y"
    """
    return ClusterRpcProxy(get_nameko_config())


_g_rpc_proxys: t.Dict[str, Pyro4.Proxy] = {}
_g_rpc_proxys_lock = threading.Lock()


@lru_cache_time(seconds=1)
def get_health_service_rpc_proxy(service_name: str,
                                 id_: t.Optional[str] = None) -> Pyro4.Proxy:
    """Gets health service from consul and make a rpc_rpoxy.

    Args:
        service_name: Which RPC service.
        id_: A service id, if it is provided, return the handle of this service.
    Return:
        A Pyro4 proxy.
    Raises:
        LookupError:
            It is thrown when cannot find a valid service.
    """
    _, nodes = _g_consul.health.service(service_name, passing=True)
    if not nodes:
        raise LookupError("Cannot get any health nodes.")

    if id_ is None:
        node = random.choice(nodes)
    else:
        for node in nodes:
            if id_ == node["Service"]["ID"].split(':')[1]:
                break
        else:
            raise LookupError(f"Cannot find the service by id {id_}.")

    ipv4 = node["Service"]["TaggedAddresses"]["lan_ipv4"]
    uri = (f'PYRO:{service_name}_{node["Service"]["ID"].split(":")[1]}'
           f'@{ipv4["Address"]}:{ipv4["Port"]}')

    if uri not in _g_rpc_proxys:
        with _g_rpc_proxys_lock:
            if uri not in _g_rpc_proxys:
                _g_rpc_proxys[uri] = Pyro4.Proxy(uri)

    return _g_rpc_proxys[uri]


_g_redis_client: t.Optional[redis.Redis] = None


@global_call_only_once
def get_redis_client() -> redis.Redis:
    """ Get the global redis client """
    global _g_redis_client
    _g_redis_client = redis.Redis.from_url(os.environ['REDIS_URI'],
                                           decode_responses=True)
    setattr(_g_redis_client, 'Lock', partial(redis_lock.Lock, _g_redis_client))
    return _g_redis_client


class ServiceBase(object):
    """ Service base class using nameko and Pyro4 """
    name = ""

    @timer(interval=3600, eager=True)
    def start_agent(self):
        if self.__class__ is ServiceBase:
            return
        start_rpc_agent(self)
        start_consul_agent()
