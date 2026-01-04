
import requests
import httpx

def fetch_data_unsafely():
    # Trigger 1: requests without timeout
    response = requests.get("https://api.example.com/data")
    
    # Trigger 2: httpx without timeout
    other_response = httpx.post("https://api.example.com/submit", json={"foo": "bar"})
    
    return response.json()
