# main.py - 5 AKKAUNT, STABIL, RAQAMLARNI YANGILASH IMKONIYATI BILAN

import asyncio
import random
import re
import os
import json
import logging
import traceback
import html
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque
from contextlib import suppress
from typing import Dict, List, Set, Optional, Any

from telethon import TelegramClient, events, functions, types
from telethon.errors import (
    FloodWaitError, 
    UserAlreadyParticipantError,
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    ChannelPrivateError,
    ChannelInvalidError,
    AuthKeyUnregisteredError,
    RPCError
)
from telethon.tl.functions.messages import ImportChatInviteRequest, GetMessagesViewsRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Message

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message as AiogramMessage, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== KONFIGURATSIYA ====================
BOT_TOKEN = "8596969237:AAEv1_69b6g02tkbLccsuJS46rFz1eIcreE"
ADMIN_ID = 8255722717
MONITOR_CHANNEL = "@Obunachi_X"

# 🔥 UNIVERSAL API
API_ID = 17349
API_HASH = "344583e45741c457fe1862106095a5eb"

BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"
LOGS_DIR = BASE_DIR / "logs"
CACHE_DIR = BASE_DIR / "cache"
BACKUP_DIR = BASE_DIR / "backups"

LOGS_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

# ==================== 5 AKKAUNT UCHUN OPTIMAL SOZLAMALAR ====================
MAX_ACCOUNTS = 5
DEBUG_MODE = False
LOG_LEVEL = logging.INFO

JOIN_DELAY = 0.5
CLICK_DELAY = 0.5
MAX_RETRIES = 2
RETRY_DELAY = 0.3

ACCOUNT_DELAY_MIN = 1.5
ACCOUNT_DELAY_MAX = 2.5
TASK_BREAK_INTERVAL = 10
TASK_BREAK_DURATION = 15

MAX_QUEUE_SIZE = 50
TASK_TIMEOUT = 60
MONITOR_HEARTBEAT = 45
TASK_CACHE_LIMIT = 100
FLOOD_WAIT_LIMIT = 45

# ==================== LOG YOZISH ====================
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / f"bot_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logging.getLogger('telethon').setLevel(logging.WARNING)
logging.getLogger('aiogram').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def log_error(error, context=""):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_file = LOGS_DIR / f"errors_{datetime.now().strftime('%Y%m%d')}.log"
    
    with open(error_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{timestamp} | {context} | {str(error)}\n")

# ==================== BOT VA DISPATCHER ====================
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

# ==================== FSM HOLATLARI ====================
class LoginStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

class UpdatePhoneStates(StatesGroup):
    waiting_old_phone = State()
    waiting_new_phone = State()
    waiting_code = State()
    waiting_password = State()

# ==================== YORDAMCHI FUNKSIYA ====================
def clean_text(text: Any) -> str:
    if text is None:
        return ""
    
    text = str(text)
    text = text.replace('\\', '')
    text = text.replace("'", "\u0027")
    text = html.escape(text)
    
    if len(text) > 1000:
        text = text[:1000] + "..."
    
    return text

def format_phone(phone: str) -> str:
    """Telefon raqamni formatlash"""
    phone = re.sub(r'[^0-9+]', '', phone)
    if not phone.startswith('+'):
        phone = f"+{phone}"
    return phone

# ==================== TOPSHIRIQ NAVBATI ====================
class TaskQueue:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self.processed_tasks: Set[str] = set()
        self.current_task = None
    
    async def add_task(self, task_id: str, channel: str, message, monitor_phone: str) -> bool:
        if task_id in self.processed_tasks:
            return False
        
        try:
            await self.queue.put({
                'id': task_id,
                'channel': channel,
                'message': message,
                'monitor_phone': monitor_phone,
                'added_time': datetime.now()
            })
            return True
        except asyncio.QueueFull:
            return False
    
    def mark_done(self, task_id: str):
        self.processed_tasks.add(task_id)
        if len(self.processed_tasks) > TASK_CACHE_LIMIT:
            self.processed_tasks = set(list(self.processed_tasks)[-TASK_CACHE_LIMIT:])

# ==================== ACCOUNT MANAGER ====================
class AccountManager:
    def __init__(self):
        self.api_id = API_ID
        self.api_hash = API_HASH
        self.active_clients: Dict[str, Dict] = {}
        self.pending_logins: Dict[str, TelegramClient] = {}
        self.pending_updates: Dict[str, Dict] = {}  # Raqam yangilash uchun
        self.monitor_channel = MONITOR_CHANNEL
        self.start_time = datetime.now()
        
        self.task_queue = TaskQueue()
        self.processor_task: Optional[asyncio.Task] = None
        
        self.monitor_client = None
        self.monitor_phone = None
        self.monitor_task: Optional[asyncio.Task] = None
        self.monitor_health_task: Optional[asyncio.Task] = None
        
        self.flood_wait_accounts: Dict[str, datetime] = {}
        self.account_tasks: Dict[str, int] = {}
        self.account_notes: Dict[str, str] = {}  # Akkaunt eslatmalari
        
    # ============= TASK ID =============
    def create_task_id(self, channel: str, message_id: int) -> str:
        return f"{channel}_{message_id}"
    
    # ============= AKKOUNT TEKSHIRISH =============
    async def check_account(self, client: TelegramClient, phone: str) -> bool:
        try:
            me = await client.get_me()
            if not me:
                return False
            
            if phone in self.flood_wait_accounts:
                if datetime.now() > self.flood_wait_accounts[phone]:
                    del self.flood_wait_accounts[phone]
                    self.account_tasks[phone] = 0
                    logger.info(f"✅ {phone[-4:]}: FloodWait tugadi")
                else:
                    return False
            return True
            
        except FloodWaitError as e:
            wait_until = datetime.now() + timedelta(seconds=e.seconds)
            self.flood_wait_accounts[phone] = wait_until
            logger.info(f"⏳ {phone[-4:]}: FloodWait {e.seconds}s")
            return False
        except Exception:
            return False
    
    def is_available(self, phone: str) -> bool:
        if phone in self.flood_wait_accounts:
            return datetime.now() > self.flood_wait_accounts[phone]
        return True
    
    # ============= DATABASE LOCK =============
    async def wait_delay(self, phone: str, action: str):
        delay = random.uniform(ACCOUNT_DELAY_MIN, ACCOUNT_DELAY_MAX)
        logger.info(f"⏱️ {phone[-4:]}: {action} - {delay:.1f}s")
        await asyncio.sleep(delay)
    
    async def rest_if_needed(self, phone: str):
        count = self.account_tasks.get(phone, 0)
        if count > 0 and count % TASK_BREAK_INTERVAL == 0:
            logger.info(f"💤 {phone[-4:]}: {TASK_BREAK_DURATION}s dam")
            await asyncio.sleep(TASK_BREAK_DURATION)
    
    # ============= RAQAM YANGILASH TIZIMI =============
    async def backup_session(self, phone: str) -> Optional[Path]:
        """Session faylni zaxiralash"""
        session_file = SESSIONS_DIR / f"{phone.replace('+', '')}.session"
        if session_file.exists():
            backup_file = BACKUP_DIR / f"{phone.replace('+', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.session.backup"
            shutil.copy2(session_file, backup_file)
            logger.info(f"💾 Backup yaratildi: {backup_file.name}")
            return backup_file
        return None
    
    async def start_phone_update(self, old_phone: str, new_phone: str) -> dict:
        """Raqam yangilashni boshlash"""
        result = {
            'success': False,
            'old_phone': old_phone,
            'new_phone': new_phone,
            'message': ''
        }
        
        try:
            # 1. Backup yaratish
            backup = await self.backup_session(old_phone)
            if backup:
                result['message'] += f"✅ Backup yaratildi\n"
            
            # 2. Eski clientni to'xtatish
            if old_phone in self.active_clients:
                try:
                    await self.active_clients[old_phone]["client"].disconnect()
                except:
                    pass
                del self.active_clients[old_phone]
                result['message'] += f"✅ Eski akkaunt to'xtatildi\n"
            
            # 3. Eski session faylni o'chirish
            old_session = SESSIONS_DIR / f"{old_phone.replace('+', '')}.session"
            if old_session.exists():
                old_session.unlink()
                result['message'] += f"🗑️ Eski session o'chirildi\n"
            
            # 4. Yangi raqam uchun login boshlash
            session_name = new_phone.replace('+', '').replace(' ', '')
            session_path = SESSIONS_DIR / f"{session_name}.session"
            
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if await client.is_user_authorized():
                me = await client.get_me()
                await self._add_client(client, me, new_phone)
                result['success'] = True
                result['message'] += f"✅ {new_phone} avtomatik ulandi\n"
            else:
                await client.send_code_request(new_phone)
                self.pending_updates[new_phone] = {
                    'client': client,
                    'old_phone': old_phone,
                    'new_phone': new_phone
                }
                result['success'] = True
                result['message'] += f"📨 {new_phone} ga kod yuborildi\n"
                result['need_code'] = True
                result['phone'] = new_phone
            
        except Exception as e:
            result['message'] = f"❌ Xatolik: {str(e)}"
            log_error(e, f"start_phone_update:{old_phone}->{new_phone}")
        
        return result
    
    async def verify_update_code(self, phone: str, code: str) -> dict:
        """Yangilash kodini tekshirish"""
        result = {
            'success': False,
            'phone': phone,
            'message': ''
        }
        
        if phone not in self.pending_updates:
            result['message'] = "❌ Yangilash sessiyasi topilmadi"
            return result
        
        data = self.pending_updates[phone]
        client = data['client']
        old_phone = data['old_phone']
        
        try:
            await client.sign_in(phone, code)
            me = await client.get_me()
            await self._add_client(client, me, phone)
            
            del self.pending_updates[phone]
            
            result['success'] = True
            result['message'] = f"✅ {old_phone[-4:]} → {phone[-4:]} yangilandi"
            
        except SessionPasswordNeededError:
            result['need_password'] = True
            result['message'] = "🔐 2FA parolni kiriting"
        except Exception as e:
            result['message'] = f"❌ Xatolik: {str(e)[:50]}"
        
        return result
    
    async def verify_update_password(self, phone: str, password: str) -> dict:
        """Yangilash parolini tekshirish"""
        result = {
            'success': False,
            'phone': phone,
            'message': ''
        }
        
        if phone not in self.pending_updates:
            result['message'] = "❌ Yangilash sessiyasi topilmadi"
            return result
        
        data = self.pending_updates[phone]
        client = data['client']
        old_phone = data['old_phone']
        
        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            await self._add_client(client, me, phone)
            
            del self.pending_updates[phone]
            
            result['success'] = True
            result['message'] = f"✅ {old_phone[-4:]} → {phone[-4:]} yangilandi"
            
        except Exception as e:
            result['message'] = f"❌ Xatolik: {str(e)[:50]}"
        
        return result
    
    # ============= AKKOUNTNI O'CHIRISH =============
    async def remove_account(self, phone: str, backup: bool = True) -> dict:
        """Akkauntni o'chirish"""
        result = {
            'success': False,
            'phone': phone,
            'message': ''
        }
        
        try:
            # Backup
            if backup:
                await self.backup_session(phone)
            
            # Clientni to'xtatish
            if phone in self.active_clients:
                try:
                    await self.active_clients[phone]["client"].disconnect()
                except:
                    pass
                del self.active_clients[phone]
                result['message'] += f"✅ Akkaunt to'xtatildi\n"
            
            # Session faylni o'chirish
            session_file = SESSIONS_DIR / f"{phone.replace('+', '')}.session"
            if session_file.exists():
                session_file.unlink()
                result['message'] += f"🗑️ Session o'chirildi\n"
            
            # FloodWait dan o'chirish
            if phone in self.flood_wait_accounts:
                del self.flood_wait_accounts[phone]
            
            # Task hisoblagichni o'chirish
            if phone in self.account_tasks:
                del self.account_tasks[phone]
            
            result['success'] = True
            result['message'] += f"✅ {phone} o'chirildi"
            
        except Exception as e:
            result['message'] = f"❌ Xatolik: {str(e)}"
        
        return result
    
    # ============= AKKOUNT RO'YXATI =============
    def get_all_phones(self) -> Dict:
        """Barcha raqamlar ro'yxati"""
        result = {
            'active': [],
            'sessions': [],
            'total': 0
        }
        
        # Aktiv akkauntlar
        for phone in self.active_clients.keys():
            result['active'].append({
                'phone': phone,
                'short': phone[-4:],
                'available': self.is_available(phone),
                'tasks': self.account_tasks.get(phone, 0),
                'flood': phone in self.flood_wait_accounts,
                'flood_remaining': (self.flood_wait_accounts[phone] - datetime.now()).seconds if phone in self.flood_wait_accounts else 0
            })
        
        # Session fayllar
        session_files = list(SESSIONS_DIR.glob("*.session"))
        for session_file in session_files:
            phone = session_file.stem
            if phone.startswith('998'):
                phone = f"+{phone}"
            
            is_active = any(phone in p for p in self.active_clients.keys())
            
            result['sessions'].append({
                'phone': phone,
                'short': phone[-4:],
                'active': is_active,
                'size': session_file.stat().st_size,
                'modified': datetime.fromtimestamp(session_file.stat().st_mtime).strftime('%H:%M %d.%m')
            })
        
        result['total'] = len(result['active'])
        return result
    
    # ============= MONITORING =============
    async def run_monitor(self):
        while is_monitoring:
            try:
                if not self.monitor_phone or self.monitor_phone not in self.active_clients:
                    await self.select_monitor()
                    continue
                
                self.monitor_client = self.active_clients[self.monitor_phone]["client"]
                
                if not self.monitor_client.is_connected():
                    await self.monitor_client.connect()
                
                entity = await self.monitor_client.get_entity(self.monitor_channel)
                
                @self.monitor_client.on(events.NewMessage(chats=entity))
                async def handler(event):
                    if not is_monitoring:
                        return
                    
                    channel = extract_channel_username(event.message.text)
                    if not channel:
                        return
                    
                    task_id = self.create_task_id(channel, event.message.id)
                    await self.task_queue.add_task(
                        task_id, channel, event.message, self.monitor_phone
                    )
                    logger.info(f"📥 Navbat: {channel}")
                
                logger.info(f"✅ Monitor: {self.monitor_phone[-4:]}")
                await self.monitor_client.run_until_disconnected()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Monitor xatolik, 3s...")
                await asyncio.sleep(3)
    
    async def select_monitor(self):
        for phone in list(self.active_clients.keys())[:MAX_ACCOUNTS]:
            if self.is_available(phone):
                self.monitor_phone = phone
                logger.info(f"✅ Monitor tanlandi: {phone[-4:]}")
                return True
        return False
    
    # ============= TOPSHIRIQ PROCESSOR =============
    async def process_tasks(self):
        while is_monitoring:
            try:
                task = await self.task_queue.queue.get()
                
                logger.info(f"\n📢 Topshiriq: {task['channel']}")
                
                if self.task_queue.processed_tasks and task['id'] in self.task_queue.processed_tasks:
                    logger.info(f"⏭️ Dublikat: {task['channel']}")
                    continue
                
                await self.execute_task(task)
                self.task_queue.mark_done(task['id'])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(e, "process_tasks")
    
    async def execute_task(self, task):
        channel = task['channel']
        message = task['message']
        
        phones = list(self.active_clients.keys())[:MAX_ACCOUNTS]
        available = [p for p in phones if self.is_available(p)]
        
        if not available:
            logger.warning("⚠️ Akkauntlar band")
            return
        
        logger.info(f"👥 Akkauntlar: {len(available)}/{len(phones)}")
        
        joined = []
        positions = {}
        
        for idx, phone in enumerate(available):
            position = idx + 1
            await self.rest_if_needed(phone)
            await self.wait_delay(phone, "join")
            
            success = await self.join_channel(phone, channel, position)
            if success:
                joined.append(phone)
                positions[phone] = position
                self.account_tasks[phone] = self.account_tasks.get(phone, 0) + 1
        
        if not joined:
            logger.warning("❌ Hech kim qo'shilmadi")
            return
        
        results = []
        
        for phone in joined:
            position = positions[phone]
            await self.rest_if_needed(phone)
            await self.wait_delay(phone, "click")
            
            response = await self.click_button(phone, message, channel, position)
            if response:
                results.append({
                    'phone': phone[-4:],
                    'response': clean_text(response)
                })
                self.account_tasks[phone] = self.account_tasks.get(phone, 0) + 1
        
        await self.send_results(results, channel)
    
    async def join_channel(self, phone, channel, position):
        if phone not in self.active_clients:
            return False
        
        client = self.active_clients[phone]["client"]
        
        try:
            clean = channel.strip()
            clean = re.sub(r'^https?://(www\.)?t\.me/', '', clean)
            clean = re.sub(r'^t\.me/', '', clean)
            
            if clean.startswith('+'):
                await client(ImportChatInviteRequest(clean[1:]))
            else:
                if not clean.startswith('@'):
                    clean = f'@{clean}'
                entity = await client.get_entity(clean)
                await client(JoinChannelRequest(entity))
            
            logger.info(f"✅ [{position}] {phone[-4:]}: Qo'shildi")
            return True
            
        except FloodWaitError as e:
            wait_until = datetime.now() + timedelta(seconds=e.seconds)
            self.flood_wait_accounts[phone] = wait_until
            logger.info(f"⏳ [{position}] {phone[-4:]}: FloodWait {e.seconds}s")
            return False
        except UserAlreadyParticipantError:
            return True
        except Exception:
            return False
    
    async def click_button(self, phone, message, channel, position):
        if phone not in self.active_clients:
            return None
        
        client = self.active_clients[phone]["client"]
        
        try:
            entity = await client.get_entity(self.monitor_channel)
            refreshed = await client.get_messages(entity, ids=message.id)
            
            if not refreshed or not refreshed.buttons:
                return None
            
            button = None
            for row in refreshed.buttons:
                for btn in row:
                    if re.search(r'tasdiq|✅|check|verify|confirm|obuna', btn.text, re.I):
                        button = btn
                        break
                if button:
                    break
            
            if not button and len(refreshed.buttons[0]) >= 2:
                button = refreshed.buttons[0][1]
            
            if button:
                result = await client(functions.messages.GetBotCallbackAnswerRequest(
                    peer=entity,
                    msg_id=message.id,
                    data=button.data if hasattr(button, 'data') else None
                ))
                
                response = "✅ Bajarildi!"
                if hasattr(result, 'message') and result.message:
                    response = result.message
                
                logger.info(f"✅ [{position}] {phone[-4:]}: Tugma bosildi")
                return response
            
            return None
            
        except FloodWaitError as e:
            wait_until = datetime.now() + timedelta(seconds=e.seconds)
            self.flood_wait_accounts[phone] = wait_until
            logger.info(f"⏳ [{position}] {phone[-4:]}: FloodWait {e.seconds}s")
            return None
        except Exception:
            return None
    
    async def send_results(self, results, channel):
        if not results:
            return
        
        channel_name = channel.replace('@', '')
        
        for res in results:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"✅ <b>Bajarildi</b>\n"
                    f"📢 @{channel_name}\n"
                    f"📱 +998{res['phone']}\n\n"
                    f"{res['response']}"
                )
                await asyncio.sleep(0.1)
            except:
                pass
    
    # ============= LOGIN FUNKSIYALARI =============
    async def start_login(self, phone_number):
        try:
            session_name = phone_number.replace('+', '').replace(' ', '')
            session_path = SESSIONS_DIR / f"{session_name}.session"
            
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if await client.is_user_authorized():
                me = await client.get_me()
                await self._add_client(client, me, phone_number)
                return {"status": "already_logged", "phone": phone_number, "me": me}
            else:
                await client.send_code_request(phone_number)
                self.pending_logins[phone_number] = client
                return {"status": "code_sent", "phone": phone_number}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def verify_code(self, phone_number, code):
        if phone_number not in self.pending_logins:
            return {"status": "error", "error": "Sessiya topilmadi"}
        client = self.pending_logins[phone_number]
        try:
            await client.sign_in(phone_number, code)
            me = await client.get_me()
            await self._add_client(client, me, phone_number)
            del self.pending_logins[phone_number]
            return {"status": "success", "phone": phone_number, "me": me}
        except SessionPasswordNeededError:
            return {"status": "password_needed", "phone": phone_number, "client": client}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def verify_password(self, phone_number, password):
        if phone_number not in self.pending_logins:
            return {"status": "error", "error": "Sessiya topilmadi"}
        client = self.pending_logins[phone_number]
        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            await self._add_client(client, me, phone_number)
            del self.pending_logins[phone_number]
            return {"status": "success", "phone": phone_number, "me": me}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def _add_client(self, client, me, phone_number):
        phone = me.phone or phone_number
        self.active_clients[phone] = {"client": client, "me": me}
        logger.info(f"✅ +998{phone[-4:]} qo'shildi")
        return phone
    
    async def load_sessions(self):
        session_files = list(SESSIONS_DIR.glob("*.session"))[:MAX_ACCOUNTS]
        count = 0
        
        for session_file in session_files:
            try:
                client = TelegramClient(str(session_file), self.api_id, self.api_hash)
                await client.connect()
                
                if await client.is_user_authorized():
                    me = await client.get_me()
                    phone = me.phone or session_file.stem
                    self.active_clients[phone] = {"client": client, "me": me}
                    count += 1
                    logger.info(f"✅ Yuklandi: {phone[-4:]}")
            except:
                pass
        
        logger.info(f"📊 Yuklangan: {count}/{len(session_files)}")
        return count
    
    async def stop_all(self):
        if self.monitor_task:
            self.monitor_task.cancel()
        if self.processor_task:
            self.processor_task.cancel()
        
        for phone in list(self.active_clients.keys()):
            try:
                await self.active_clients[phone]["client"].disconnect()
            except:
                pass
        
        self.active_clients.clear()
    
    def get_stats(self):
        return {
            'active': len(self.active_clients),
            'flood': len(self.flood_wait_accounts),
            'queue': self.task_queue.queue.qsize(),
            'uptime': str(datetime.now() - self.start_time).split('.')[0]
        }

# ==================== GLOBAL OBYEKTLAR ====================
account_manager = AccountManager()
is_monitoring = False

# ==================== YORDAMCHI ====================
def extract_channel_username(text):
    if not text:
        return None
    patterns = [r'@[\w_]+', r't\.me/\+[\w_]+', r'https?://t\.me/[\w_]+']
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            channel = matches[0]
            channel = re.sub(r'^https?://(www\.)?t\.me/', '', channel)
            channel = re.sub(r'^t\.me/', '', channel)
            return channel
    return None

# ==================== RAQAM YANGILASH HANDLERLARI ====================

@dp.message(Command("phones"))
async def cmd_phones(message: AiogramMessage):
    """Barcha raqamlarni ko'rsatish"""
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Ruxsat yo\u0027q")
        return
    
    data = account_manager.get_all_phones()
    
    text = f"📱 <b>5 AKKAUNT - RAQAM BOSHQARISH</b>\n\n"
    text += f"🟢 <b>Aktiv akkauntlar ({len(data['active'])}/5):</b>\n"
    
    for i, acc in enumerate(data['active'], 1):
        status = "🟢" if acc['available'] else "⏳"
        flood = f" ({acc['flood_remaining']}s)" if acc['flood'] else ""
        text += f"{i}. {status} <code>+998{acc['short']}</code> | {acc['tasks']} task{flood}\n"
    
    text += f"\n📁 <b>Session fayllar ({len(data['sessions'])}):</b>\n"
    
    for i, sess in enumerate(data['sessions'][:10], 1):
        status = "✅" if sess['active'] else "💤"
        text += f"{i}. {status} <code>{sess['short']}</code> | {sess['modified']}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Yangi", callback_data="add_account"),
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="update_phone_menu")
        ],
        [
            InlineKeyboardButton(text="🗑 O'chirish", callback_data="remove_phone_menu"),
            InlineKeyboardButton(text="💾 Backup", callback_data="backup_sessions")
        ]
    ])
    
    await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

@dp.callback_query(F.data == "update_phone_menu")
async def callback_update_menu(callback: CallbackQuery, state: FSMContext):
    """Raqam yangilash menyusi"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    if not account_manager.active_clients:
        await callback.message.answer("❌ Aktiv akkauntlar yo'q")
        return
    
    text = f"🔄 <b>Raqam yangilash</b>\n\n"
    text += f"Qaysi raqamni yangilamoqchisiz?\n\n"
    
    phones = list(account_manager.active_clients.keys())[:5]
    keyboard_buttons = []
    
    for i, phone in enumerate(phones, 1):
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"{i}. +998{phone[-4:]}", 
                callback_data=f"update_select_{phone}"
            )
        ])
    
    keyboard_buttons.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="back_to_phones")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback.message.answer(text, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("update_select_"))
async def callback_update_select(callback: CallbackQuery, state: FSMContext):
    """Yangilash uchun raqam tanlash"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    old_phone = callback.data.replace("update_select_", "")
    await state.update_data(old_phone=old_phone)
    
    await callback.message.answer(
        f"📱 <b>Raqam yangilash</b>\n\n"
        f"Eski raqam: <code>{old_phone}</code>\n"
        f"Yangi raqamni kiriting (+998901234567):"
    )
    await state.set_state(UpdatePhoneStates.waiting_new_phone)

@dp.message(UpdatePhoneStates.waiting_new_phone)
async def process_update_new_phone(message: AiogramMessage, state: FSMContext):
    """Yangi raqamni qabul qilish"""
    if message.from_user.id != ADMIN_ID:
        return
    
    data = await state.get_data()
    old_phone = data.get('old_phone')
    new_phone = format_phone(message.text.strip())
    
    if not re.match(r'^\+998\d{9}$', new_phone):
        await message.reply("❌ Noto'g'ri format. +998901234567")
        return
    
    msg = await message.reply(f"🔄 {old_phone[-4:]} → {new_phone[-4:]} yangilanmoqda...")
    
    result = await account_manager.start_phone_update(old_phone, new_phone)
    
    if result.get('need_code'):
        await state.update_data(phone=new_phone)
        await msg.edit_text(
            f"{result['message']}\n\n"
            f"📨 5 xonali kodni kiriting:"
        )
        await state.set_state(UpdatePhoneStates.waiting_code)
    else:
        await msg.edit_text(result['message'])
        await state.clear()

@dp.message(UpdatePhoneStates.waiting_code)
async def process_update_code(message: AiogramMessage, state: FSMContext):
    """Yangilash kodini tekshirish"""
    if message.from_user.id != ADMIN_ID:
        return
    
    code = message.text.strip()
    data = await state.get_data()
    phone = data.get('phone')
    
    msg = await message.reply("⏳ Kod tekshirilmoqda...")
    result = await account_manager.verify_update_code(phone, code)
    
    if result.get('need_password'):
        await msg.edit_text(result['message'])
        await state.set_state(UpdatePhoneStates.waiting_password)
    elif result['success']:
        await msg.edit_text(result['message'])
        await state.clear()
    else:
        await msg.edit_text(result['message'])
        await state.clear()

@dp.message(UpdatePhoneStates.waiting_password)
async def process_update_password(message: AiogramMessage, state: FSMContext):
    """Yangilash parolini tekshirish"""
    if message.from_user.id != ADMIN_ID:
        return
    
    password = message.text.strip()
    data = await state.get_data()
    phone = data.get('phone')
    
    msg = await message.reply("⏳ Parol tekshirilmoqda...")
    result = await account_manager.verify_update_password(phone, password)
    
    await msg.edit_text(result['message'])
    await state.clear()

@dp.callback_query(F.data == "remove_phone_menu")
async def callback_remove_menu(callback: CallbackQuery):
    """Raqam o'chirish menyusi"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    data = account_manager.get_all_phones()
    
    text = f"🗑 <b>Raqam o'chirish</b>\n\n"
    text += f"Aktiv akkauntlar:\n"
    
    keyboard_buttons = []
    
    for i, acc in enumerate(data['active'], 1):
        text += f"{i}. +998{acc['short']} - {acc['tasks']} task\n"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"❌ +998{acc['short']}", 
                callback_data=f"remove_confirm_{acc['phone']}"
            )
        ])
    
    keyboard_buttons.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="back_to_phones")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.answer(text, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("remove_confirm_"))
async def callback_remove_confirm(callback: CallbackQuery):
    """Raqamni o'chirishni tasdiqlash"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    phone = callback.data.replace("remove_confirm_", "")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha", callback_data=f"remove_yes_{phone}"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data="remove_no")
        ]
    ])
    
    await callback.message.answer(
        f"🗑 <b>{phone} o'chirilsinmi?</b>\n\n"
        f"Bu amalni ortga qaytarib bo'lmaydi!",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data and c.data.startswith("remove_yes_"))
async def callback_remove_yes(callback: CallbackQuery):
    """Raqamni o'chirish"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    phone = callback.data.replace("remove_yes_", "")
    
    msg = await callback.message.edit_text(f"🗑 {phone} o'chirilmoqda...")
    result = await account_manager.remove_account(phone)
    await msg.edit_text(result['message'])

@dp.callback_query(F.data == "remove_no")
async def callback_remove_no(callback: CallbackQuery):
    """O'chirishni bekor qilish"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    await callback.message.delete()

@dp.callback_query(F.data == "backup_sessions")
async def callback_backup_sessions(callback: CallbackQuery):
    """Barcha sessiyalarni zaxiralash"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    session_files = list(SESSIONS_DIR.glob("*.session"))
    count = 0
    
    for session_file in session_files:
        try:
            backup_file = BACKUP_DIR / f"{session_file.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.session.backup"
            shutil.copy2(session_file, backup_file)
            count += 1
        except:
            pass
    
    await callback.message.answer(f"✅ {count} ta session fayl zaxiralandi")

@dp.callback_query(F.data == "back_to_phones")
async def callback_back_to_phones(callback: CallbackQuery):
    """Raqamlar ro'yxatiga qaytish"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    await callback.message.delete()
    await cmd_phones(callback.message)

# ==================== ASOSIY BOT HANDLERLAR ====================

@dp.message(Command("start"))
async def cmd_start(message: AiogramMessage):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Ruxsat yo\u0027q")
        return
    
    msg = await message.reply("⚡ Bot ishga tushmoqda...")
    
    count = await account_manager.load_sessions()
    stats = account_manager.get_stats()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Raqamlar", callback_data="phones_cmd"),
            InlineKeyboardButton(text="📋 Akkauntlar", callback_data="list_accounts")
        ],
        [
            InlineKeyboardButton(text="🚀 MONITORING", callback_data="start_monitor"),
            InlineKeyboardButton(text="🛑 TO'XTATISH", callback_data="stop_monitor")
        ],
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="stats"),
            InlineKeyboardButton(text="🔄 Tiklash", callback_data="reload")
        ]
    ])
    
    await msg.edit_text(
        f"🤖 <b>5 AKKAUNT - RAQAM BOSHQARISH</b>\n\n"
        f"⏰ {stats['uptime']}\n"
        f"👥 {stats['active']}/{MAX_ACCOUNTS}\n"
        f"⏳ Navbat: {stats['queue']}\n"
        f"⚡ Delay: {ACCOUNT_DELAY_MIN}-{ACCOUNT_DELAY_MAX}s",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "phones_cmd")
async def callback_phones_cmd(callback: CallbackQuery):
    """Raqamlar ro'yxatiga o'tish"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    await cmd_phones(callback.message)

@dp.callback_query(F.data == "start_monitor")
async def callback_start_monitor(callback: CallbackQuery):
    global is_monitoring
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    if is_monitoring:
        await callback.message.answer("⚠️ Monitoring ishlayapti")
        return
    
    if account_manager.get_stats()['active'] == 0:
        await callback.message.answer("❌ Akkauntlar yo\u0027q")
        return
    
    await account_manager.select_monitor()
    
    if not account_manager.monitor_phone:
        await callback.message.answer("❌ Monitor tanlanmadi")
        return
    
    account_manager.monitor_task = asyncio.create_task(account_manager.run_monitor())
    account_manager.processor_task = asyncio.create_task(account_manager.process_tasks())
    
    is_monitoring = True
    
    await callback.message.answer(
        f"🟢 <b>5 AKKAUNT MONITORING</b>\n"
        f"👁 +998{account_manager.monitor_phone[-4:]}\n"
        f"👥 {account_manager.get_stats()['active']}/5\n"
        f"⚡ 1.5-2.5s delay"
    )

@dp.callback_query(F.data == "stop_monitor")
async def callback_stop_monitor(callback: CallbackQuery):
    global is_monitoring
    
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    if not is_monitoring:
        await callback.message.answer("⚠️ Monitoring to\u0027xtatilgan")
        return
    
    is_monitoring = False
    
    if account_manager.monitor_task:
        account_manager.monitor_task.cancel()
    if account_manager.processor_task:
        account_manager.processor_task.cancel()
    
    await callback.message.answer("🔴 <b>MONITORING TO\u0027XTATILDI</b>")

@dp.callback_query(F.data == "reload")
async def callback_reload(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    await callback.message.edit_text("🔄 Akkauntlar tiklanmoqda...")
    count = await account_manager.load_sessions()
    await callback.message.edit_text(f"✅ {count} ta akkaunt tiklandi")

@dp.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    stats = account_manager.get_stats()
    
    text = f"📊 <b>STATISTIKA</b>\n\n"
    text += f"⏰ {stats['uptime']}\n"
    text += f"👥 {stats['active']}/{MAX_ACCOUNTS}\n"
    text += f"⏳ FloodWait: {stats['flood']}\n"
    text += f"📥 Navbat: {stats['queue']}\n"
    text += f"✅ Cache: {len(account_manager.task_queue.processed_tasks)}"
    
    await callback.message.answer(text)

@dp.callback_query(F.data == "list_accounts")
async def callback_list_accounts(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    await callback.answer()
    
    if not account_manager.active_clients:
        await callback.message.answer("❌ Akkauntlar yo\u0027q")
        return
    
    text = f"📋 <b>5 AKKAUNT</b>\n\n"
    for i, phone in enumerate(list(account_manager.active_clients.keys())[:5], 1):
        status = "🟢" if account_manager.is_available(phone) else "⏳"
        tasks = account_manager.account_tasks.get(phone, 0)
        text += f"{i}. {status} <code>{phone[-4:]}</code> | {tasks} task\n"
    
    await callback.message.answer(text)

@dp.callback_query(F.data == "add_account")
async def callback_add_account(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Ruxsat yo\u0027q")
        return
    
    if len(account_manager.active_clients) >= MAX_ACCOUNTS:
        await callback.answer(f"❌ Maksimal {MAX_ACCOUNTS} ta akkaunt")
        return
    
    await callback.answer()
    await callback.message.answer("📞 <b>Telefon raqam:</b>\n+998901234567")
    await state.set_state(LoginStates.waiting_phone)

@dp.message(Command("cancel"))
async def cmd_cancel(message: AiogramMessage, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.reply("❌ Bekor qilindi")

@dp.message(LoginStates.waiting_phone)
async def process_phone(message: AiogramMessage, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    phone = format_phone(message.text.strip())
    if not re.match(r'^\+998\d{9}$', phone):
        await message.reply("❌ Noto\u0027g\u0027ri format. +998901234567")
        return
    
    msg = await message.reply("⏳ Kod yuborilmoqda...")
    result = await account_manager.start_login(phone)
    
    if result["status"] == "code_sent":
        await state.update_data(phone=phone)
        await msg.edit_text("📨 5 xonali kodni kiriting:")
        await state.set_state(LoginStates.waiting_code)
    elif result["status"] == "already_logged":
        await msg.edit_text(f"✅ +998{phone[-4:]} ulangan")
        await state.clear()
    else:
        await msg.edit_text(f"❌ Xatolik")
        await state.clear()

@dp.message(LoginStates.waiting_code)
async def process_code(message: AiogramMessage, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    code = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    
    msg = await message.reply("⏳ Kod tekshirilmoqda...")
    result = await account_manager.verify_code(phone, code)
    
    if result["status"] == "success":
        await msg.edit_text(f"✅ +998{phone[-4:]} qo\u0027shildi")
        await state.clear()
    elif result["status"] == "password_needed":
        await msg.edit_text("🔐 Parol:")
        await state.set_state(LoginStates.waiting_password)
    else:
        await msg.edit_text(f"❌ Xatolik")
        await state.clear()

@dp.message(LoginStates.waiting_password)
async def process_password(message: AiogramMessage, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    password = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    
    msg = await message.reply("⏳ Parol tekshirilmoqda...")
    result = await account_manager.verify_password(phone, password)
    
    if result["status"] == "success":
        await msg.edit_text(f"✅ +998{phone[-4:]} qo\u0027shildi")
    else:
        await msg.edit_text(f"❌ Xatolik")
    
    await state.clear()

# ==================== STARTUP ====================
async def on_startup():
    count = await account_manager.load_sessions()
    logger.info(f"🚀 Bot ishga tushdi. Akkauntlar: {count}")
    
    await bot.send_message(
        ADMIN_ID,
        f"🤖 <b>5 AKKAUNT - RAQAM BOSHQARISH</b>\n\n"
        f"✅ {count}/5 akkaunt yuklandi\n"
        f"👁 {MONITOR_CHANNEL}\n"
        f"📱 /phones - raqamlarni boshqarish\n"
        f"⚡ 1.5-2.5s delay\n"
        f"💤 Har 10 taskda 15s dam"
    )

async def on_shutdown():
    global is_monitoring
    is_monitoring = False
    await account_manager.stop_all()
    await bot.session.close()

async def main():
    await on_startup()
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())