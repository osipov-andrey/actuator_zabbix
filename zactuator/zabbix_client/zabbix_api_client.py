import httpx
import json
import logging
from typing import Optional

from cba.commands.commands_tools import load_json_template

from .zabbix_main_client import ZabbixMainClient


class ZabbixApiClient(ZabbixMainClient):
    """
    Предназначен для работы с API заббикса
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth: Optional[str] = None
        self.log = logging.getLogger(__name__)

    @property
    def api_url(self) -> str:
        api_url = self.host / "api_jsonrpc.php"
        return api_url.human_repr()

    async def is_authorised(self) -> bool:
        """ Проверяет авторизацию с помощью Zabbix API """
        self.log.debug("Checking auth with sessionid: %s", self.auth)
        auth = await self._check_authentication()
        self.log.debug("Takes sessionid from Zabbix Api: %s", auth)
        auth_status = bool(self.auth) and (self.auth == auth)
        self.log.debug("Auth status: >> %s << ", auth_status)
        return auth_status

    async def zabbix_login(self):
        """ Авторизуется на Zabbix через API """
        auth = None
        json_message: dict = load_json_template('user_login.json', __file__)
        json_message["params"]["user"] = self.username
        json_message["params"]["password"] = self.password

        # Метод post_to_zabbix_api проверяет авторизацию и поддерживает ее, вызывая текущий метод.
        # Если не нужен StackOverflow - отключим проверку авторизации)
        login_response = await self.post_to_zabbix_api(error_handling=False, json=json_message)

        try:
            auth = login_response["result"]
        except KeyError:
            self.log.warning('LOGIN FAILED!')
        await self._set_auth(auth)

    async def handle_error_response_form_zabbix(self, error: dict):
        """ Определяет что делать с ошибками, если Zabbix API их вернет """
        error_codes_switch = {
            -32602: self.zabbix_login,  # "Session terminated, re-login, please."
            -32500: self._set_auth,  # "Login name or password is incorrect."
        }

        error_code = error["code"]
        await error_codes_switch[error_code]()

    async def post_to_zabbix_api(self, error_handling=True, **kwargs) -> dict:
        """ Собственно, отправка POST-запроса в Zabbix API """
        async with httpx.AsyncClient() as client:
            response = await client.post(self.api_url, **kwargs)
            response_body = json.loads(response.text)

            if "error" in response_body:
                error = response_body["error"]
                self.log.warning(error)
                if error_handling:
                    # авто-обработка сообщений об ошибке
                    await self.handle_error_response_form_zabbix(error)

        return response_body

    async def _set_auth(self, auth=None):
        """ Сбрасывает или устанавливает токен авторизации в клиенте """
        if self.auth != auth:
            self.auth = auth
            self.log.info("Auth was changed to: %s", bool(auth))

    async def _check_authentication(self) -> [str, None]:
        """
        Проверка аутентификации по sessionid.
        По умолчанию продлевает подтвержденную сессию.
        """
        json_message: dict = load_json_template('check_authentication.json', __file__)
        json_message["params"]["sessionid"] = str(self.auth)

        check_auth_request = await self.post_to_zabbix_api(error_handling=False, json=json_message)
        try:
            auth = check_auth_request['result']['sessionid']
        except KeyError:
            auth = None
        await self._set_auth(auth)
        return auth
