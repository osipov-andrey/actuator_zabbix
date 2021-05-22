from cba.consumers import SSEConsumer
from cba.publishers import RabbitPublisher, HTTPPublisher
from cba.actuator import Actuator

from .config import config
from .commands import *


NAME = config.BOT_CLIENT_NAME

if config.DEBUG:
    SSE_URL = config.SSE_URL_DEBUG.format(NAME)
    publisher = RabbitPublisher(**config.RABBIT)

else:
    SSE_URL = config.SSE_URL.format(NAME)
    publisher = HTTPPublisher(**config.PATEFON)


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
