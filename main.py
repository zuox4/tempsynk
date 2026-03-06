import requests
from pymongo import MongoClient, UpdateOne
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
import sys
import os
from sferum import SferumContacts

# Импорт конфигурации
from config import Config, PERFORMANCE_SETTINGS, LOG_SETTINGS, MONGO_SETTINGS, MOS_API_SETTINGS

# Настройка логирования из конфига
logging.basicConfig(
    level=getattr(logging, LOG_SETTINGS['level']),
    format=LOG_SETTINGS['format'],
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_SETTINGS['file'], encoding='utf-8')
    ]
)
logger = logging.getLogger('mos_sync')

# Константы из конфига
DEFAULT_MONGO_URI = MONGO_SETTINGS['uri']
DEFAULT_DB_NAME = MONGO_SETTINGS['db_name']
DEFAULT_COLLECTION_NAME = MONGO_SETTINGS['collection_name']
BATCH_SIZE = PERFORMANCE_SETTINGS['batch_size']
MAX_WORKERS = PERFORMANCE_SETTINGS['max_workers']
REQUEST_TIMEOUT = MOS_API_SETTINGS['timeout']


@dataclass
class SyncStatistics:
    """Статистика синхронизации"""
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    students: int = 0
    parents: int = 0
    teachers: int = 0
    total_processed: int = 0

    def display(self):
        """Отображение статистики"""
        print("\n" + "=" * 50)
        print("📊 РЕЗУЛЬТАТЫ СИНХРОНИЗАЦИИ")
        print("=" * 50)
        print(f"✅ Создано: {self.created}")
        print(f"🔄 Обновлено: {self.updated}")
        print(f"❌ Деактивировано: {self.deactivated}")
        print(f"📚 Всего обработано: {self.total_processed}")

        if self.students:
            print(f"👨‍🎓 Учеников: {self.students}")
        if self.parents:
            print(f"👪 Родителей: {self.parents}")
        if self.teachers:
            print(f"👨‍🏫 Учителей: {self.teachers}")
        print("=" * 50)


class DataNormalizer:
    """Нормализация данных"""

    @staticmethod
    def normalize_phone(phone: Any) -> Optional[str]:
        """Приведение телефона к стандартному формату"""
        if not phone:
            return None

        cleaned = ''.join(filter(str.isdigit, str(phone)))

        if len(cleaned) == 11 and cleaned.startswith('8'):
            return '7' + cleaned[1:]
        elif len(cleaned) == 11 and cleaned.startswith('7'):
            return cleaned
        elif len(cleaned) == 10:
            return '7' + cleaned

        return None

    @staticmethod
    def normalize_email(email: Any) -> Optional[str]:
        """Нормализация email"""
        if not email:
            return None

        email = str(email).strip().lower()
        return email if '@' in email else None


class MosApiClient:
    """Клиент для работы с API MOS.RU"""

    def __init__(self, bearer_token: str):
        self.base_url = MOS_API_SETTINGS['base_url']
        self.max_url = MOS_API_SETTINGS['max_url']
        self.headers = Config.get_default_mos_headers(bearer_token)
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.max_data = None  # Для кэширования данных Sferum

    def set_max_data(self, max_data: Dict[str, str]):
        """Установка данных из Sferum"""
        self.max_data = max_data
        if self.max_data:
            logger.info(f"Загружено {len(self.max_data)} контактов из Sferum")

    def fetch_data(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Базовый метод для запросов к API"""
        url = f"{self.base_url}/{endpoint}"

        try:
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Таймаут при запросе {url}")
        except requests.exceptions.ConnectionError:
            logger.error(f"Ошибка соединения с {url}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP ошибка {e.response.status_code}: {url}")
        except Exception as e:
            logger.error(f"Неизвестная ошибка {url}: {e}")

        return None

    def fetch_with_pagination(self, endpoint: str, base_params: Dict, items_per_page: int = 300) -> List:
        """Запрос с пагинацией"""
        all_items = []
        current_page = 1

        while True:
            params = {**base_params, "page": current_page, "per_page": items_per_page}
            data = self.fetch_data(endpoint, params)

            if not data or not isinstance(data, list):
                break

            all_items.extend(data)

            if len(data) < items_per_page:
                break

            current_page += 1

        return all_items

    def get_class_list(self) -> List[str]:
        """Получение списка классов"""
        data = self.fetch_data('class_units', {'with_home_based': 'true'})

        if not data:
            logger.warning("Не удалось получить список классов")
            return []

        class_ids = [str(class_info['id']) for class_info in data if class_info.get('id')]
        logger.info(f"Получено классов: {len(class_ids)}")
        return class_ids

    def get_students_by_class(self, class_id: str) -> Optional[List]:
        """Получение учеников по классу"""
        params = {
            "class_unit_ids": class_id,
            "with_deleted": "false",
            "with_parents": "true",
            "with_user_info": "true"
        }

        return self.fetch_data('student_profiles', params)

    def get_teachers(self) -> List:
        """Получение всех учителей"""
        params = {
            "academic_year_id": MOS_API_SETTINGS['academic_year_id'],
            "school_id": MOS_API_SETTINGS['school_id']
        }
        return self.fetch_with_pagination('teacher_profiles', params)

    def get_max_data(self, staff_data=None, person_data=None):
        """
        ОРИГИНАЛЬНАЯ ФУНКЦИЯ: Получает MAX ID и ссылку для пользователя
        """
        staff_id = staff_data.get('user_integration_id') if staff_data else None
        person_id = person_data.get('person_id') if person_data else None

        if staff_id:
            url = f"https://school.mos.ru/v2/external-partners/check-for-max-user?staff_id={staff_id}"
            logger.debug(f"Запрос MAX данных для staff_id: {staff_id}")
        elif person_id:
            url = f"https://school.mos.ru/v2/external-partners/check-for-max-user?person_id={person_id}"
            logger.debug(f"Запрос MAX данных для person_id: {person_id}")
        else:
            return None

        try:
            response = requests.get(url, headers=self.headers, timeout=10)

            if response.status_code != 200:
                logger.debug(f"MAX API вернул код {response.status_code}")
                return None

            data = response.json()
            if not data or 'max_link' not in data:
                logger.debug(f"MAX API не вернул max_link: {data}")
                return None

            max_link = data['max_link']
            max_user_id = None

            # Получаем ID из Sferum данных
            if self.max_data and max_link:
                max_user_id = self.max_data.get(max_link)
                logger.debug(f"Для ссылки {max_link} найден ID: {max_user_id}")

            return {
                'max_id': max_user_id,
                'max_link': max_link
            }
        except requests.exceptions.RequestException as e:
            logger.debug(f"Ошибка получения MAX данных: {e}")
            return None

    def close(self):
        """Закрытие сессии"""
        self.session.close()


class SferumClient:
    """Клиент для работы с Sferum"""

    def __init__(self, bearer_token: str):
        self.bearer_token = bearer_token
        self.contacts_cache = None


    def get_contacts(self) -> Dict[str, str]:
        """Получение контактов из Sferum"""
        if self.contacts_cache is not None:
            return self.contacts_cache

        logger.info("Получение контактов из Sferum...")

        try:
            # Импортируем ваш модуль sferum
            from sferum import SferumContacts

            # Создаем экземпляр и получаем контакты
            sferum = SferumContacts(self.bearer_token)
            contacts = sferum.get_contacts()

            # Преобразуем в нужный формат {ссылка: id}
            self.contacts_cache = {}
            if contacts:
                for link, user_id in contacts.items():
                    self.contacts_cache[link] = user_id
                logger.info(f"Получено {len(self.contacts_cache)} контактов из Sferum")
            else:
                logger.warning("Sferum вернул пустой список контактов")
                self.contacts_cache = {}

        except ImportError:
            logger.error("Модуль sferum не найден. Убедитесь, что файл sferum.py существует")
            self.contacts_cache = {}
        except Exception as e:
            logger.error(f"Ошибка при получении контактов из Sferum: {e}")
            self.contacts_cache = {}

        return self.contacts_cache

from school_client import SchoolLocalClient
class UserDataProcessor:
    """Обработка данных пользователей"""

    def __init__(self, normalizer: DataNormalizer, mos_client: Optional[MosApiClient] = None):
        self.normalizer = normalizer
        self.mos_client = mos_client
        self._parents_cache: Set[str] = set()
        self.school_data = SchoolLocalClient().get_teachers()
    def process_student_data(self, student: Dict, include_max: bool = False) -> List[Dict]:
        """Обработка данных ученика и его родителей"""
        users = []

        if not student or not student.get('person_id'):
            return users

        # Обработка ученика
        student_info = self._create_user_base(student, 'student')
        student_info.update({
            'class_unit_name': student.get('class_unit', {}).get('name', ''),
            'parents_ids': []
        })

        # Обработка родителей
        parents = student.get('parents', [])
        parent_ids = []

        for parent in parents:
            parent_id = parent.get('person_id')
            if not parent_id:
                continue

            parent_ids.append(parent_id)

            if parent_id not in self._parents_cache:
                self._parents_cache.add(parent_id)
                parent_info = self._create_user_base(parent, 'parent')

                if include_max:
                    self._enrich_with_max_data(parent_info, parent)

                users.append(self._clean_tuple_values(parent_info))

        student_info['parents_ids'] = parent_ids

        if include_max:
            self._enrich_with_max_data(student_info, student)

        users.append(self._clean_tuple_values(student_info))

        return users
    def find_teacher_by_name(self, name: str) -> str:
        return self.school_data[name] if self.school_data.get(name) else None
    def process_teacher_data(self, teacher: Dict, include_max: bool = False) -> Optional[Dict]:
        """Обработка данных учителя"""
        if not teacher.get('user'):
            return None

        teacher_info = self._create_user_base(teacher, 'teacher')
        teacher_info.update({
            'managed_class_units': teacher.get('managed_class_units')
        })
        teacher_info.update({
            'email':self.find_teacher_by_name(teacher_info['full_name']),
        })
        if include_max:
            self._enrich_with_max_data(teacher_info, teacher, is_teacher=True)

        return self._clean_tuple_values(teacher_info)

    def _create_user_base(self, source: Dict, user_type: str) -> Dict:
        """Создание базовой структуры пользователя"""
        user_data = source.get('user', {}) if 'user' in source else source

        if user_type == 'teacher':
            external_id = str(source['id'])
            full_name = source.get('name', f'Учитель_{external_id}')
            email = user_data.get('email') or user_data.get('email_ezd')
            phone = user_data.get('phone_number')
        elif user_type == 'student':
            external_id = source['person_id']
            full_name = source.get('user_name', '')
            email = source.get('email')
            phone = source.get('phone_number')
        else:  # parent
            external_id = source['person_id']
            full_name = source.get('name', '')
            email = source.get('email')
            phone = source.get('phone_number')

        return {
            'external_id': external_id,
            'full_name': full_name,
            'email': self.normalizer.normalize_email(email),
            'phone_number': self.normalizer.normalize_phone(phone),
            'type': user_type
        }

    def _enrich_with_max_data(self, user_info: Dict, source: Dict, is_teacher: bool = False):
        """Обогащение данными MAX - используем оригинальную функцию"""
        if not self.mos_client:
            return

        if is_teacher:
            max_info = self.mos_client.get_max_data(staff_data=source)
        else:
            max_info = self.mos_client.get_max_data(person_data=source)

        if max_info:
            user_info['max_link'] = max_info.get('max_link')
            user_info['max_id'] = max_info.get('max_id')
            if user_info.get('max_link'):
                logger.debug(f"Установлены MAX данные: link={user_info['max_link']}, id={user_info['max_id']}")
        else:
            user_info['max_link'] = None
            user_info['max_id'] = None

    def _clean_tuple_values(self, data: Dict) -> Dict:
        """Очистка значений от кортежей"""
        cleaned = {}
        for key, value in data.items():
            if isinstance(value, tuple):
                cleaned[key] = value[0] if value else None
            else:
                cleaned[key] = value
        return cleaned

    def reset_cache(self):
        """Сброс кэша родителей"""
        self._parents_cache = set()


class DatabaseManager:
    """Управление базой данных MongoDB"""

    def __init__(self, uri: str = DEFAULT_MONGO_URI, db_name: str = DEFAULT_DB_NAME,
                 collection_name: str = DEFAULT_COLLECTION_NAME):
        self.uri = uri
        self.db_name = db_name
        self.collection_name = collection_name
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        self._create_indexes()

    def _create_indexes(self):
        """Создание индексов"""
        try:
            self.collection.create_index('external_id', unique=True)
            self.collection.create_index('type')
            self.collection.create_index('is_active')
            logger.info(f"Индексы созданы/проверены в {self.db_name}.{self.collection_name}")
        except Exception as e:
            logger.warning(f"Ошибка при создании индексов: {e}")

    def save_users(self, users: List[Dict], active_ids: Set[str],
                   user_types: List[str], deactivate_missing: bool = True) -> SyncStatistics:
        """Сохранение пользователей в БД"""
        if not users:
            logger.warning("Нет данных для сохранения")
            return SyncStatistics()

        stats = SyncStatistics()
        stats.total_processed = len(users)

        operations = []
        now = datetime.now()

        for user in users:
            user['is_active'] = True
            user['updated_at'] = now

            operations.append(UpdateOne(
                {'external_id': user['external_id']},
                {'$set': user},
                upsert=True
            ))

        if operations:
            for i in range(0, len(operations), BATCH_SIZE):
                batch = operations[i:i + BATCH_SIZE]
                batch_result = self.collection.bulk_write(batch)
                stats.created += batch_result.upserted_count
                stats.updated += batch_result.modified_count

        if deactivate_missing and active_ids:
            deactivated = self.collection.update_many(
                {
                    'external_id': {'$nin': list(active_ids)},
                    'type': {'$in': user_types}
                },
                {
                    '$set': {
                        'is_active': False,
                        'deactivated_at': now
                    }
                }
            )
            stats.deactivated = deactivated.modified_count

        for user in users:
            if user['type'] == 'student':
                stats.students += 1
            elif user['type'] == 'parent':
                stats.parents += 1
            elif user['type'] == 'teacher':
                stats.teachers += 1

        logger.info(
            f"Сохранено: +{stats.created} создано, {stats.updated} обновлено, {stats.deactivated} деактивировано")

        return stats

    def get_statistics(self) -> Dict:
        """Получение статистики БД"""
        total = self.collection.count_documents({})

        type_stats = {}
        for doc in self.collection.aggregate([
            {"$group": {"_id": "$type", "count": {"$sum": 1}}}
        ]):
            type_stats[doc['_id']] = doc['count']

        active = self.collection.count_documents({"is_active": True})

        return {
            'total': total,
            'by_type': type_stats,
            'active': active,
            'inactive': total - active
        }

    def display_statistics(self):
        """Отображение статистики БД"""
        stats = self.get_statistics()

        print("\n" + "=" * 50)
        print(f"📊 СТАТИСТИКА БАЗЫ ДАННЫХ ({self.db_name}.{self.collection_name})")
        print("=" * 50)
        print(f"📌 Всего записей: {stats['total']}")
        print(f"✅ Активных: {stats['active']}")
        print(f"❌ Неактивных: {stats['inactive']}")

        if stats['by_type']:
            print("\n📋 По типам:")
            for type_name, count in stats['by_type'].items():
                type_icon = {
                    'student': '👨‍🎓',
                    'parent': '👪',
                    'teacher': '👨‍🏫'
                }.get(type_name, '📄')
                print(f"   {type_icon} {type_name}: {count}")

        print("=" * 50)

    def close(self):
        """Закрытие соединения"""
        self.client.close()


class SynchronizationOrchestrator:
    """Оркестратор синхронизации"""

    def __init__(self, mos_token: str, sferum_token: Optional[str] = None,
                 mongo_uri: str = None, db_name: str = None, collection: str = None):
        self.mos_client = MosApiClient(mos_token)
        self.sferum_client = SferumClient(sferum_token) if sferum_token else None

        # Получаем данные из Sferum и передаем в MOS клиент
        if self.sferum_client:
            max_data = self.sferum_client.get_contacts()
            self.mos_client.set_max_data(max_data)

        self.data_processor = UserDataProcessor(
            normalizer=DataNormalizer(),
            mos_client=self.mos_client
        )

        self.db_manager = DatabaseManager(
            uri=mongo_uri or DEFAULT_MONGO_URI,
            db_name=db_name or DEFAULT_DB_NAME,
            collection_name=collection or DEFAULT_COLLECTION_NAME
        )
        self.include_max = sferum_token is not None
        logger.info(f"Режим MAX: {'включен' if self.include_max else 'выключен'}")

    def sync_teachers(self, deactivate: bool = True) -> SyncStatistics:
        """Синхронизация учителей"""
        logger.info("👨‍🏫 Начало синхронизации учителей")

        teachers = self.mos_client.get_teachers()
        logger.info(f"Получено учителей: {len(teachers)}")

        processed_teachers = []
        teacher_ids = set()

        for teacher in teachers:
            processed = self.data_processor.process_teacher_data(teacher, self.include_max)
            if processed:
                processed_teachers.append(processed)
                teacher_ids.add(processed['external_id'])

        stats = self.db_manager.save_users(
            processed_teachers,
            teacher_ids,
            ['teacher'],
            deactivate
        )

        logger.info(f"✅ Синхронизация учителей завершена")
        return stats

    def sync_students_and_parents(self, deactivate: bool = True,
                                  parallel: bool = True) -> SyncStatistics:
        """Синхронизация учеников и родителей"""
        logger.info("👨‍🎓 Начало синхронизации учеников и родителей")

        self.data_processor.reset_cache()

        classes = self.mos_client.get_class_list()
        if not classes:
            logger.warning("Нет классов для обработки")
            return SyncStatistics()

        all_users = []

        if parallel and len(classes) > 1:
            all_users = self._parallel_class_processing(classes)
        else:
            all_users = self._sequential_class_processing(classes)

        students = [u for u in all_users if u['type'] == 'student']
        parents = [u for u in all_users if u['type'] == 'parent']

        logger.info(f"Собрано: {len(students)} учеников, {len(parents)} родителей")

        all_ids = {u['external_id'] for u in all_users}
        stats = self.db_manager.save_users(
            all_users,
            all_ids,
            ['student', 'parent'],
            deactivate
        )

        return stats

    def _parallel_class_processing(self, classes: List[str]) -> List[Dict]:
        """Параллельная обработка классов"""
        all_users = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_class = {
                executor.submit(self._process_single_class, class_id): class_id
                for class_id in classes
            }

            for future in as_completed(future_to_class):
                try:
                    class_users = future.result(timeout=60)
                    all_users.extend(class_users)
                    logger.debug(f"Класс {future_to_class[future]}: {len(class_users)} пользователей")
                except Exception as e:
                    logger.error(f"Ошибка обработки класса: {e}")

        return all_users

    def _sequential_class_processing(self, classes: List[str]) -> List[Dict]:
        """Последовательная обработка классов"""
        all_users = []

        for class_id in classes:
            class_users = self._process_single_class(class_id)
            all_users.extend(class_users)
            logger.debug(f"Класс {class_id}: {len(class_users)} пользователей")

        return all_users

    def _process_single_class(self, class_id: str) -> List[Dict]:
        """Обработка одного класса"""
        students_data = self.mos_client.get_students_by_class(class_id)

        if not students_data:
            return []

        class_users = []
        for student in students_data:
            class_users.extend(
                self.data_processor.process_student_data(student, self.include_max)
            )

        return class_users

    def sync_all(self) -> Dict[str, SyncStatistics]:
        """Полная синхронизация всех данных"""
        logger.info("🚀 Начало полной синхронизации")

        results = {
            'teachers': self.sync_teachers(deactivate=True),
            'students_parents': self.sync_students_and_parents(
                deactivate=True,
                parallel=True
            )
        }

        logger.info("✅ Полная синхронизация завершена")
        return results

    def close(self):
        """Закрытие всех соединений"""
        self.mos_client.close()
        self.db_manager.close()
        logger.info("Соединения закрыты")


class InteractiveCLI:
    """Интерактивный интерфейс командной строки"""

    @staticmethod
    def clear_screen():
        """Очистка экрана"""
        os.system('cls' if os.name == 'nt' else 'clear')

    @staticmethod
    def print_header():
        """Вывод заголовка"""
        print("=" * 60)
        print("   🏫 СИНХРОНИЗАЦИЯ ДАННЫХ MOS.RU СО ШКОЛЬНОЙ БАЗОЙ")
        print("=" * 60)

    @staticmethod
    def get_input(prompt: str, required: bool = True) -> str:
        """Получение ввода от пользователя"""
        while True:
            value = input(prompt).strip()
            if value or not required:
                return value
            print("❌ Это поле обязательно для заполнения")

    @staticmethod
    def get_choice(prompt: str, options: List[str]) -> int:
        """Получение выбора пользователя"""
        print(prompt)
        for i, option in enumerate(options, 1):
            print(f"   {i}. {option}")

        while True:
            try:
                choice = int(input("Выберите номер: "))
                if 1 <= choice <= len(options):
                    return choice
                print(f"❌ Введите число от 1 до {len(options)}")
            except ValueError:
                print("❌ Введите число")

    @staticmethod
    def get_yes_no(prompt: str, default: bool = True) -> bool:
        """Получение ответа да/нет"""
        suffix = " (Y/n): " if default else " (y/N): "
        while True:
            response = input(prompt + suffix).strip().lower()
            if not response:
                return default
            if response in ['y', 'yes', 'да', 'д']:
                return True
            if response in ['n', 'no', 'нет', 'н']:
                return False
            print("❌ Введите Y или N")

    def run(self):
        """Запуск интерактивного интерфейса"""
        self.clear_screen()
        self.print_header()

        print(
            f"\n📁 Текущие настройки БД: {MONGO_SETTINGS['uri']} - {MONGO_SETTINGS['db_name']}.{MONGO_SETTINGS['collection_name']}")

        change_db = self.get_yes_no("\nИзменить настройки подключения к БД?", default=False)

        mongo_uri = MONGO_SETTINGS['uri']
        db_name = MONGO_SETTINGS['db_name']
        collection = MONGO_SETTINGS['collection_name']

        if change_db:
            mongo_uri = self.get_input(f"URI MongoDB [{mongo_uri}]: ", required=False) or mongo_uri
            db_name = self.get_input(f"Имя БД [{db_name}]: ", required=False) or db_name
            collection = self.get_input(f"Имя коллекции [{collection}]: ", required=False) or collection

        print("\n🔑 Введите данные для авторизации")

        default_mos = Config.get_token('mos_ru')
        mos_prompt = f"Токен MOS.RU"
        if default_mos:
            mos_prompt += f" (есть в конфиге)"
        mos_prompt += ": "

        mos_token = self.get_input(mos_prompt, required=True)
        if not mos_token and default_mos:
            mos_token = default_mos

        print("\n🔗 Для получения MAX ID требуется токен Sferum")
        include_sferum = self.get_yes_no("Подключать данные из Sferum", default=True)

        sferum_token = None
        if include_sferum:
            default_sferum = Config.get_token('sferum')
            sferum_prompt = f"Токен Sferum"
            if default_sferum:
                sferum_prompt += f" (есть в конфиге)"
            sferum_prompt += ": "

            sferum_token = self.get_input(sferum_prompt, required=True)
            if not sferum_token and default_sferum:
                sferum_token = default_sferum

        print("\n📋 Выберите тип синхронизации")
        sync_type = self.get_choice(
            "Что синхронизировать?",
            ["Только учителей", "Только учеников и родителей", "Всё вместе"]
        )

        use_parallel = self.get_yes_no("\nИспользовать параллельную обработку", default=True)

        print("\n" + "=" * 60)
        print("ПРОВЕРЬТЕ НАСТРОЙКИ:")
        print(f"📌 Подключение к БД: {mongo_uri} - {db_name}.{collection}")
        print(f"📌 MOS.RU токен: {'✓' if mos_token else '✗'}")
        print(f"📌 Sferum токен: {'✓' if sferum_token else '✗'}")
        print(f"📌 MAX данные: {'будут загружены' if sferum_token else 'не будут загружены'}")
        print(f"📌 Тип синхронизации: {['Только учителя', 'Только ученики/родители', 'Всё вместе'][sync_type - 1]}")
        print(f"📌 Параллельная обработка: {'Да' if use_parallel else 'Нет'}")
        print(f"📌 MAX Workers: {MAX_WORKERS}")
        print(f"📌 Batch size: {BATCH_SIZE}")
        print("=" * 60)

        if not self.get_yes_no("\nНачать синхронизацию?", default=True):
            print("❌ Синхронизация отменена")
            return

        self.clear_screen()
        print("\n🚀 ЗАПУСК СИНХРОНИЗАЦИИ...\n")

        orchestrator = SynchronizationOrchestrator(
            mos_token=mos_token,
            sferum_token=sferum_token,
            mongo_uri=mongo_uri,
            db_name=db_name,
            collection=collection
        )

        try:
            if sync_type == 1:
                stats = orchestrator.sync_teachers(deactivate=True)
                stats.display()

            elif sync_type == 2:
                stats = orchestrator.sync_students_and_parents(
                    deactivate=True,
                    parallel=use_parallel
                )
                stats.display()

            elif sync_type == 3:
                results = orchestrator.sync_all()

                print("\n📊 ИТОГИ ПО КАЖДОЙ ГРУППЕ:")
                for group_name, stats in results.items():
                    print(f"\n{group_name.upper()}:")
                    print(f"   Создано: {stats.created}")
                    print(f"   Обновлено: {stats.updated}")
                    print(f"   Деактивировано: {stats.deactivated}")

            orchestrator.db_manager.display_statistics()

        except KeyboardInterrupt:
            print("\n\n⚠️ Синхронизация прервана пользователем")
        except Exception as e:
            logger.exception("Критическая ошибка")
            print(f"\n❌ Произошла ошибка: {e}")
        finally:
            orchestrator.close()

        print("\n✅ Готово!")


def main():
    """Основная функция"""
    cli = InteractiveCLI()
    cli.run()


if __name__ == "__main__":
    main()