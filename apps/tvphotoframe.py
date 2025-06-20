# apps/tvphotoframe.py
print("🧪 TVPHOTOFRAME.PY ЗАГРУЖАЕТСЯ!")

import appdaemon.plugins.hass.hassapi as hass
import os
import random
import time
from datetime import datetime, timedelta

class TvPhotoFrameManager(hass.Hass):
    
    def initialize(self):
        """Инициализация приложения фоторамки"""
        
        # Основные параметры
        self.tv_entity = self.args.get("tv_entity", "media_player.lg_webos_tv_ur80006lj_2")
        self.photo_folder = self.args.get("photo_folder", "/media/nas/photos/")
        self.supported_formats = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
        
        # Состояние приложения
        self.tvphotoframe_active = False
        self.photo_list = []
        self.current_photo_index = 0
        self.tvphotoframe_timer = None
        self.last_activity_time = datetime.now()
        
        # Загрузка списка фотографий
        self.load_photo_list()
        
        # Отслеживание изменений состояния TV
        self.listen_state(self.tv_state_changed, self.tv_entity)
        self.listen_state(self.tv_attributes_changed, self.tv_entity, attribute="all")
        
        # Отслеживание изменений настроек
        self.listen_state(self.tvphotoframe_toggle_changed, "input_boolean.tvphotoframe_active")
        self.listen_state(self.folder_path_changed, "input_text.tvphotoframe_folder")
        
        # Таймер проверки неактивности
        self.run_every(self.check_tv_inactivity, "now", 60)  # проверка каждую минуту
        
        # Регистрация сервиса для голосового управления
        self.register_service("tvphotoframe/toggle", self.toggle_tvphotoframe_service)
        
        self.log("TvPhotoFrameManager инициализирован")
    
    def load_photo_list(self):
        """Загрузка списка фотографий из папки"""
        # ВСЕГДА читаем путь из UI (input_text.tvphotoframe_folder)
        folder_path = self.get_state("input_text.tvphotoframe_folder")
        
        # Если в UI пусто - используем fallback из конфигурации
        if not folder_path or folder_path == "unknown":
            folder_path = self.photo_folder
            self.log(f"UI путь пустой, используем fallback: {folder_path}")
        else:
            self.log(f"Используем путь из UI: {folder_path}")
            
        try:
            if os.path.exists(folder_path):
                self.photo_list = []
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in self.supported_formats):
                            full_path = os.path.join(root, file)
                            self.photo_list.append(full_path)
                
                random.shuffle(self.photo_list)
                self.log(f"Загружено {len(self.photo_list)} фотографий из {folder_path}")
            else:
                self.log(f"Папка {folder_path} не найдена", level="WARNING")
                self.photo_list = []
        except Exception as e:
            self.log(f"Ошибка загрузки фотографий: {e}", level="ERROR")
            self.photo_list = []
    
    def tv_state_changed(self, entity, attribute, old, new, kwargs):
        """Обработка изменения состояния TV"""
        self.log(f"TV состояние: {old} -> {new}")
        
        if new in ['playing', 'on']:
            self.last_activity_time = datetime.now()
            if self.tvphotoframe_active:
                self.stop_tvphotoframe("TV активен")
        elif new == 'off':
            if self.tvphotoframe_active:
                self.stop_tvphotoframe("TV выключен")
    
    def tv_attributes_changed(self, entity, attribute, old, new, kwargs):
        """Обработка изменения атрибутов TV (обнаружение нажатий пульта)"""
        if new != old and self.tvphotoframe_active:
            # Любое изменение атрибутов считаем активностью пользователя
            self.last_activity_time = datetime.now()
            self.stop_tvphotoframe("Обнаружена активность пульта")
    
    def tvphotoframe_toggle_changed(self, entity, attribute, old, new, kwargs):
        """Обработка переключения фоторамки через интерфейс"""
        if new == "on" and not self.tvphotoframe_active:
            self.start_tvphotoframe("Запуск через интерфейс")
        elif new == "off" and self.tvphotoframe_active:
            self.stop_tvphotoframe("Остановка через интерфейс")
    
    def folder_path_changed(self, entity, attribute, old, new, kwargs):
        """Обработка изменения пути к папке с фото"""
        if new != old:
            self.log(f"Изменен путь к папке: {old} -> {new}")
            self.load_photo_list()
    
    def check_tv_inactivity(self, kwargs):
        """Проверка неактивности TV"""
        if self.tvphotoframe_active:
            return
            
        tv_state = self.get_state(self.tv_entity)
        tvphotoframe_enabled = self.get_state("input_boolean.tvphotoframe_enabled")
        timeout_minutes = float(self.get_state("input_number.tv_inactive_timeout"))
        
        if (tv_state == "on" and 
            tvphotoframe_enabled == "on" and 
            not self.tvphotoframe_active):
            
            inactive_time = datetime.now() - self.last_activity_time
            if inactive_time.total_seconds() > (timeout_minutes * 60):
                self.start_tvphotoframe("Неактивность TV")
    
    def start_tvphotoframe(self, reason=""):
        """Запуск фоторамки"""
        if self.tvphotoframe_active:
            return
            
        if not self.photo_list:
            self.log("Нет фотографий для показа", level="WARNING")
            return
            
        tv_state = self.get_state(self.tv_entity)
        if tv_state != "on":
            self.log("TV не включен, фоторамка не запущена", level="WARNING")
            return
        
        self.tvphotoframe_active = True
        self.current_photo_index = 0
        random.shuffle(self.photo_list)  # Перемешиваем при каждом запуске
        
        # Устанавливаем состояние в HA
        self.set_state("input_boolean.tvphotoframe_active", state="on")
        
        # Показываем первое фото
        self.show_next_photo()
        
        self.log(f"Фоторамка запущена. Причина: {reason}")
        
        # Отправляем уведомление
        self.call_service("notify/persistent_notification", 
                         message=f"Фоторамка запущена ({len(self.photo_list)} фото)",
                         title="TV Фоторамка")
    
    def stop_tvphotoframe(self, reason=""):
        """Остановка фоторамки"""
        if not self.tvphotoframe_active:
            return
            
        self.tvphotoframe_active = False
        
        # Отменяем таймер
        if self.tvphotoframe_timer:
            self.cancel_timer(self.tvphotoframe_timer)
            self.tvphotoframe_timer = None
        
        # Устанавливаем состояние в HA
        self.set_state("input_boolean.tvphotoframe_active", state="off")
        
        # Останавливаем воспроизведение на TV
        self.call_service("media_player/media_stop", entity_id=self.tv_entity)
        
        self.log(f"Фоторамка остановлена. Причина: {reason}")
        
        # Отправляем уведомление
        self.call_service("notify/persistent_notification", 
                         message=f"Фоторамка остановлена. Причина: {reason}",
                         title="TV Фоторамка")
    
    def show_next_photo(self):
        """Показ следующей фотографии"""
        if not self.tvphotoframe_active or not self.photo_list:
            return
            
        # Получаем текущее фото
        photo_path = self.photo_list[self.current_photo_index]
        
        try:
            # Отправляем фото на TV
            self.call_service("media_player/play_media",
                            entity_id=self.tv_entity,
                            media_content_type="image/jpeg",
                            media_content_id=photo_path)
            
            self.log(f"Показ фото {self.current_photo_index + 1}/{len(self.photo_list)}: {os.path.basename(photo_path)}")
            
            # Переходим к следующему фото
            self.current_photo_index = (self.current_photo_index + 1) % len(self.photo_list)
            
            # Если прошли все фото, перемешиваем снова
            if self.current_photo_index == 0:
                random.shuffle(self.photo_list)
                self.log("Список фотографий перемешан")
            
            # Планируем показ следующего фото
            interval = int(float(self.get_state("input_number.tvphotoframe_interval")))
            self.tvphotoframe_timer = self.run_in(self.show_next_photo_callback, interval)
            
        except Exception as e:
            self.log(f"Ошибка показа фото {photo_path}: {e}", level="ERROR")
            # Пробуем следующее фото через 2 секунды
            self.tvphotoframe_timer = self.run_in(self.show_next_photo_callback, 2)
    
    def show_next_photo_callback(self, kwargs):
        """Callback для таймера показа следующего фото"""
        self.tvphotoframe_timer = None
        self.show_next_photo()
    
    def toggle_tvphotoframe_service(self, kwargs):
        """Сервис для переключения фоторамки (для голосового управления)"""
        if self.tvphotoframe_active:
            self.stop_tvphotoframe("Голосовая команда")
        else:
            self.start_tvphotoframe("Голосовая команда")
        
        return {"status": "toggled", "active": self.tvphotoframe_active}
    
    def terminate(self):
        """Завершение работы приложения"""
        if self.tvphotoframe_active:
            self.stop_tvphotoframe("Завершение приложения")
        self.log("TvPhotoFrameManager завершен")