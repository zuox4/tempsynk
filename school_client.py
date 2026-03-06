import requests


class SchoolLocalClient:
    def __init__(self):
        self.url = 'https://school1298.ru/portal/workers/workersPS-no.json'

    def load_data(self):
        """Загрузка данных из API"""
        try:
            response = requests.get(self.url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Ошибка загрузки данных: {e}")
            return {"value": []}

    def parse_teacher_data(self, data):
        """Парсинг данных учителей и возврат словаря {имя: email}"""
        teachers = {}

        if not data or 'value' not in data:
            print("Нет данных для парсинга")
            return teachers

        for staff_item in data['value']:
            # Получаем имя
            name = staff_item.get('name')
            if not name:  # Пропускаем записи без имени
                continue

            # Получаем email и проверяем на "нет"
            email_raw = staff_item.get('email')

            # Проверка: если email отсутствует или равен "нет" (в любом регистре)
            if email_raw and str(email_raw).strip().lower() != 'нет':
                email = str(email_raw).strip().lower()
            else:
                email = None

            # Добавляем в словарь
            teachers[name] = email

            # Для отладки (можно закомментировать)
            print(f"Обработан: {name} -> {email}")

        print(f"Всего обработано учителей: {len(teachers)}")
        return teachers

    def get_teachers(self):
        """Получение словаря учителей {имя: email}"""
        data = self.load_data()
        teachers = self.parse_teacher_data(data)
        return teachers