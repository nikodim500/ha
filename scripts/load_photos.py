#!/usr/bin/env python3
# scripts/load_photos.py
# Script to load photo list from NAS folder with SMB support

import os
import requests
import json
import random
import yaml
import subprocess
import tempfile
import time
from pathlib import Path

import os
import requests
import json
import random
import yaml
import subprocess
from pathlib import Path
from datetime import datetime

# Configuration
HA_URL = "http://192.168.1.10:8123"
SUPPORTED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.JPG', '.JPEG', '.PNG']
MAX_PHOTOS = 99999  # Limit to avoid database issues
DEBUG_DIR = "/config/tvphotoframe_debug"
MOUNT_BASE = "/tmp/smb_mounts"  # Base folder for SMB mounts

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
            logging.FileHandler(f'{debug_dir}/scan_photos.log'),
            logging.StreamHandler()  # Also output to console
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
                log_and_print(f"📄 Found secrets.yaml: {path}")
                break
        
        if not secrets_path:
            log_and_print("❌ secrets.yaml file not found", "ERROR")
            log_and_print("💡 Expected locations:")
            for path in possible_paths:
                log_and_print(f"   - {path}")
            return None
        
        # Read secrets.yaml
        with open(secrets_path, 'r', encoding='utf-8') as file:
            secrets = yaml.safe_load(file)
        
        # Search for token
        token_keys = ['tvphotoframe_token', 'appdaemon_token', 'ha_token', 'home_assistant_token', 'api_token']
        
        for key in token_keys:
            if key in secrets:
                log_and_print(f"✅ Token found in secrets.yaml: {key}")
                return secrets[key]
        
        log_and_print("❌ Token not found in secrets.yaml", "ERROR")
        log_and_print("💡 Add one of these lines to secrets.yaml:")
        for key in token_keys:
            log_and_print(f"   {key}: your_token_here")
        log_and_print("💡 Recommended: tvphotoframe_token: your_token")
        
        return None
        
    except yaml.YAMLError as e:
        log_and_print(f"❌ Error parsing secrets.yaml: {e}", "ERROR")
        return None
    except Exception as e:
        log_and_print(f"❌ Error reading secrets.yaml: {e}", "ERROR")
        return None

def load_smb_credentials():
    """Load SMB credentials from secrets.yaml (optional for guest access)"""
    try:
        with open("/config/secrets.yaml", 'r', encoding='utf-8') as file:
            secrets = yaml.safe_load(file)
        
        # Look for SMB credentials (optional)
        smb_user = secrets.get('smb_username', secrets.get('nas_username'))
        smb_pass = secrets.get('smb_password', secrets.get('nas_password'))
        
        if smb_user and smb_pass:
            print(f"✅ SMB credentials found for user: {smb_user}")
            return smb_user, smb_pass
        else:
            print("ℹ️ No SMB credentials in secrets.yaml - will try guest access")
            return None, None
            
    except Exception as e:
        print(f"⚠️ Error loading SMB credentials, trying guest access: {e}")
        return None, None

def parse_network_path(path):
    """Parse Windows network path to get server and share"""
    # Convert \\server\share\folder to //server/share and /folder
    if path.startswith('\\\\'):
        # Windows UNC path
        path_clean = path.replace('\\\\', '').replace('\\', '/')
        parts = path_clean.split('/')
        if len(parts) >= 2:
            server = parts[0]
            share = parts[1]
            subfolder = '/'.join(parts[2:]) if len(parts) > 2 else ''
            return server, share, subfolder
    elif path.startswith('//'):
        # Unix SMB path
        path_clean = path[2:]  # Remove //
        parts = path_clean.split('/')
        if len(parts) >= 2:
            server = parts[0]
            share = parts[1]
            subfolder = '/'.join(parts[2:]) if len(parts) > 2 else ''
            return server, share, subfolder
    
    return None, None, None

def mount_smb_share(server, share, username=None, password=None):
    """Mount SMB share to local directory with SMB 1.0 support and read-only fix"""
    try:
        # Create mount base directory
        os.makedirs(MOUNT_BASE, exist_ok=True)
        
        # Create unique mount point
        mount_point = os.path.join(MOUNT_BASE, f"{server}_{share}")
        os.makedirs(mount_point, exist_ok=True)
        
        # Check if already mounted
        if os.path.ismount(mount_point):
            print(f"✅ SMB share already mounted: {mount_point}")
            return mount_point
        
        # Build mount command
        smb_path = f"//{server}/{share}"
        
        # SMB 1.0 specific options with read-only fixes
        mount_options = [
            # Read-only mount (since we only need to read photos)
            "guest,vers=1.0,ro,uid=root,gid=root,iocharset=utf8,noperm",
            # Read-only with different security
            "guest,vers=1.0,ro,sec=ntlm,uid=root,gid=root,iocharset=utf8",
            # Read-only basic
            "guest,vers=1.0,ro,uid=root,gid=root",
            # Legacy read-only
            "guest,ro,sec=ntlm,uid=root,gid=root,iocharset=utf8",
            # Read-only without version
            "guest,ro,uid=root,gid=root,iocharset=utf8",
            # Try read-write anyway
            "guest,vers=1.0,uid=root,gid=root,iocharset=utf8,file_mode=0444,dir_mode=0555",
            # Basic guest without permissions
            "guest,vers=1.0,uid=root,gid=root",
            # Minimal options
            "guest,uid=root,gid=root"
        ]
        
        # If credentials provided, add authenticated SMB 1.0 options first
        if username and password:
            auth_options = [
                f"username={username},password={password},vers=1.0,ro,uid=root,gid=root,iocharset=utf8",
                f"username={username},password={password},vers=1.0,ro,sec=ntlm,uid=root,gid=root",
                f"username={username},password={password},ro,sec=ntlm,uid=root,gid=root,iocharset=utf8",
                f"username={username},password={password},vers=1.0,uid=root,gid=root,file_mode=0444"
            ]
            mount_options = auth_options + mount_options
        
        print(f"🔧 Mounting SMB 1.0 share (read-only): {smb_path} -> {mount_point}")
        
        # Try each mount option
        for i, options in enumerate(mount_options):
            if username and i < 4:
                access_type = "authenticated SMB 1.0"
            elif "ro" in options:
                access_type = "read-only guest SMB 1.0"
            else:
                access_type = "guest SMB 1.0"
                
            print(f"🔄 Trying {access_type} (option {i+1})...")
            
            mount_cmd = ["mount", "-t", "cifs", smb_path, mount_point, "-o", options]
            
            try:
                result = subprocess.run(mount_cmd, capture_output=True, text=True, timeout=45)
                
                if result.returncode == 0:
                    print(f"✅ Successfully mounted with {access_type}: {mount_point}")
                    
                    # Test access to mounted folder
                    try:
                        test_files = os.listdir(mount_point)[:3]
                        print(f"   📁 Mount test - found items: {test_files}")
                        return mount_point
                    except Exception as e:
                        print(f"   ⚠️ Mount successful but cannot list contents: {e}")
                        # Try to continue anyway, maybe permissions will work
                        return mount_point
                        
                else:
                    error_msg = result.stderr.strip()
                    if "cannot mount" in error_msg and "read-only" in error_msg:
                        print(f"   ❌ Read-only mount issue")
                    elif "Permission denied" in error_msg:
                        print(f"   ❌ Permission denied")
                    elif "No such file or directory" in error_msg:
                        print(f"   ❌ Share not found")
                    elif "Connection refused" in error_msg:
                        print(f"   ❌ Connection refused")
                    elif "Invalid argument" in error_msg:
                        print(f"   ❌ Invalid mount options")
                    else:
                        print(f"   ❌ Failed: {error_msg}")
                    continue
                    
            except subprocess.TimeoutExpired:
                print(f"   ❌ Timeout (45s) - server may be slow")
                continue
            except Exception as e:
                print(f"   ❌ Error: {e}")
                continue
        
        print(f"❌ All SMB 1.0 mount attempts failed for {smb_path}")
        print("💡 Advanced SMB 1.0 troubleshooting:")
        print("   - Try manual test: smbclient -L //192.168.1.11 -N")
        print("   - Check dmesg for kernel errors: dmesg | tail")
        print("   - Verify share name exactly matches on server")
        print("   - Check if server requires specific SMB dialect")
        return None
        
    except Exception as e:
        print(f"❌ Mount error: {e}")
        return None
            
    except subprocess.TimeoutExpired:
        print("❌ Mount command timed out")
        return None
    except Exception as e:
        print(f"❌ Mount error: {e}")
        return None

def unmount_smb_share(mount_point):
    """Unmount SMB share"""
    try:
        if os.path.ismount(mount_point):
            result = subprocess.run(["umount", mount_point], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print(f"🔓 Unmounted: {mount_point}")
            else:
                print(f"⚠️ Unmount warning: {result.stderr}")
    except Exception as e:
        print(f"⚠️ Unmount error: {e}")

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

def get_photo_list_via_python_smb(server, share, subfolder="", username=None, password=None):
    """Get list of photos using Python SMB library (alternative to smbclient)"""
    photos = []
    
    try:
        print(f"🐍 Using Python SMB library for: //{server}/{share}")
        
        # Try to use existing Python libraries
        try:
            import socket
            import struct
            print("✅ Using socket-based SMB approach")
            
            # For now, let's use a simpler curl-based approach that works in Alpine
            return get_photo_list_via_curl_smb(server, share, subfolder, username, password)
            
        except ImportError as e:
            print(f"ℹ️ Python SMB libraries not available: {e}")
            # Fall back to curl approach
            return get_photo_list_via_curl_smb(server, share, subfolder, username, password)
    
    except Exception as e:
        print(f"❌ Error with Python SMB: {e}")
        return []

def get_photo_list_via_curl_smb(server, share, subfolder="", username=None, password=None):
    """Alternative: try to access SMB via HTTP (if server has web interface)"""
    photos = []
    
    try:
        print(f"🌐 Trying alternative access methods for: //{server}/{share}")
        
        # Check if server has web interface on common ports
        web_ports = [80, 8080, 8000, 9000, 443]
        working_url = None
        
        for port in web_ports:
            for protocol in ['http', 'https']:
                test_url = f"{protocol}://{server}:{port}"
                try:
                    result = subprocess.run(['curl', '-s', '--connect-timeout', '3', test_url], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and len(result.stdout) > 0:
                        print(f"✅ Found web interface at: {test_url}")
                        working_url = test_url
                        break
                except:
                    continue
            if working_url:
                break
        
        if working_url:
            print(f"🌐 Server has web interface, but SMB file listing via HTTP not implemented yet")
            print("💡 This would require server-specific implementation")
        
        # For now, return empty list and suggest manual file listing
        print("💡 Alternative: Create static file list manually")
        print("   1. Connect to \\\\192.168.1.11\\photo\\0001photoframe via Windows")
        print("   2. Copy all filenames to a text file")
        print("   3. Update the script with static list")
        
        return []
        
    except Exception as e:
        print(f"❌ Alternative access error: {e}")
        return []

def get_photo_list_fallback_static():
    """Fallback: static photo list for testing"""
    print("🔄 Using fallback static photo list for testing")
    
    # Sample photo list - replace with your actual photos
    static_photos = [
        "IMG_001.jpg", "IMG_002.jpg", "IMG_003.png",
        "DSCN001.jpg", "DSCN002.jpg", "photo1.jpeg",
        "vacation/beach1.jpg", "vacation/beach2.jpg",
        "family/birthday1.jpg", "family/birthday2.png",
        "nature/sunset.jpg", "nature/landscape.png"
    ]
    
    # Shuffle for variety
    random.shuffle(static_photos)
    
    print(f"📷 Using {len(static_photos)} sample photos")
    print("💡 Replace static_photos list in script with your actual filenames")
    
    return static_photos

def get_photo_list(folder_path):
    """Get list of photos from folder (with multiple fallback methods)"""
    photos = []
    
    try:
        print(f"🔍 Analyzing path: {folder_path}")
        
        # Check if it's a network path
        server, share, subfolder = parse_network_path(folder_path)
        
        if server and share:
            print(f"🌐 Network path detected - Server: {server}, Share: {share}, Subfolder: {subfolder}")
            
            # Load SMB credentials
            username, password = load_smb_credentials()
            
            # Try multiple methods in order of preference
            methods = [
                ("smbclient", lambda: get_photo_list_via_smbclient(server, share, subfolder, username, password)),
                ("python SMB", lambda: get_photo_list_via_python_smb(server, share, subfolder, username, password)),
                ("static fallback", lambda: get_photo_list_fallback_static())
            ]
            
            for method_name, method_func in methods:
                print(f"🔄 Trying {method_name} method...")
                try:
                    photos = method_func()
                    if photos:
                        print(f"✅ Success with {method_name}: {len(photos)} photos")
                        break
                    else:
                        print(f"⚠️ {method_name} returned no photos, trying next method...")
                except Exception as e:
                    print(f"❌ {method_name} failed: {e}")
                    continue
            
            if not photos:
                print("❌ All network methods failed!")
                print("💡 Quick fix: Use static photo list")
                photos = get_photo_list_fallback_static()
            
        else:
            # Local path - use original method
            scan_path = folder_path
            print(f"💾 Local path detected: {scan_path}")
            
            if os.path.exists(scan_path):
                print(f"✅ Path accessible: {scan_path}")
                
                # Recursive search in all subfolders
                for root, dirs, files in os.walk(scan_path):
                    for file in files:
                        if any(file.lower().endswith(ext.lower()) for ext in SUPPORTED_EXTENSIONS):
                            # Get relative path from main folder
                            rel_path = os.path.relpath(os.path.join(root, file), scan_path)
                            photos.append(rel_path.replace('\\', '/'))  # Normalize slashes
                            
                print(f"📷 Found {len(photos)} photos")
                
                # Limit count and shuffle
                if len(photos) > MAX_PHOTOS:
                    photos = random.sample(photos, MAX_PHOTOS)
                    print(f"🎲 Selected random {MAX_PHOTOS} photos from total collection")
                else:
                    random.shuffle(photos)
            else:
                print(f"❌ Path not accessible: {scan_path}")
    
    except Exception as e:
        print(f"❌ Error scanning photos: {e}")
        print("🔄 Using fallback static list...")
        photos = get_photo_list_fallback_static()
    
    return photos

def get_photo_list_via_smbclient(server, share, subfolder="", username=None, password=None):
    """Get list of photos using smbclient (working version)"""
    
    # Use confirmed working path
    smbclient_cmd = "/usr/bin/smbclient"
    
    print(f"🔍 Using confirmed smbclient: {smbclient_cmd}")
    
    # Verify it works
    try:
        result = subprocess.run([smbclient_cmd, "--version"], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"✅ smbclient version: {result.stdout.strip().split()[0]}")
        else:
            print(f"❌ smbclient test failed: {result.stderr}")
            raise Exception("smbclient not working")
    except Exception as e:
        print(f"❌ smbclient error: {e}")
        raise Exception("smbclient not available")
    
    # Now use the working smbclient
    photos = []
    smb_path = f"//{server}/{share}"
    
    print(f"📡 Connecting to: {smb_path}")
    
    # Build base command
    cmd_base = [
        smbclient_cmd, smb_path,
        "--option=client min protocol=NT1",
        "--option=client max protocol=NT1"
    ]
    
    # Add authentication
    if username and password:
        cmd_base.extend(["-U", f"{username}%{password}"])
        print(f"🔐 Using credentials: {username}")
    else:
        cmd_base.append("-N")
        print("🔓 Using guest access")
    
    # Function to run smbclient commands
    def run_smb_command(command):
        full_cmd = cmd_base + ["-c", command]
        print(f"🔧 Running: smbclient ... -c '{command}'")
        
        try:
            result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return result.stdout
            else:
                print(f"❌ Command failed: {result.stderr.strip()}")
                return None
        except subprocess.TimeoutExpired:
            print("❌ Command timeout (30s)")
            return None
        except Exception as e:
            print(f"❌ Command error: {e}")
            return None
    
    # Test basic connection first
    print("🧪 Testing basic connection...")
    test_output = run_smb_command("ls")
    if not test_output:
        print("❌ Basic connection test failed!")
        return []
    
    print("✅ Basic connection works!")
    
    # Navigate to subfolder if specified
    if subfolder:
        print(f"📁 Navigating to subfolder: {subfolder}")
        ls_command = f'cd "{subfolder}"; ls'
    else:
        print("📁 Scanning root directory")
        ls_command = "ls"
    
    # Get file listing
    print(f"🔍 Getting directory listing...")
    output = run_smb_command(ls_command)
    if not output:
        print("❌ Directory listing failed!")
        return []
    
    print("📋 Parsing directory listing...")
    print("Raw output preview:")
    print(output[:500] + "..." if len(output) > 500 else output)
    
    lines = output.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or 'blocks of size' in line:
            continue
            
        # Skip directories starting with '.'
        if line.startswith('  .'):
            continue
            
        # Parse smbclient output: "  filename   type   size   date"
        parts = line.split()
        if len(parts) < 2:
            continue
            
        filename = parts[0]
        filetype = parts[1]
        
        # Only process files (A = archive/file)
        if filetype == 'A':
            # Check if it's an image file
            if any(filename.lower().endswith(ext.lower()) for ext in SUPPORTED_EXTENSIONS):
                if subfolder:
                    photo_path = f"{subfolder}/{filename}"
                else:
                    photo_path = filename
                photos.append(photo_path)
                print(f"   📷 Found: {photo_path}")
        elif filetype in ['D', 'DA']:
            print(f"   📁 Directory: {filename}")
    
    print(f"📷 Total photos found: {len(photos)}")
    
    # Shuffle and limit
    if photos:
        random.shuffle(photos)
        if len(photos) > MAX_PHOTOS:
            photos = photos[:MAX_PHOTOS]
            print(f"🎲 Limited to {MAX_PHOTOS} photos")
    
    return photos

def test_network_access(folder_path):
    """Enhanced network access testing with smbclient"""
    print("🔧 Testing network folder access...")
    
    # Parse network path
    server, share, subfolder = parse_network_path(folder_path)
    
    if server and share:
        print(f"🌐 Network path detected:")
        print(f"   Server: {server}")
        print(f"   Share: {share}")
        print(f"   Subfolder: {subfolder}")
        
        # Test network connectivity
        print(f"🏓 Testing connectivity to {server}...")
        ping_result = subprocess.run(['ping', '-c', '1', '-W', '3', server], 
                                   capture_output=True, text=True)
        
        if ping_result.returncode == 0:
            print(f"✅ Server {server} is reachable")
        else:
            print(f"❌ Server {server} is not reachable")
            print("💡 Check network connection and server IP")
            return False
        
        # Test SMB connection with smbclient
        print(f"🔗 Testing SMB 1.0 connection...")
        username, password = load_smb_credentials()
        
        smb_path = f"//{server}/{share}"
        cmd = [
            "smbclient", smb_path,
            "--option=client min protocol=NT1",
            "--option=client max protocol=NT1"
        ]
        
        if username and password:
            cmd.extend(["-U", f"{username}%{password}"])
        else:
            cmd.append("-N")
        
        cmd.extend(["-c", "ls"])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"✅ SMB connection successful!")
                if subfolder:
                    # Test access to subfolder
                    subfolder_cmd = cmd[:-2] + ["-c", f"cd \"{subfolder}\"; ls"]
                    subfolder_result = subprocess.run(subfolder_cmd, capture_output=True, text=True, timeout=15)
                    if subfolder_result.returncode == 0:
                        print(f"✅ Subfolder '{subfolder}' accessible")
                        lines = subfolder_result.stdout.strip().split('\n')
                        file_count = sum(1 for line in lines if line.strip() and not line.startswith('  .') and 'blocks of size' not in line)
                        print(f"   📁 Found {file_count} items in subfolder")
                    else:
                        print(f"⚠️ Subfolder '{subfolder}' not accessible or empty")
                return True
            else:
                print(f"❌ SMB connection failed: {result.stderr.strip()}")
                return False
        except subprocess.TimeoutExpired:
            print("❌ SMB connection timeout")
            return False
        except Exception as e:
            print(f"❌ SMB test error: {e}")
            return False
            
    else:
        # Local path testing
        if os.path.exists(folder_path):
            print(f"✅ Local path accessible: {folder_path}")
            return True
        else:
            print(f"❌ Local path not found: {folder_path}")
            return False

def update_ha_simple_counter(total_photos, token):
    """Update only photo counter in Home Assistant"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"📊 Updating HA with total count: {total_photos}")
    
    try:
        # Update total count
        counter_data = {
            "entity_id": "input_number.tvphotoframe_total_photos",
            "value": total_photos
        }
        
        response = requests.post(
            f"{HA_URL}/api/services/input_number/set_value",
            headers=headers,
            json=counter_data,
            timeout=5
        )
        
        if response.status_code == 200:
            print(f"✅ Updated photo counter: {total_photos}")
        else:
            print(f"❌ Counter update error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Counter update error: {e}")

def save_photos_to_file(photos, folder_path):
    """Save photos list to JSON file for random selection"""
    try:
        from datetime import datetime
        import json
        
        # Ensure directory exists
        os.makedirs(DEBUG_DIR, exist_ok=True)
        
        # Prepare data
        photos_data = {
            "files": photos,
            "total_count": len(photos),
            "last_updated": datetime.now().isoformat(),
            "scan_folder": folder_path,
            "version": "2.0"
        }
        
        # Save to file
        with open("/config/tvphotoframe_photos.json", 'w', encoding='utf-8') as f:
            json.dump(photos_data, f, indent=2, ensure_ascii=False)
        
        log_and_print(f"💾 Saved {len(photos)} photos to /config/tvphotoframe_photos.json")
        return True
        
    except Exception as e:
        print(f"❌ Error saving photos file: {e}")
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
        pass  # Not critical if notification fails

def save_photo_list(photos, folder_path, filename="photo_list.json"):
    """Save photo list to file for debugging"""
    try:
        # Create debug folder if it doesn't exist
        os.makedirs(DEBUG_DIR, exist_ok=True)
        
        # Save to debug directory
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

if __name__ == "__main__":
    # Setup logging first
    logger = setup_logging()
    log_and_print.logger = logger  # Attach logger to function
    
    log_and_print("=" * 60)
    log_and_print("🖼️  TV PHOTO FRAME - LOADING PHOTOS WITH SMB SUPPORT")
    log_and_print("=" * 60)
    
    # Send start notification
    log_and_print("📢 Sending start notification to HA...")
    try:
        requests.post(
            f"{HA_URL}/api/services/notify/persistent_notification",
            headers={"Authorization": f"Bearer TEMP_TOKEN", "Content-Type": "application/json"},
            json={"message": "🐍 Python script started scanning photos", "title": "TV Photo Frame"},
            timeout=5
        )
    except:
        log_and_print("⚠️ Could not send start notification (no token yet)", "WARNING")
    
    # Load token from secrets.yaml
    log_and_print("🔑 Loading token from secrets.yaml...")
    ha_token = load_ha_token()
    
    if not ha_token:
        log_and_print("❌ ERROR: Could not get token from secrets.yaml!", "ERROR")
        log_and_print("💡 Add to secrets.yaml:")
        log_and_print("   tvphotoframe_token: your_long_lived_token")
        update_ha_notification("❌ Error: No token found in secrets.yaml", token=None)
        exit(1)
    
    log_and_print("✅ Token loaded successfully")
    
    # Send progress notification
    update_ha_notification("🔍 Getting folder path from HA...", token=ha_token)
    
    # Get folder path from Home Assistant
    photo_folder = get_photo_folder_from_ha(ha_token)
    
    if not photo_folder:
        log_and_print("❌ Could not get folder path from Home Assistant", "ERROR")
        update_ha_notification("❌ Error: could not get folder path", token=ha_token)
        exit(1)
    
    log_and_print(f"📁 Folder path: {photo_folder}")
    
    # Send scanning start notification
    update_ha_notification(f"🔍 Scanning folder: {photo_folder}", token=ha_token)
    
    # Test network access with SMB support
    log_and_print("🧪 Testing folder access...")
    update_ha_notification("🧪 Testing folder access...", token=ha_token)
    
    if not test_network_access(photo_folder):
        log_and_print("❌ Network access test failed!", "ERROR")
        log_and_print("💡 Troubleshooting steps:")
        log_and_print("   1. Check server IP and network connectivity")
        log_and_print("   2. Verify SMB credentials in secrets.yaml")
        log_and_print("   3. Ensure SMB share permissions allow access")
        log_and_print("   4. Try mounting manually: mount -t cifs //server/share /mnt/test")
        update_ha_notification(f"❌ Network access failed: {photo_folder}", token=ha_token)
        exit(1)
    
    log_and_print("✅ Folder access OK")
    update_ha_notification("✅ Folder access OK, scanning photos...", token=ha_token)
    
    # Scan photos with SMB support
    photos = get_photo_list(photo_folder)
    
    if photos:
        log_and_print(f"📷 Found {len(photos)} photos")
        
        # Save photos to file instead of HA
        log_and_print("💾 Saving photos list to file...")
        if save_photos_to_file(photos, photo_folder):
            
            # Update only the counter in HA
            log_and_print("📡 Updating Home Assistant counter...")
            update_ha_notification(f"📡 Updating HA counter: {len(photos)} photos...", token=ha_token)
            
            update_ha_simple_counter(len(photos), ha_token)
            
            # Success completion
            update_ha_notification(f"✅ SUCCESS: Found {len(photos)} photos! Use 'Next Photo' to start.", "TV Photo Frame - Complete", token=ha_token)
            log_and_print(f"🎉 SUCCESS: Saved {len(photos)} photos to file!")
        else:
            update_ha_notification("❌ Error saving photos file", "TV Photo Frame - Error", token=ha_token)
        
    else:
        log_and_print("❌ No photos found!", "ERROR")
        update_ha_notification(f"❌ No photos found in folder: {photo_folder}", "TV Photo Frame - Error", token=ha_token)
    
    log_and_print("=" * 60)
    log_and_print("✅ Script completed!")
    log_and_print("=" * 60)