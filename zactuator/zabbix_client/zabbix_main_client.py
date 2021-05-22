import re

from abc import abstractmethod
from collections import UserDict
from functools import wraps
from yarl import URL

from ..config import config
from ..exceptions import AuthorisedException


class ZabbixIssueMessage(UserDict):
    """
    Преобразует сообщение от Zabbix в словарь.
    Сообщения генерируются объектами 'media', 'action' в заббиксе.

    Пример сообщения:

    [message: Текст >>Not_classified<<] # обязательное поле
    [rabbit_queue: telegram]            # обязательное поле
    [telegram_channel: Numas]           # обязательное поле
    [zab_graphs: 1112, 1078]
    [zab_items: 30414]
    [graph_period: 30m]
    [graph_width: 600]
    [graph_height: 200]

    """
    def __init__(self, message: str):
        super().__init__()
        self._parse_message(message)

    def __getattr__(self, item):
        return self.setdefault(item, "")

    def _parse_message(self, text: str):
        """ Парсит параметры из сообщения с Zabbix """
        pattern = re.compile(r"\[([\S]+?): ([\S\s]+?)\]")
        parameters = re.findall(pattern, text)
        parameters = {match[0].lower(): match[1] for match in parameters}
        self.update(**parameters)


class ZabbixMainClient:
    """
    Базовый класс для клиентов Zabbix.
    Предоставляет интерфейс создания сообщений и отправки их в патефон.
    """
    # TODO логи в базовом классе тоже нужны

    def __init__(self,
                 host: str = config.ZABBIX_HOST,
                 username: str = config.ZABBIX_USER,
                 password: str = config.ZABBIX_PASSW,
                 storage_dir: str = config.PATH_TO_IMAGES
                 ):
        self.host = URL('http://' + host) / 'zabbix'
        self.username = username
        self.password = password
        self.storage_dir = storage_dir

    @staticmethod
    def authorised_required(method, auto_login=True):
        """
        Декоратор для методов-обращений к Zabbix.
        Если нет у клиента нет авторизации - принудительно авторизовывает
        """
        @wraps(method)
        async def wrapper(self, *args, **kwargs):
            try:
                zab = self.zabbix_client
            except AttributeError:
                zab = self
            if not await zab.is_authorised():
                if auto_login:
                    await zab.zabbix_login()
                    if not await zab.is_authorised():
                        raise AuthorisedException
                else:
                    raise AuthorisedException
            return await method(self, *args, **kwargs)
        return wrapper

    @abstractmethod
    async def is_authorised(self):
        ...

    @abstractmethod
    async def zabbix_login(self):
        ...

    @staticmethod
    def _add_prefix(issue_id: str, prefix: str = 'zbx-'):
        """ Добавляет префикс для issue_id """
        return prefix + issue_id

    @staticmethod
    def _is_resolved(zabbix_event_status: str):
        """ Проверяют статус issue. Issue - событие в Zabbix """
        return True if zabbix_event_status.upper() == 'RESOLVED' else False

