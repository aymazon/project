# 环境搭建

## 安装 docker 基础工具
无特殊要求, 安装 docker 和 docker-compose 即可, 参考网上教程
```bash
sudo apt-get install -y nvidia-container-runtime
# 在 /etc/docker/daemon.json 中增加运行时配置
#  "runtimes": {
#      "nvidia": {
#          "path": "/usr/bin/nvidia-container-runtime",
#          "runtimeArgs": []
#      }
#  },
#  "default-runtime": "nvidia"
```

## 全局替换 project 为工程名称

1. `_common/Dockerfile`

## 基础镜像本地构建
```bash
# 当然也可以直接使用 baseimage 基础镜像
git clone https://github.com/phusion/baseimage-docker.git  # 注意 baseimage-docker 主仓版本号和项目 Dockerfile 的版本对应
cd baseimage-docker
vim image/prepare.sh
# 在 apt update 前添加镜像加速源
sed -i 's/http:\/\/archive\.ubuntu\.com\/ubuntu\//http:\/\/mirrors\.163\.com\/ubuntu\//g' /etc/apt/sources.list
sed -i 's/http:\/\/security\.ubuntu\.com\/ubuntu\//http:\/\/mirrors\.163\.com\/ubuntu\//g' /etc/apt/sources.list
# 将 Makefile 文件中的 build 指令的 --platform 参数去掉
make build BASE_IMAGE=nvidia/cuda:10.0-cudnn7-devel-ubuntu18.04 NAME=phusion/baseimage-cuda-10.0-cudnn7-devel-ubuntu18.04 QEMU_ARCH=amd64
cd -
mkdir tmp
wget -q https://bitbucket.org/pypy/pypy/downloads/pypy3.6-v7.3.0-linux64.tar.bz2 -O tmp/pypy3.tar.bz2
docker build --no-cache -t project/baseimage:0.1 .
```

## 在容器中进行探索
```bash
docker run --rm -it --cap-add=SYS_PTRACE --name test-project-baseimage project/baseimage:0.1 /sbin/my_init --skip-startup-files --skip-runit --quiet -- bash -l
```

## 运行管理

### 启动前准备
```bash
cp env .env
```

### 启动
```bash
docker-compose up -d --build
```

### 停止
```bash
docker-compose down
```

### 开发相关
```bash
docker-compose up --build; docker-compose down
docker-compose exec xxx bash -c "source /venv-py3/bin/activate; bash"
```
