from common import monitor_process

from service import count_daemon_process


def main() -> None:
    monitor_process(count_daemon_process())


if __name__ == '__main__':
    main()
