import mysql.connector
from collections import deque
from datetime import datetime
import asyncio
import logging

# Налаштування логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class QueueManager:
    def __init__(self, db_config):
        self.db_config = db_config
        logger.info(f"Ініціалізація QueueManager з db_config: {db_config}")
        self.queues = {}  # Словник черг: {university_id: deque}
        self.user_names = {}  # Кеш імен: {(user_id, university_id): user_name}
        self.join_times = {}  # Кеш часу входу: {(user_id, university_id): join_time}

    async def startup(self):
        """Виконує ініціалізацію під час запуску бота"""
        logger.info("Запуск ініціалізації бази даних")
        await self.init_db()

    async def init_db(self):
        """Ініціалізація бази даних і таблиць"""
        try:
            logger.info("Спроба підключення до MySQL")
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            logger.info("Підключення до MySQL успішне")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS universities (
                    university_id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    UNIQUE (name)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    user_name VARCHAR(255) NOT NULL,
                    phone_number VARCHAR(20) NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue (
                    user_id BIGINT NOT NULL,
                    university_id INT NOT NULL,
                    join_time DATETIME NOT NULL,
                    PRIMARY KEY (user_id, university_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (university_id) REFERENCES universities(university_id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    action VARCHAR(255) NOT NULL,
                    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    admin_id BIGINT NOT NULL,
                    message_text TEXT NOT NULL,
                    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (admin_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            conn.commit()
            logger.info("База даних ініціалізована")
            await self.load_queue()
        except mysql.connector.Error as e:
            logger.error(f"Помилка ініціалізації бази даних: {e}")
            raise
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def is_admin(self, user_id: int) -> bool:
        """Перевіряє, чи є користувач адміністратором"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT is_admin FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            return result is not None and result[0]
        except mysql.connector.Error as e:
            logger.error(f"Помилка перевірки статусу адміністратора: {e}")
            return False
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def get_universities(self):
        """Отримує список університетів"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT university_id, name FROM universities")
            universities = cursor.fetchall()
            logger.info("Університети успішно завантажені")
            return universities
        except mysql.connector.Error as e:
            logger.error(f"Помилка завантаження університетів: {e}")
            return []
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def load_queue(self):
        """Завантаження черг з бази даних для всіх університетів"""
        self.queues.clear()
        self.user_names = {}
        self.join_times = {}
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT q.user_id, u.user_name, q.university_id, q.join_time 
                FROM queue q
                JOIN users u ON q.user_id = u.user_id
                ORDER BY q.join_time
            """)
            for row in cursor.fetchall():
                user_id, user_name, university_id, join_time = row
                if university_id not in self.queues:
                    self.queues[university_id] = deque()
                self.queues[university_id].append(user_id)
                self.user_names[(user_id, university_id)] = user_name
                self.join_times[(user_id, university_id)] = join_time
            logger.info("Черги успішно завантажені з бази даних")
        except mysql.connector.Error as e:
            logger.error(f"Помилка завантаження черг: {e}")
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def save_queue(self):
        """Збереження всіх черг у базу даних"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM queue")
            for university_id, queue in self.queues.items():
                for user_id in queue:
                    cursor.execute(
                        "INSERT INTO queue (user_id, university_id, join_time) VALUES (%s, %s, %s)",
                        (user_id, university_id, self.join_times[(user_id, university_id)])
                    )
            conn.commit()
            logger.info("Черги успішно збережені в базі даних")
        except mysql.connector.Error as e:
            logger.error(f"Помилка збереження черг: {e}")
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def save_user_phone(self, user_id: int, user_name: str, phone_number: str):
        """Збереження номера телефону користувача"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (user_id, user_name, phone_number, is_admin) VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE user_name=%s, phone_number=%s",
                (user_id, user_name, phone_number, False, user_name, phone_number)
            )
            conn.commit()
            logger.info(f"Збережено номер: {phone_number} для {user_name} (ID: {user_id})")
        except mysql.connector.Error as e:
            logger.error(f"Помилка збереження номера телефону: {e}")
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def phone_exists(self, user_id: int) -> str:
        """Перевірка, чи існує номер телефону для користувача"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else None
        except mysql.connector.Error as e:
            logger.error(f"Помилка перевірки номера телефону: {e}")
            return None
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def log_action(self, user_id: int, user_name: str, action: str):
        """Запис дії в історію"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_history (user_id, action) VALUES (%s, %s)",
                (user_id, action)
            )
            conn.commit()
            logger.info(f"Дія записана: {action} для {user_name} (ID: {user_id})")
        except mysql.connector.Error as e:
            logger.error(f"Помилка запису історії: {e}")
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def get_user_history(self, user_id: int) -> str:
        """Повертає історію дій користувача (доступно лише для адмінів)"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.user_name, h.action, h.timestamp 
                FROM user_history h
                JOIN users u ON h.user_id = u.user_id
                WHERE h.user_id = %s 
                ORDER BY h.timestamp DESC
            """, (user_id,))
            history = cursor.fetchall()
            if not history:
                return "Історія дій порожня."
            result = ["📜 Історія дій:"]
            for user_name, action, timestamp in history:
                result.append(f"[{timestamp}] {user_name}: {action}")
            return "\n".join(result)
        except mysql.connector.Error as e:
            logger.error(f"Помилка отримання історії користувача: {e}")
            return "Помилка при отриманні історії."
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    async def broadcast_message(self, bot, admin_id: int, admin_name: str, message_text: str, university_id: int):
        """Зберігає повідомлення в базу даних і надсилає його користувачам у черзі вибраного університету"""
        try:
            # Збереження повідомлення в базу даних
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO broadcast_messages (admin_id, message_text) VALUES (%s, %s)",
                (admin_id, message_text)
            )
            conn.commit()
            logger.info(f"Оголошення збережено від {admin_name} (ID: {admin_id})")

            # Логування дії
            await self.log_action(admin_id, admin_name, f"broadcast_message_university_{university_id}: {message_text[:50]}...")

            # Отримання користувачів у черзі вибраного університету
            users = list(self.queues.get(university_id, deque()))
            logger.info(f"Надсилання оголошення {len(users)} користувачам університету {university_id}")

            # Форматування повідомлення
            broadcast_text = f"📢 Оголошення від адміністратора {admin_name}:\n{message_text}"

            # Надсилання повідомлення кожному користувачу в черзі
            for user_id in users:
                try:
                    await bot.send_message(chat_id=user_id, text=broadcast_text)
                    logger.info(f"Оголошення надіслано користувачу {user_id} у університеті {university_id}")
                except Exception as e:
                    logger.error(f"Помилка надсилання оголошення користувачу {user_id}: {e}")
                    continue

        except mysql.connector.Error as e:
            logger.error(f"Помилка збереження оголошення: {e}")
            raise
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    def join_queue(self, user_id: int, user_name: str, university_id: int) -> str:
        """Додає користувача до черги університету"""
        if university_id not in self.queues:
            self.queues[university_id] = deque()
        queue = self.queues[university_id]
        if user_id not in queue:
            queue.append(user_id)
            self.user_names[(user_id, university_id)] = user_name
            self.join_times[(user_id, university_id)] = datetime.now()
            asyncio.create_task(self.log_action(user_id, user_name, f"join_queue_university_{university_id}"))
            return f"{user_name}, ви додані до черги університету. Ваш номер: {len(queue)}"
        return "Ви вже в черзі цього університету!"

    def leave_queue(self, user_id: int, university_id: int) -> str:
        """Видаляє користувача з черги університету"""
        if university_id not in self.queues or user_id not in self.queues[university_id]:
            logger.warning(f"Користувач (ID: {user_id}) не в черзі університету {university_id}")
            return "Вас немає в черзі цього університету!"
        self.queues[university_id].remove(user_id)
        user_name = self.user_names.pop((user_id, university_id))
        self.join_times.pop((user_id, university_id))
        if not self.queues[university_id]:
            del self.queues[university_id]
        logger.info(f"Користувач {user_name} (ID: {user_id}) покинув чергу університету {university_id}")
        asyncio.create_task(self.log_action(user_id, user_name, f"leave_queue_university_{university_id}"))
        return f"{user_name}, ви покинули чергу університету."

    def view_queue(self, university_id: int) -> str:
        """Повертає список учасників черги університету в рамці"""
        if university_id not in self.queues or not self.queues[university_id]:
            logger.info(f"Черга для університету {university_id} порожня")
            return "Черга порожня."
        
        queue_list = [f"{i+1}. {self.user_names[(uid, university_id)]}" for i, uid in enumerate(self.queues[university_id])]
        max_length = max(len(line) for line in queue_list) if queue_list else 10
        max_length = max(max_length, len("Поточна черга"))
        
        top_border = "╔" + "═" * (max_length + 2) + "╗"
        bottom_border = "╚" + "═" * (max_length + 2) + "╝"
        title = f"║ {'Поточна черга'.center(max_length)} ║"
        separator = "╟" + "─" * (max_length + 2) + "╢"
        queue_rows = [f"║ {line.ljust(max_length)} ║" for line in queue_list]
        
        result = [top_border, title, separator] + queue_rows + [bottom_border]
        logger.info(f"Запит на перегляд черги для університету {university_id}")
        return "\n".join(result)

    async def next_in_queue(self, university_id: int, bot) -> tuple[str, list[int]]:
        """Викликає наступного користувача з черги університету та сповіщає всіх про нову позицію"""
        if university_id not in self.queues or not self.queues[university_id]:
            logger.info(f"Черга для університету {university_id} порожня при виклику наступного")
            return "Черга порожня.", []
        # Видаляємо першого користувача
        next_user = self.queues[university_id].popleft()
        next_name = self.user_names.pop((next_user, university_id))
        self.join_times.pop((next_user, university_id))
        # Перевіряємо, чи залишилися користувачі в черзі
        if not self.queues[university_id]:
            del self.queues[university_id]
            logger.info(f"Черга для університету {university_id} порожня після видалення {next_name} (ID: {next_user})")
            return "Черга порожня.", []
        # Отримуємо ім'я наступного користувача (тепер першого в черзі)
        new_first_user = self.queues[university_id][0]
        new_first_name = self.user_names[(new_first_user, university_id)]
        updated_users = list(self.queues.get(university_id, deque()))
        # Сповіщаємо всіх користувачів у черзі про їхні нові позиції
        for index, user_id in enumerate(updated_users):
            try:
                position_message = await self.notify_position(user_id, university_id)
                await bot.send_message(
                    chat_id=user_id,
                    text=f"Черга зрушила! {position_message}"
                )
                logger.info(f"Сповіщення про нову позицію надіслано користувачу {user_id} у університеті {university_id}")
            except Exception as e:
                logger.error(f"Помилка надсилання сповіщення користувачу {user_id}: {e}")
                continue
        logger.info(f"Наступний користувач після видалення {next_name} (ID: {next_user}): {new_first_name} (ID: {new_first_user}) у університеті {university_id}")
        await self.log_action(next_user, next_name, f"next_in_queue_university_{university_id}")
        return f"Наступний: {new_first_name}", updated_users

    async def notify_position(self, user_id: int, university_id: int) -> str:
        """Повертає повідомлення про поточну позицію користувача в черзі університету"""
        if university_id not in self.queues or user_id not in self.queues[university_id]:
            logger.warning(f"Користувач (ID: {user_id}) не в черзі університету {university_id}")
            return "Вас немає в черзі цього університету!"
        position = list(self.queues[university_id]).index(user_id) + 1
        logger.info(f"Сповіщення позиції для {self.user_names[(user_id, university_id)]} (ID: {user_id}) у {university_id}: {position}")
        return f"{self.user_names[(user_id, university_id)]}, ваша позиція в черзі: {position}"

    async def remind_first(self, bot, chat_id: int, university_id: int):
        """Нагадує першому користувачу в черзі університету через 1 хвилину"""
        if university_id not in self.queues or not self.queues[university_id]:
            logger.info(f"Черга для університету {university_id} порожня, нагадування не потрібне")
            return
        await asyncio.sleep(60)
        if university_id in self.queues and self.queues[university_id]:
            first_user = self.queues[university_id][0]
            try:
                await bot.send_message(
                    chat_id=first_user,
                    text=f"{self.user_names[(first_user, university_id)]}, ви перший у черзі університету! Будь ласка, підготуйтеся."
                )
                logger.info(f"Нагадування надіслано першому користувачу (ID: {first_user}) у {university_id}")
            except Exception as e:
                logger.error(f"Помилка надсилання нагадування для університету {university_id}: {e}")