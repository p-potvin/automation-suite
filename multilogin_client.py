import os
import requests
import yaml
import logging

os.makedirs('logs', exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


class MultiLoginClient:
    def __init__(self, config_path: str = 'config/settings.yaml'):
        self.base_url = os.getenv('MULTILOGIN_API_URL', '')
        self.api_key = os.getenv('MULTILOGIN_API_KEY', '')
        self.profile_name = os.getenv('MULTILOGIN_PROFILE_NAME', 'automation_profile')
        self.os_type = os.getenv('MULTILOGIN_OS_TYPE', 'Windows 10')
        self.browser = os.getenv('MULTILOGIN_BROWSER', 'Chrome')

        if not self.base_url and os.path.exists(config_path):
            with open(config_path, 'r') as file:
                config = yaml.safe_load(file)
            ml = config.get('multilogin', {})
            self.base_url = self.base_url or ml.get('base_url', '')
            self.api_key = self.api_key or ml.get('api_key', '')
            self.profile_name = self.profile_name or ml.get('profile_name', 'automation_profile')
            self.os_type = self.os_type or ml.get('os_type', 'Windows 10')
            self.browser = self.browser or ml.get('browser', 'Chrome')

        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    def create_profile(self):
        """Creates a new browser profile."""
        payload = {
            "name": self.profile_name,
            "os": self.os_type,
            "browser": self.browser,
            "resolution": {"width": 1920, "height": 1080}
        }
        response = requests.post(f"{self.base_url}/profiles", json=payload, headers=self.headers, timeout=30)
        if response.status_code == 200:
            profile = response.json()
            log.info(f"Profile Created: {profile['id']}")
            return profile['id']
        else:
            log.error(f"Profile Creation Failed: {response.text}")
            return None

    def launch_browser(self, profile_id):
        """Launches a browser session for the profile."""
        url = f"{self.base_url}/profiles/{profile_id}/browser"
        response = requests.post(url, headers=self.headers, timeout=30)
        if response.status_code == 200:
            browser = response.json()
            log.info(f"Browser Launched: {browser['id']}, URL: {browser['url']}")
            return browser['id'], browser['url']
        else:
            log.error(f"Browser Launch Failed: {response.text}")
            return None, None

    def get_cookies(self, browser_id):
        """Extracts cookies from the running browser."""
        url = f"{self.base_url}/browser/{browser_id}/cookies"
        response = requests.get(url, headers=self.headers, timeout=30)
        if response.status_code == 200:
            cookies = response.json()
            log.info(f"Cookies Extracted: {len(cookies)}")
            return cookies
        else:
            log.error(f"Cookie Extraction Failed: {response.text}")
            return []

    def close_session(self, profile_id):
        """Closes the browser session."""
        url = f"{self.base_url}/profiles/{profile_id}/browser/close"
        requests.post(url, headers=self.headers, timeout=30)
        log.info(f"Session Closed: {profile_id}")
