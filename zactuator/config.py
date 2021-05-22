import logging.config
import os
import yaml

from errno import EEXIST
from pathlib import Path


__all__ = ['config', 'Config']


class Config(dict):
    def __init__(self, file: str) -> None:
        super().__init__()
        file = Path(__file__).parent.absolute().joinpath(file)
        with open(file, 'r', encoding='utf-8') as f:
            self.update(**yaml.load(f, Loader=yaml.FullLoader))

        self.create_logging_dir()
        logging.config.dictConfig(self['logging'])

    def __getattr__(self, item):
        return self[item]

    def create_logging_dir(self):
        base_dir = Path(__file__).parent.absolute()
        path_to_log = base_dir.joinpath(self['logging']['handlers']['file']['filename'])

        try:
            # Создаю папку для логов, если ее нет
            os.mkdir(path_to_log.parent)
        except OSError as err:
            if err.errno != EEXIST:
                raise err
            pass
        # Записываем в словарь с конфигом получившийся абсолютный пусть до логов
        self['logging']['handlers']['file']['filename'] = path_to_log


config = Config("config.yaml")
