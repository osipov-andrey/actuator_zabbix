import base64
import httpx
import logging
import time

from ..config import config
from .zabbix_main_client import ZabbixMainClient, ZabbixIssueMessage


class ZabbixWebInterfaceClient(ZabbixMainClient):
    """
    Предназначен для работы с WEB-интерфейсом.
    В первую очередь для скачивания картинок и отправки их в патефон.
    """
    AUTH_COOKIE_NAME = 'zbx_sessionid'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cookies = dict()
        self.log = logging.getLogger(__name__)

    async def is_authorised(self):
        """ Проверяет авторизацию по cookies """
        auth = False
        # http://zabbix_host/zabbix/zabbix.php - пустая страница. Проверим авторизацию здесь.
        check_auth_host = self.host / 'zabbix.php'
        async with httpx.AsyncClient() as client:
            self.log.debug("Checking auth with cookies: %s", dict(self.cookies))
            check_request = await client.head(check_auth_host.human_repr(), cookies=self.cookies)
            self.log.debug("Check auth headers: %s", check_request.headers)
            check_cookies = check_request.cookies
        try:
            auth = self.cookies[self.AUTH_COOKIE_NAME] == check_cookies[self.AUTH_COOKIE_NAME]
        except KeyError:
            pass
        finally:
            self.log.debug("Auth status: >> %s << ", auth)
            return auth

    async def zabbix_login(self):
        """ Логинится на Zabbix по главной странице """
        login_data = {"name": self.username, "password": self.password, "enter": "Sign in"}
        auth = httpx.BasicAuth(self.username, self.password)
        async with httpx.AsyncClient() as client:
            login_request = await client.post(str(self.host) + "/", data=login_data, auth=auth)

            if login_request.status_code != 200:
                self.log.warning('Login on Zabbix Failed!')
                self.log.debug(login_request.text)

            cookies = login_request.cookies
            if self.AUTH_COOKIE_NAME in cookies.keys():
                self.log.info("LOGGING SUCCESS on Zabbix Web Interface")
            else:
                self.log.warning('Authentication on Zabbix Failed!')
                self.log.debug(login_request.text)

            self.cookies = cookies
            return login_request.text

    async def zabbix_logout(self):
        """ Разлогинивается на Zabbix """
        logout_url = self.host / 'index.php'
        logout_url = logout_url.with_query(
            {'reconnect': 1}
        )
        async with httpx.AsyncClient() as client:
            await client.post(logout_url.human_repr(), cookies=self.cookies)

    @ZabbixMainClient.authorised_required
    async def zabbix_api_load_image(self, image_url, query_params, image_id):
        """ Загружает изображение по URL """
        image_url = image_url.with_query(query_params)
        self.log.debug('Graph URL: %s', image_url)

        async with httpx.AsyncClient() as client:
            graph_request = await client.get(
                url=str(image_url),
                cookies=self.cookies,
            )

            image = graph_request.content

            if config.SAVED_IMAGES:
                self._write_file(self._get_graph_file_name(image_id), image)

            return base64.b64encode(image).decode()

    async def _get_graph(self, graph_id: str, zabbix_message: ZabbixIssueMessage) -> str:
        """
        Получает график по Zabbix API. Возвращает Base64-байт строку.
        При включенной опции SAVED_IMAGES в settings.py сохраняет график в PNG-файл.
        """
        graph_query_params = {
            'graphid': graph_id,
            'from': 'now-{}'.format(zabbix_message.graph_period),
            'to': 'now',
            'profileIdx': 'web.graphs.filter',
            'profileIdx2': graph_id,
            'width': zabbix_message.graph_width,
            'height': zabbix_message.graph_height
        }

        graph_url = self.host / 'chart2.php'
        graph = await self.zabbix_api_load_image(graph_url, graph_query_params, graph_id)
        return graph

    async def _get_item_graph(self, item_id: str, zabbix_message: ZabbixIssueMessage) -> str:
        """
        Получает график айтема по Zabbix API. Возвращает Base64-байт строку.
        При включенной опции SAVED_IMAGES в settings.py сохраняет график в PNG-файл.
        """
        item_graph_query_params = {
            'itemids': item_id,
            'type': 1,
            'from': 'now-{}'.format(zabbix_message.graph_period),
            'to': 'now',
            'profileIdx': 'web.item.graph.filter',
            'profileIdx2': item_id,
            'width': zabbix_message.graph_width,
            'height': zabbix_message.graph_height
        }
        item_graph_url = self.host / 'chart.php'
        item_graph = await self.zabbix_api_load_image(
            item_graph_url, item_graph_query_params, item_id
        )
        return item_graph

    def _get_graph_file_name(self, graph_id):
        """ Создает имя для записи графика в файл """
        time_ = time.strftime('%Y_%m_%d__%H_%M')
        graph_file_name = f"{self.storage_dir}_ID{graph_id}_{time_}.png"
        return graph_file_name

    @staticmethod
    def _write_file(filename, data):
        with open(filename, "wb") as fd:
            fd.write(data)
        return True
