# Cache breaker 3 - Verifying Incremental Scan
import requests
import sqlite3
import json

class PaymentProcessor:
    def process_payment(self, user_id, amount):
        # 1. External API Call - Critical point of failure
        # Problem: No timeout specified. If the bank is down, this will hang indefinitely.
        # Problem: No retry logic. A transient network blip causes failure.
        response = requests.post(f"https://bank-api.com/charge", json={"user": user_id, "amount": amount})
        
        if response.status_code == 200:
            # 2. Database Operation - State consistency
            # Problem: No transaction management. If write fails or process crashes after payment, 
            # we might have charged the user but not recorded it.
            conn = sqlite3.connect("payments.db")
            cursor = conn.cursor()
            
            # Problem: SQL Injection risk (though resilience frame focuses on architecture)
            cursor.execute(f"INSERT INTO transactions VALUES ({user_id}, {amount}, 'SUCCESS')")
            conn.commit()
            
            # Problem: Connection not closed in finally block.
            conn.close()
            return True
            
        return False

    def sync_data(self):
        # 3. Batch Processing - Resource Exhaustion
        # Problem: Loading everything into memory. If file is huge, process crashes (OOM).
        with open("large_transaction_log.json", "r") as f:
            data = json.load(f)
            
        for item in data:
            self.process_payment(item['id'], item['amount'])
