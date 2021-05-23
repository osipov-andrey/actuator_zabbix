from cba.consumers import SSEConsumer
from cba.publishers import RabbitPublisher
from cba.actuator import Actuator

from .config import config
from .commands import *


NAME = config.BOT_CLIENT_NAME

SSE_URL = config.SSE_URL.format(NAME)
publisher = RabbitPublisher(**config.RABBIT)


def main():
    dispatcher.introduce(NAME)
    dispatcher.set_publishers(publisher)
    sse = SSEConsumer(SSE_URL)

    zactuator = Actuator(
        name=NAME,
        verbose_name=config.VERBOSE_BOT_CLIENT_NAME,
        consumer=sse,
        dispatcher=dispatcher
    )
    zactuator.run()


if __name__ == '__main__':
    main()
