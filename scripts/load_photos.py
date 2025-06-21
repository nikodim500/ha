#!/usr/bin/env python3
# scripts/load_photos.py
# Script to load photo list from NAS folder

import os
import requests
import json
import random
import yaml
from pathlib import Path

# Configuration
HA_URL = "http://192.168.1.10:8123"
SUPPORTED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.JPG', '.JPEG', '.PNG']
MAX_PHOTOS = 200  # Limit for large collections
DEBUG_DIR = "/config/tvphotoframe_debug"  # Folder for debug files

def load_ha_token():
    """Load token from secrets.yaml"""
    try:
        # Search for secrets.yaml in different locations
        possible_paths = [
            "/config/secrets.yaml",
            "./secrets.yaml",
            "../secrets.yaml"
        ]
        
        secrets_path = None
        for path in possible_paths:
            if os.path.exists(path):
                secrets_path = path
                print(f"📄 Found secrets.yaml: {path}")
                break
        
        if not secrets_path:
            print("❌ secrets.yaml file not found")
            print("💡 Expected locations:")
            for path in possible_paths:
                print(f"   - {path}")
            return None
        
        # Read secrets.yaml
        with open(secrets_path, 'r', encoding='utf-8') as file:
            secrets = yaml.safe_load(file)
        
        # Search for token
        token_keys = ['tvphotoframe_token', 'appdaemon_token', 'ha_token', 'home_assistant_token', 'api_token']
        
        for key in token_keys:
            if key in secrets:
                print(f"✅ Token found in secrets.yaml: {key}")
                return secrets[key]
        
        print("❌ Token not found in secrets.yaml")
        print("💡 Add one of these lines to secrets.yaml:")
        for key in token_keys:
            print(f"   {key}: your_token_here")
        print("💡 Recommended: tvphotoframe_token: your_token")
        
        return None
        
    except yaml.YAMLError as e:
        print(f"❌ Error parsing secrets.yaml: {e}")
        return None
    except Exception as e:
        print(f"❌ Error reading secrets.yaml: {e}")
        return None

def get_ha_entity_state(entity_id, token):
    """Get entity value from Home Assistant"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            f"{HA_URL}/api/states/{entity_id}",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get('state')
        elif response.status_code == 401:
            print(f"❌ Authorization error: check token")
            return None
        else:
            print(f"❌ Error getting {entity_id}: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Connection error to HA: {e}")
        return None

def get_photo_folder_from_ha(token):
    """Get photo folder path from Home Assistant"""
    print("📡 Getting folder path from Home Assistant...")
    
    folder_path = get_ha_entity_state("input_text.tvphotoframe_folder", token)
    
    if folder_path:
        print(f"📁 Path from HA: {folder_path}")
        return folder_path
    else:
        print("❌ Failed to get path from HA")
        return None

def get_photo_list(folder_path):
    """Get list of photos from folder"""
    photos = []
    try:
        print(f"🔍 Scanning folder: {folder_path}")
        
        if os.path.exists(folder_path):
            # Recursive search in all subfolders
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if any(file.lower().endswith(ext.lower()) for ext in SUPPORTED_EXTENSIONS):
                        # Get relative path from main folder
                        rel_path = os.path.relpath(os.path.join(root, file), folder_path)
                        photos.append(rel_path.replace('\\', '/'))  # Normalize slashes
                        
            print(f"📷 Found {len(photos)} photos")
            
            # Limit count and shuffle
            if len(photos) > MAX_PHOTOS:
                photos = random.sample(photos, MAX_PHOTOS)
                print(f"🎲 Selected random {MAX_PHOTOS} photos from total collection")
            else:
                random.shuffle(photos)
                
        else:
            print(f"❌ Folder {folder_path} not found")
            # Check network folder availability
            parent_dir = os.path.dirname(folder_path)
            if os.path.exists(parent_dir):
                print(f"🔍 Parent folder found: {parent_dir}")
                try:
                    subdirs = [d for d in os.listdir(parent_dir) if os.path.isdir(os.path.join(parent_dir, d))]
                    print(f"📁 Available subfolders: {subdirs[:10]}")  # Show first 10
                except:
                    print("❌ No access to parent folder")
            
    except PermissionError:
        print(f"❌ No access to folder: {folder_path}")
        print("💡 Check network folder access permissions")
    except Exception as e:
        print(f"❌ Folder access error: {e}")
    
    return photos

def update_ha_input_select(photos, token):
    """Update input_select in Home Assistant"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # If no photos found, set placeholder
    if not photos:
        photos = ["No photos found - check path"]
    
    # input_select has option count limit
    if len(photos) > 100:
        photos = photos[:100]  # Take first 100
        print(f"⚠️ Limited to 100 photos for input_select")
    
    data = {
        "entity_id": "input_select.tvphotoframe_photos",
        "options": photos
    }
    
    try:
        response = requests.post(
            f"{HA_URL}/api/services/input_select/set_options",
            headers=headers,
            json=data,
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✅ Updated list in HA: {len(photos)} photos")
            
            # Additionally update total count
            counter_data = {
                "entity_id": "input_number.tvphotoframe_total_photos",
                "value": len(photos)
            }
            
            requests.post(
                f"{HA_URL}/api/services/input_number/set_value",
                headers=headers,
                json=counter_data,
                timeout=5
            )
            
        else:
            print(f"❌ HA update error: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.Timeout:
        print("❌ Connection timeout to Home Assistant")
    except requests.exceptions.ConnectionError:
        print("❌ Connection error to Home Assistant")
        print("💡 Check that HA is available at:", HA_URL)
    except Exception as e:
        print(f"❌ HA update error: {e}")

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
        pass  # Not critical if notification fails

def save_photo_list(photos, folder_path, filename="photo_list.json"):
    """Save photo list to file for debugging"""
    try:
        # Create debug folder if it doesn't exist
        os.makedirs(DEBUG_DIR, exist_ok=True)
        
        # Save to subfolder
        debug_file = os.path.join(DEBUG_DIR, filename)
        
        from datetime import datetime
        with open(debug_file, 'w', encoding='utf-8') as f:
            json.dump({
                "scan_time": datetime.now().isoformat(),
                "total_photos": len(photos),
                "folder_path": folder_path,
                "ha_url": HA_URL,
                "photos_sample": photos[:20],  # First 20 for example
                "all_photos": photos,  # Full list
                "full_count": len(photos)
            }, f, indent=2, ensure_ascii=False)
        print(f"💾 List saved to {debug_file}")
    except Exception as e:
        print(f"❌ Save error: {e}")

def detect_ha_url():
    """Auto-detect Home Assistant URL"""
    # For Raspberry Pi - try local addresses first
    possible_urls = [
        "http://127.0.0.1:8123",  # Local for RPi
        "http://localhost:8123",   # Alternative local
        "http://homeassistant.local:8123",  # mDNS
        "http://supervisor/core",  # If script in Add-on
        # Popular IP addresses in home networks
        "http://192.168.1.100:8123",
        "http://192.168.1.101:8123", 
        "http://192.168.1.10:8123",
        "http://192.168.0.100:8123",
        "http://192.168.0.10:8123",
        "http://10.0.0.100:8123",
    ]
    
    print("🔍 Searching for Home Assistant on Raspberry Pi...")
    
    for url in possible_urls:
        try:
            print(f"   Checking: {url}")
            response = requests.get(f"{url}/api/", timeout=3)
            if response.status_code == 200:
                print(f"✅ Found HA at: {url}")
                return url
        except Exception as e:
            print(f"   ❌ {url} - unavailable")
            continue
    
    print("❌ Could not find available HA URL")
    print("💡 Check your Raspberry Pi IP address:")
    print("   - Run: ip addr show")
    print("   - Or check router for device IP")
    print("   - Then try: http://YOUR_IP:8123")
    
    return None

def test_network_access(folder_path):
    """Check network folder access"""
    print("🔧 Testing network folder access...")
    
    # Check different path variants
    test_paths = [
        folder_path,
        folder_path.replace('\\\\', '//') if '\\\\' in folder_path else folder_path,  # Unix style
        os.path.dirname(folder_path),  # Parent folder
    ]
    
    for path in test_paths:
        try:
            if os.path.exists(path):
                print(f"✅ Accessible: {path}")
                if os.path.isdir(path):
                    items = os.listdir(path)[:5]  # First 5 items
                    print(f"   📁 Contains: {items}")
                return True
            else:
                print(f"❌ Not accessible: {path}")
        except Exception as e:
            print(f"❌ Access error {path}: {e}")
    
    return False

if __name__ == "__main__":
    print("=" * 60)
    print("🖼️  TV PHOTO FRAME - LOADING PHOTOS FROM HOME ASSISTANT")
    print("=" * 60)
    
    # Load token from secrets.yaml
    print("🔑 Loading token from secrets.yaml...")
    ha_token = load_ha_token()
    
    if not ha_token:
        print("❌ ERROR: Could not get token from secrets.yaml!")
        print("💡 Add to secrets.yaml:")
        print("   tvphotoframe_token: your_long_lived_token")
        exit(1)
    
    # Get folder path from Home Assistant
    photo_folder = get_photo_folder_from_ha(ha_token)
    
    if not photo_folder:
        print("❌ Could not get folder path from Home Assistant")
        update_ha_notification("❌ Error: could not get folder path", token=ha_token)
        exit(1)
    
    # Send scanning start notification
    update_ha_notification(f"🔍 Scanning folder: {photo_folder}", token=ha_token)
    
    # Test network access
    if not test_network_access(photo_folder):
        print("❌ No access to network folder!")
        print(f"💡 Check path: {photo_folder}")
        print("💡 Make sure network folder is mounted")
        update_ha_notification(f"❌ No access to folder: {photo_folder}", token=ha_token)
        exit(1)
    
    # Scan photos
    photos = get_photo_list(photo_folder)
    
    if photos:
        # Save for debugging
        save_photo_list(photos, photo_folder)
        
        # Update Home Assistant
        print("📡 Updating Home Assistant...")
        update_ha_input_select(photos, ha_token)
        
        # Success completion
        update_ha_notification(f"✅ Loaded {len(photos)} photos", token=ha_token)
        
    else:
        print("❌ No photos found!")
        update_ha_notification(f"❌ No photos found in folder: {photo_folder}", token=ha_token)
    
    print("=" * 60)
    print("✅ Done!")
    print("=" * 60)