FROM phusion/baseimage:0.11

CMD ["/sbin/my_init"]

SHELL ["/bin/bash", "-c"]

ENV LANG C.UTF-8

RUN set -ex; \
    true \
    && sed -i 's/http:\/\/archive\.ubuntu\.com\/ubuntu\//http:\/\/mirrors\.163\.com\/ubuntu\//g' /etc/apt/sources.list \
    && sed -i 's/http:\/\/security\.ubuntu\.com\/ubuntu\//http:\/\/mirrors\.163\.com\/ubuntu\//g' /etc/apt/sources.list \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get update \
    && apt-get install -y -q --no-install-recommends \
        wget bzip2 tzdata rsync htop sysstat strace lsof net-tools gettext-base bash-completion netbase \
        gcc python3-dev zlib1g-dev virtualenv \
    && echo '$' > /etc/container_environment/ENV_DOLLAR \
    && rm -rf /etc/service/sshd \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

COPY requirements.txt /tmp

RUN set -ex; true \
    && mkdir -p ~/.pip && echo -e "[global]\nindex-url = https://mirrors.163.com/pypi/simple" > ~/.pip/pip.conf \
    && virtualenv -p python3 --no-setuptools --system-site-packages /venv-py3 \
    && echo -e "alias activate-py3='source /venv-py3/bin/activate'\n" >> /root/.bashrc \
    && source /venv-py3/bin/activate \
    && pip install -U pip setuptools \
    && pip install -r /tmp/requirements.txt \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache/pip/*

COPY tmp/pypy3.tar.bz2 /tmp/pypy3.tar.bz2
COPY requirements-pypy.txt /tmp

RUN set -ex; true \
    && tar xjf /tmp/pypy3.tar.bz2 -C /opt/ \
    && cd /opt/pypy*/bin/ && virtualenv -p ./pypy3 --no-setuptools /venv-pypy3 \
    && echo -e "alias activate-pypy3='source /venv-pypy3/bin/activate'\n" >> /root/.bashrc \
    && source /venv-pypy3/bin/activate \
    && pip install -U pip setuptools \
    && pip install -r /tmp/requirements-pypy.txt \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache/pip/*

ONBUILD WORKDIR /app
ONBUILD ARG APP_NAME
ONBUILD ENV APP_NAME=${APP_NAME}
ONBUILD ARG PROJECT_NAME
ONBUILD ENV PROJECT_NAME=${PROJECT_NAME}
ONBUILD COPY ${APP_NAME} /app
ONBUILD COPY _common/common.py /app
ONBUILD COPY _common/daemon.py /app
ONBUILD COPY _common/nameko.yml /app
ONBUILD RUN mv /app/nameko.yml /app/${PROJECT_NAME}_${APP_NAME}_service.yml
