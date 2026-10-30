import requests

class FedExRestRequest:
    def __init__(self, api_key, secret_key, account_number, use_sandbox=True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.account_number = account_number
        self.base_url = "https://apis-sandbox.fedex.com" if use_sandbox else "https://apis.fedex.com"

    def get_access_token(self):
        url = f"{self.base_url}/oauth/token"
        payload = {
            'grant_type': 'client_credentials',
            'client_id': self.api_key,
            'client_secret': self.secret_key
        }
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        response = requests.post(url, data=payload, headers=headers)
        
        if response.status_code == 200:
            return response.json().get('access_token')
        return False
