import datetime
import httpx
import logging
from abc import ABC
from pathlib import Path
from typing import Tuple

from cba.dispatcher import CommandsDispatcher
from cba.commands import arguments
from cba.commands import HumanCallableCommandWithArgs, BaseCommand, ServiceCommand
from cba.commands.commands_tools import load_json_template
from cba.exceptions import BadCommandTemplateException

from . import exceptions
from .zabbix_client.zabbix_web_interface_client import ZabbixWebInterfaceClient
from .zabbix_client.zabbix_api_client import ZabbixApiClient


PATH_TO_TEMPLATES = Path(__file__).parent.absolute()\
    .joinpath("zabbix_client")\
    .joinpath("__init__.py")

_LOGGER = logging.getLogger(__name__)

dispatcher = CommandsDispatcher()


def load_template(filename: str) -> dict:
    return load_json_template(filename, PATH_TO_TEMPLATES)


class ZabbixServiceCommand(ServiceCommand, ABC):
    zabbix_client = ZabbixApiClient()


class ZabbixCallableCommand(BaseCommand, ABC):
    zabbix_client = ZabbixApiClient()
    PATH_TO_FILE = PATH_TO_TEMPLATES

    async def execute(self):
        """ Override method to handle custom zactuator exceptions """
        try:
            await super().execute()
        except exceptions.AuthorisedException:
            _LOGGER.critical("Auth on Zabbix failed!", exc_info=True)
            await self.create_subcommand(AuthFailedCommand).execute()
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            _LOGGER.error(err, exc_info=True)
            await self.create_subcommand(NoConnectToZabbixCommand).execute()


class ZabbixCallableCommandWithArgs(ZabbixCallableCommand, HumanCallableCommandWithArgs, ABC):

    @ZabbixApiClient.authorised_required
    async def get_data_from_zabbix_api(self, template: dict) -> dict:
        """ Request to Zabbix-API"""
        template['auth'] = self.zabbix_client.auth
        request = await self.zabbix_client.post_to_zabbix_api(json=template)
        return request

    @staticmethod
    def format_items_info(raw_items_info: dict) -> str:
        """ Форматирует json-ответ метода item.get Zabbix-API """
        items_info_string = ""
        try:
            for item in raw_items_info["result"]:
                value = item['lastvalue']
                hosts = [host["host"] for host in item["hosts"]]
                item_info_string = f">>lupa<< <b>{', '.join(hosts)}::{item['name']}</b> = " \
                                   f"{value if value else '<i>No data</i>'}\n"
                items_info_string += item_info_string
        except (IndexError, KeyError):
            emergency_response = f">>Average<< Request parsing error! Raw data:\n{raw_items_info}"
            _LOGGER.warning(emergency_response)
            return emergency_response
        return items_info_string

    @staticmethod
    def _from_ts(ts):
        return str(datetime.datetime.fromtimestamp(int(ts)))

    def format_triggers_info(self, raw_triggers_info: dict) -> str:
        """ Форматирует json-ответ метода trigger.get Zabbix-API """
        problem_triggers_message = ""

        try:
            for trigger_info in raw_triggers_info['result']:
                # tg_id = trigger_info['triggerid']
                last_change = self._from_ts(trigger_info['lastchange'])
                priority = trigger_info["priority"]
                description = trigger_info["description"]
                hosts = ', '.join(host_info["host"] for host_info in trigger_info["hosts"])

                # tg_id = f"trigger_id: {tg_id}"
                last_change = f">>clock<< {last_change}"

                trigger_info_message = \
                    f"\n\n{last_change}\n>>{priority}<<<b>{hosts}</b>:: {description}"
                problem_triggers_message += trigger_info_message
        except KeyError:
            emergency_response = f"Request parsing error! Raw data:\n{raw_triggers_info}"
            _LOGGER.warning(emergency_response)
            return emergency_response

        if not problem_triggers_message:
            problem_triggers_message = f">>OK<< <i> NO TURNED TRIGGERS </i>\n"

        return problem_triggers_message


class WebInterfaceCommandMixin:
    """
    Подкласс-примесь для определения команд, которые работают не с Zabbix-API,
    а с веб-интерфейсом
    """

    zabbix_web_client = ZabbixWebInterfaceClient()
    item_graph_url = zabbix_web_client.host / 'chart.php'
    graph_url = zabbix_web_client.host / 'chart2.php'

    async def load_graph(self, image_query_params, source) -> str:
        """ Загружает картинку с Zabbix. На этом этапе данные провалидированы """
        if source == 'item':
            url = self.item_graph_url
            source_id = image_query_params['itemids']
        else:
            url = self.graph_url
            source_id = image_query_params['graphid']

        graph = await self.zabbix_web_client.zabbix_api_load_image(
            url, image_query_params, source_id
        )
        return graph

    def prepare_query_params(self, item_id=None, graph_id=None, period=1) -> dict:
        if item_id and graph_id:
            raise AttributeError("Choose only item_id or graph_id!")

        width, height = self._get_resolution(period)
        graph_query_params = {

            'type': 0,
            'from': 'now-{}h'.format(period),
            'to': 'now',
            'profileIdx': 'web.graphs.filter',
            'profileIdx2': item_id if item_id else graph_id,
            'width': width,
            'height': height,
        }
        if item_id:
            graph_query_params['itemids'] = item_id
        elif graph_id:
            graph_query_params['graphid'] = graph_id
        else:
            raise AttributeError("Choose item_id or graph_id!")

        return graph_query_params

    @staticmethod
    def _get_resolution(hours) -> Tuple[int, int]:
        base_width = 400
        base_height = 200
        max_width = 1000
        max_height = 350

        width = base_width + (200 * int(hours))
        height = base_height + (50 * int(hours))

        return min(width, max_width), min(height, max_height)


@dispatcher.register_callable_command
class GetHostInfo(ZabbixCallableCommandWithArgs, WebInterfaceCommandMixin):
    """ Get info about Host """
    CMD = "hostinfo"
    JSON_TMPL_FILE = 'host_info.json'
    HOSTS = {
        key.capitalize(): value for key, value
        in load_json_template(JSON_TMPL_FILE, ZabbixCallableCommand.PATH_TO_FILE).items()
    }
    ARGS = (
        arguments.String("host_name", "Zabbix host name", example="Line1", options=list(HOSTS.keys())),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Отображать названия линий на кнопках надо с большой буквы,
        # но работать команда должна при любом регистре атрибутов
        self.host_name = self.host_name.strip().lower()
        self.template = {key.strip().lower(): value for key, value in self.template.items()}

    async def _execute(self):
        template = self.template[self.host_name]
        host = template["host"]
        message_subject = f"Host info for {host}"
        message_body = ""
        main_image = None

        # Есть сработавшие триггеры? Если да - добавляем кнопки
        triggers_template = load_template('get_all_problem_triggers.json')
        triggers_template["params"]["host"] = host
        triggers = await self.get_data_from_zabbix_api(triggers_template)
        triggers = triggers['result']

        info_triggers = list(filter(lambda x: int(x['priority']) <= 2, triggers))
        problem_triggers = list(filter(lambda x: int(x['priority']) > 2, triggers))

        if problem_triggers:
            message_body += \
                f">>fire<< <i>Problem-triggers: <b>{len(problem_triggers)}</b></i>\n"
            self.add_inline_button(GetProblemTriggers, ">>fire<< Bad Triggers", "ge", "3",
                                   self.host_name)
        else:
            message_body += \
                f">>OK<< <i>No problems on line</i>\n"

        message_body += \
            f">>info<< <i>Info-triggers: <b>{len(info_triggers)}</b></i>\n"
        if info_triggers:
            self.add_inline_button(GetProblemTriggers, ">>info<< Info Triggers", "le", "2",
                                   self.host_name)

        # Zabbix items? Если да - добавляем их в текст
        if template["items"]:
            items_template = load_json_template('get_items.json',
                                                ZabbixCallableCommand.PATH_TO_FILE)
            items_template["params"]["itemids"] = template["items"]
            items = await self.get_data_from_zabbix_api(items_template)
            items = self.format_items_info(items)

            message_body += "\n<b>Items overview:</b>\n"
            message_body += items

        # Изображение в сообщении?
        if template["main_image"]:
            image_type = template["main_image"]["source"]
            element_id = template["main_image"]["id"]
            if image_type == "graph":
                graph_params = self.prepare_query_params(graph_id=element_id)
                main_image = await self.load_graph(graph_params, image_type)
            elif image_type == "item":
                graph_params = self.prepare_query_params(item_id=element_id)
                main_image = await self.load_graph(graph_params, image_type)
            else:
                _LOGGER.warning("Wrong image type!")
                # Типы графиков указываются в шаблоне команды
                raise BadCommandTemplateException(self.TMPL_FILE)

            message_body += "\n<b>Graph:</b>\n"
            message_body += f">>lupa<< 2h:: {self.reverse_command(GetGraph, image_type, element_id, '2')}\n"
            message_body += f">>lupa<< 4h:: {self.reverse_command(GetGraph, image_type, element_id, '4')}\n"

        message_body += f"\n>>repeat<< {self.reverse_command(GetHostInfo, self.host_name)}"

        # Добавляем кнопки для всех графиков
        for graph_name, graph_id in template["graphs"].items():
            self.add_inline_button(GetGraph, f">>graph1<< {graph_name}", "graph", graph_id)
        for item_name, item_id in template["item_graphs"].items():
            self.add_inline_button(GetGraph, f">>graph2<< {item_name}", "item", item_id)

        await self.send_message(
            subject=message_subject,
            text=message_body,
            images=[main_image, ],
            reply_markup=self.inline_buttons
        )

    def _validate(self) -> list:
        wrong_commands = list()
        if self.host_name.capitalize() not in self.HOSTS:
            wrong_commands.append(self.host_name)
        return wrong_commands


@dispatcher.register_callable_command
class GetItemHistory(ZabbixCallableCommandWithArgs):
    """
    Get the history of item values.
    """
    CMD = 'history'
    JSON_TMPL_FILE = 'get_item_history.json'

    ARGS = (
        arguments.Integer("item_id", "Item ID", example="integer"),
        arguments.Integer("period", "The period of history to the present",
                          example="integer", default=1, maximum=100),
        arguments.Integer("limit", "Limit on the number of records returned",
                          example="integer", default=100)
    )

    async def _execute(self):
        ts = int(datetime.datetime.timestamp(datetime.datetime.now()))
        time_from_hours = int(self.period)
        time_from_ts = ts - 3600 * time_from_hours

        self.template['params']['itemids'] = self.item_id
        self.template['params']['time_from'] = time_from_ts
        self.template['params']['limit'] = self.limit  # TODO: АГРЕГАЦИЯ ИСТОРИИ ПО ДАТАМ ИЗМЕНЕНИЯ

        history_request: dict = await self.get_data_from_zabbix_api(self.template)
        history: list = history_request['result']

        subject = f"History of item {self.item_id}. " \
                  f"Period: last {time_from_hours} hour(s) ({len(history)} records)"

        await self.send_message(
            subject=subject,
            replies=self.history_generator(history)
        )

    def history_generator(self, history: list) -> str:
        """ Превращает список в строку порционно """
        queries_in_one_message = 50
        h_len = len(history)
        start = 0
        end = queries_in_one_message
        history_parts_count = h_len // queries_in_one_message + bool(h_len % queries_in_one_message)
        for _ in range(history_parts_count):
            history_message = '\n'.join(
                f'Time: {self._from_ts(moment["clock"])} Value: {moment["value"]}'
                for moment in history[start: end]
            )
            yield history_message
            start += queries_in_one_message
            end += queries_in_one_message


@dispatcher.register_callable_command
class GetGraph(ZabbixCallableCommandWithArgs, WebInterfaceCommandMixin):
    """
    Get a graph of the values of an item.
    """
    CMD = 'graph'

    ARGS = (
        arguments.String("source", "Data source",
                         example="item, graph", options=["item", "graph"], allow_options=True),
        arguments.Integer("item_id", "Item ID", example="Integer"),
        arguments.Integer("period", "Period of interest in hours",
                          example="integer", default=1, options=[1, 2, 4, 8, 12, 24],
                          maximum=100)
    )

    async def _execute(self):

        if self.source == "item":
            graphs_params = self.prepare_query_params(
                item_id=self.item_id, period=self.period
            )
            template = load_template('get_items.json')
            template["params"]["itemids"] = self.item_id
        else:
            # self.source уже провалидирован на нужные значения
            graphs_params = self.prepare_query_params(
                graph_id=self.item_id, period=self.period
            )
            template = load_template('get_graph.json')
            template["params"]["graphids"] = self.item_id

        # Узнаем название Item и Host
        element_info = await self.get_data_from_zabbix_api(template)
        try:
            element_name = element_info["result"][0]["name"]
            host_name = element_info["result"][0]["hosts"][0]["host"]
            subject = f"{host_name} - {element_name}\n"
            message_body = f">>repeat<< {self.reverse_command(self.__class__, self.source, self.item_id)}"
        except IndexError:
            subject = f">>WARNING<< No {self.source} for id {self.item_id}"
            message_body = ""

        graph = await self.load_graph(graphs_params, self.source)

        await self.send_message(
            subject=subject,
            text=message_body,
            images=[graph, ]
        )


@dispatcher.register_callable_command
class GetItems(ZabbixCallableCommandWithArgs):
    """ Get item value. """
    JSON_TMPL_FILE = 'get_items.json'
    CMD = 'getitems'

    ARGS = (
        arguments.ListArg("item_ids", "Item ID",
                          example="30414 30415 ..."),
    )

    async def _execute(self):
        self.template['params']['itemids'] = self.item_ids

        items_request = await self.get_data_from_zabbix_api(self.template)
        items_text = self.format_items_info(items_request)

        await self.send_message(
            subject="Items info",
            text=items_text
        )


@dispatcher.register_callable_command
class GetProblemTriggers(ZabbixCallableCommandWithArgs):
    """ Get information about triggers in a problem state """
    JSON_TMPL_FILE = 'get_all_problem_triggers.json'
    CMD = 'badtriggers'
    LINES = load_template('host_info.json')
    MAX_PRIORITY = 5
    ARGS = (
        arguments.String("direction", "Filter condition", default="ge",
                         options=['≤', '=', '≥'], allowed=['≤', '=', '≥', 'le', 'eq', 'ge']),
        arguments.Integer("priority", "Trigger Priority Lower Bound",
                          example="0 - 5", default="1",
                          options=[i for i in range(MAX_PRIORITY + 1)], allow_options=True),
        arguments.String("hostname", "Filtering triggers by hostname",
                         example="Line1, Line4, All..", default='All',
                         options=[line for line in LINES] + ['All'])
    )

    # Для кнопок нужны красивые символы,
    # но их невозможно передать в макросах команд
    directions_translator = {
        '≤': 'le',
        '=': 'eq',
        '≥': 'ge',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.zabbix_line_host = ""  # настоящее имя хоста в Zabbix для обращений по API
        self.hostname = self.hostname.strip().lower()  # Зарегистрированное в 'host_info.json' имя
        # (для красоты кнопочек)
        self.LINES = {key.strip().lower(): value for key, value in self.LINES.items()}

    def _set_hostname(self):
        if self.hostname != 'all':
            # Отображаемые имена хостов (с большой буквы) и действительные
            # подгружаем из 'host_info.json'
            self.zabbix_line_host = self.LINES[self.hostname]['host']
            # В шаблон запроса к Zabbix-API подставляем действительное
            # имя хоста в Zabbix
            self.template['params']['host'] = self.zabbix_line_host
        else:
            # если нужно получить информацию для всех хостов - не трогаем шаблон.
            # В шаблоне значение - null. Т.е. без фильтрации по хостам.
            self.zabbix_line_host = self.hostname

    def _set_direction(self) -> None:
        # TODO: unittest
        """
        Устанавливает служебное-строковое значение directions и
        то, которое показывается пользователю
        """
        try:
            self.direction_str = self.directions_translator[self.direction]
        except KeyError:
            directions_translator_back = {
                value: key for key, value in self.directions_translator.items()
            }
            # На этом моменте должна быть пройдена валидация,
            # и self.direction - либо ключ, либо значение из словаря directions_translator
            self.direction_str, self.direction = \
                self.direction, directions_translator_back[self.direction]

    def _set_priority(self) -> None:
        # TODO: unittest
        priority = int(self.priority)
        priority_switch = {
            'le': lambda: list(range(priority + 1)),
            'eq': lambda: [priority, ],
            'ge': lambda: list(range(priority, self.MAX_PRIORITY + 1)),
        }
        priorities = priority_switch[self.direction_str]()
        self.template['params']['filter']['priority'] = priorities

    def _set_subject(self, host) -> str:
        subject = f"Problem triggers for priority {self.direction} {self.priority}, " \
                  f"host: {host if host else 'All'}"
        return subject

    async def _execute(self):
        self._set_hostname()
        self._set_direction()
        self._set_priority()

        problem_triggers_request = await self.get_data_from_zabbix_api(self.template)

        subject = self._set_subject(self.zabbix_line_host)

        problem_triggers_message = self.format_triggers_info(problem_triggers_request)

        await self.send_message(
            subject=subject,
            text=problem_triggers_message
        )

    def _validate(self) -> list:
        wrong_arguments = list()
        if self.hostname.lower() == 'all':
            return wrong_arguments
        if self.hostname.lower() not in self.LINES:
            wrong_arguments.append(self.hostname)
        return wrong_arguments


@dispatcher.register_callable_command
class HotKeysCommand(ZabbixCallableCommand):
    """ Hot keys """
    CMD = 'hotkeys'
    JSON_TMPL_FILE = 'hot_keys.json'
    EMOJI = ">>High<<"

    async def _execute(self):
        for item_name, item_id in self.template["items"].items():
            self.add_inline_button(GetItems, f">>info<< {item_name}", item_id)
        for item_name, item_id in self.template["item_graphs"].items():
            self.add_inline_button(GetGraph, f">>graph2<< {item_name}", "item", item_id)
        for graph_name, graph_id in self.template["graphs"].items():
            self.add_inline_button(GetGraph, f">>graph1<< {graph_name}", "graph", graph_id)

        await self.send_message(
            subject=f"{self.EMOJI} Hot keys",
            text=f"Settings in {self.JSON_TMPL_FILE} file",
            reply_markup=self.inline_buttons
        )


class NoConnectToZabbixCommand(ZabbixServiceCommand):
    """ Вызывается автоматически при отсуствии соединения с Zabbix.\n """
    EMOJI = '>>DISASTER<<'
    CMD = 'ZabbixBadGateway'

    async def _execute(self):

        await self.send_message(
            subject=f"{self.EMOJI} No connection to Zabbix!",
            text="Try again!"
        )


class AuthFailedCommand(ZabbixServiceCommand):
    """ Вызывается автоматически при неудачной авторизации на Zabbix.\n """

    EMOJI = '>>PROBLEM<<'
    CMD = 'ZabbixAuthFailed'

    async def _execute(self):

        await self.send_message(
            subject=f"{self.EMOJI} auth on Zabbix failed!",
            text="Check auth data on HEN"
        )
