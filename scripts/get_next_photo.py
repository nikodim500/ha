#!/usr/bin/env python3
# scripts/get_next_photo.py
# Script to select random photo from file and update HA sensor

import os
import requests
import json
import random
import yaml
from datetime import datetime

# Configuration
HA_URL = "http://192.168.1.10:8123"
PHOTOS_FILE = "/config/tvphotoframe_photos.json"

def setup_logging():
    """Setup logging to debug directory"""
    import logging
    
    # Create debug directory
    debug_dir = "/config/tvphotoframe_debug"
    os.makedirs(debug_dir, exist_ok=True)
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'{debug_dir}/get_next_photo.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def log_and_print(message, level="INFO"):
    """Print and log message"""
    print(message)
    try:
        if hasattr(log_and_print, 'logger'):
            if level == "ERROR":
                log_and_print.logger.error(message)
            elif level == "WARNING":
                log_and_print.logger.warning(message)
            else:
                log_and_print.logger.info(message)
    except:
        pass  # If logger not available, just print

def load_ha_token():
    """Load token from secrets.yaml"""
    try:
        with open("/config/secrets.yaml", 'r', encoding='utf-8') as file:
            secrets = yaml.safe_load(file)
        
        token_keys = ['tvphotoframe_token', 'appdaemon_token', 'ha_token', 'home_assistant_token', 'api_token']
        
        for key in token_keys:
            if key in secrets:
                return secrets[key]
        
        return None
        
    except Exception as e:
        log_and_print(f"❌ Error reading secrets.yaml: {e}", "ERROR")
        return None

def load_photos_from_file():
    """Load photos list from JSON file"""
    try:
        if not os.path.exists(PHOTOS_FILE):
            log_and_print(f"❌ Photos file not found: {PHOTOS_FILE}", "ERROR")
            log_and_print("💡 Run photo scan first!")
            return None
        
        with open(PHOTOS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        photos = data.get('files', [])
        folder = data.get('scan_folder', '/media/photo/0001photoframe')
        
        if not photos:
            log_and_print("❌ No photos found in file", "ERROR")
            return None
        
        log_and_print(f"📂 Loaded {len(photos)} photos from file")
        return photos, folder
        
    except Exception as e:
        log_and_print(f"❌ Error reading photos file: {e}", "ERROR")
        return None

def select_random_photo(photos, folder):
    """Select random photo and create full path"""
    try:
        # Select random photo
        random_photo = random.choice(photos)
        
        # Create full path
        if '/' in random_photo:
            full_path = f"{folder}/{random_photo}"
        else:
            full_path = f"{folder}/{random_photo}"
        
        log_and_print(f"🎲 Selected random photo: {random_photo}")
        log_and_print(f"📍 Full path: {full_path}")
        
        return full_path, random_photo
        
    except Exception as e:
        log_and_print(f"❌ Error selecting photo: {e}", "ERROR")
        return None, None

def update_ha_sensor(photo_path, photo_file, total_photos, token):
    """Update random photo path sensor in HA"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Update sensor with new photo path
        data = {
            "state": photo_path,
            "attributes": {
                "photo_file": photo_file,
                "total_photos": total_photos,
                "last_updated": datetime.now().isoformat(),
                "status": "ready"
            }
        }
        
        response = requests.post(
            f"{HA_URL}/api/states/sensor.random_photo_path",
            headers=headers,
            json=data,
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            log_and_print(f"✅ Updated HA sensor: {photo_file}")
            return True
        else:
            log_and_print(f"❌ HA sensor update error: {response.status_code}", "ERROR")
            return False
            
    except Exception as e:
        log_and_print(f"❌ HA sensor update error: {e}", "ERROR")
        return False

def update_ha_notification(message, title="TV Photo Frame", token=None):
    """Send notification to Home Assistant"""
    if not token:
        return
        
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    data = {
        "message": message,
        "title": title
    }
    
    try:
        requests.post(
            f"{HA_URL}/api/services/notify/persistent_notification",
            headers=headers,
            json=data,
            timeout=5
        )
    except:
        pass

if __name__ == "__main__":
    # Setup logging first
    logger = setup_logging()
    log_and_print.logger = logger  # Attach logger to function
    
    log_and_print("=" * 50)
    log_and_print("🎲 TV PHOTO FRAME - GET RANDOM PHOTO")
    log_and_print("=" * 50)
    
    # Load token
    log_and_print("🔑 Loading token...")
    ha_token = load_ha_token()
    
    if not ha_token:
        log_and_print("❌ Could not get token from secrets.yaml!", "ERROR")
        exit(1)
    
    # Load photos from file
    log_and_print("📂 Loading photos from file...")
    result = load_photos_from_file()
    
    if not result:
        update_ha_notification("❌ No photos file found. Run scan first!", token=ha_token)
        exit(1)
    
    photos, folder = result
    
    # Select random photo
    log_and_print("🎲 Selecting random photo...")
    photo_path, photo_file = select_random_photo(photos, folder)
    
    if not photo_path:
        update_ha_notification("❌ Error selecting random photo", token=ha_token)
        exit(1)
    
    # Update HA sensor
    log_and_print("📡 Updating Home Assistant...")
    if update_ha_sensor(photo_path, photo_file, len(photos), ha_token):
        log_and_print("🎉 SUCCESS: Random photo selected!")
    else:
        log_and_print("❌ Failed to update HA sensor", "ERROR")
        exit(1)
    
    log_and_print("=" * 50)
    log_and_print("✅ Done!")
    log_and_print("=" * 50)