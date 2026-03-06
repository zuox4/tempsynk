# config.py
from typing import Dict, Any, Optional
import os
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()

# Настройки MongoDB
MONGO_SETTINGS = {
    'uri': os.getenv('MONGO_URI', 'mongodb://localhost:27017/'),
    'db_name': os.getenv('MONGO_DB_NAME', 'school'),
    'collection_name': os.getenv('MONGO_COLLECTION', 'users')
}

# Настройки API MOS.RU
MOS_API_SETTINGS = {
    'base_url': 'https://school.mos.ru/api/ej/core/teacher/v1',
    'max_url': 'https://school.mos.ru/v2/external-partners/check-for-max-user',
    'academic_year_id': int(os.getenv('ACADEMIC_YEAR_ID', '13')),
    'school_id': int(os.getenv('SCHOOL_ID', '28')),
    'timeout': int(os.getenv('REQUEST_TIMEOUT', '30')),
}

# Настройки API Sferum (замените на реальные endpoint-ы)
SFERUM_API_SETTINGS = {
    'base_url': os.getenv('SFERUM_API_URL', 'https://api.sferum.ru/v1'),
    'contacts_endpoint': os.getenv('SFERUM_CONTACTS_ENDPOINT', '/contacts'),
    'timeout': int(os.getenv('SFERUM_TIMEOUT', '10')),
}

# Заголовки по умолчанию для MOS.RU
DEFAULT_MOS_HEADERS = {
    "profile-id": os.getenv('PROFILE_ID', '16073051'),
    "x-mes-hostid": os.getenv('X_MES_HOSTID', '9'),
    "x-mes-subsystem": os.getenv('X_MES_SUBSYSTEM', 'teacherweb'),
    "aid": os.getenv('AID', '13')
}

# Настройки производительности
PERFORMANCE_SETTINGS = {
    'batch_size': int(os.getenv('BATCH_SIZE', '500')),
    'max_workers': int(os.getenv('MAX_WORKERS', '10')),
    'pagination_per_page': int(os.getenv('PAGINATION_PER_PAGE', '300')),
}

# Настройки логирования
LOG_SETTINGS = {
    'level': os.getenv('LOG_LEVEL', 'INFO'),
    'file': os.getenv('LOG_FILE', 'sync.log'),
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
}

# Токены (можно задать в .env или вводить интерактивно)
TOKENS = {
    'mos_ru': os.getenv('MOS_RU_TOKEN', ''),
    'sferum': os.getenv('SFERUM_TOKEN', '')
}


class Config:
    """Класс для доступа к настройкам"""

    @staticmethod
    def get_mongo_settings() -> Dict[str, str]:
        return MONGO_SETTINGS.copy()

    @staticmethod
    def get_mos_api_settings() -> Dict[str, Any]:
        return MOS_API_SETTINGS.copy()

    @staticmethod
    def get_sferum_api_settings() -> Dict[str, Any]:
        return SFERUM_API_SETTINGS.copy()

    @staticmethod
    def get_performance_settings() -> Dict[str, int]:
        return PERFORMANCE_SETTINGS.copy()

    @staticmethod
    def get_log_settings() -> Dict[str, Any]:
        return LOG_SETTINGS.copy()

    @staticmethod
    def get_default_mos_headers(bearer_token: str = None) -> Dict[str, str]:
        """Получение заголовков для MOS.RU с токеном"""
        headers = DEFAULT_MOS_HEADERS.copy()
        if bearer_token:
            headers['authorization'] = f'Bearer {bearer_token}'
        return headers

    @staticmethod
    def update_token(token_type: str, token_value: str):
        """Обновление токена в памяти"""
        TOKENS[token_type] = token_value

    @staticmethod
    def get_token(token_type: str) -> str:
        return TOKENS.get(token_type, '')