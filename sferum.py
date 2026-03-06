import requests
import json
from typing import Dict

class SferumContacts:
    def __init__(self, bearer_token: str)->None:
        self.bearer_token: str
        self.organization_id: int = 45074
        self.limit: int = 10000
        self.offset: int = 0
        self.bearer_token = bearer_token
        self.base_url = "https://platform-api.sferum-dev.ru/api/v1/contacts"
    def get_contacts(self) -> Dict[str, int]:

        headers = {
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {self.bearer_token}",
        }
        payload = {
            "sortBy": "maxId",
            "organization_id": self.organization_id,
            "limit": self.limit,
            "offset": self.offset
        }

        try:
            # Выполняем POST запрос
            response = requests.post(self.base_url, headers=headers, json=payload)

            # Проверяем статус ответа
            if response.status_code != 200:
                raise Exception(f"API вернул ошибку {response.status_code}: {response.text}")

            # Парсим ответ
            data = response.json()

            # Формируем словарь
            result_dict = {}
            items = data.get('response', {}).get('items', [])

            print(f"Получено записей: {len(items)}")

            for item in items:
                link = item.get('link')
                max_id = item.get('maxId')
                if link:  # Проверяем, что link существует
                    result_dict[link] = max_id
                print(f"Сформировано записей в словаре: {len(result_dict)}")
            return result_dict

        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при выполнении запроса: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"Ошибка при парсинге JSON ответа: {e}")

