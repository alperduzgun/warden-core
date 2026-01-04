"""
Resilience Test Case

This file contains code patterns that are syntactically valid but structurally fragile.
It is designed to test the new LLM-based FMEA (Failure Mode & Effects Analysis) capabilities.

# Cache invalidation comment: v3
"""

import sqlite3
import requests
import time

def process_payment(order_id: str, amount: float):
    # CRITICISM EXPECTED: Missing transaction rollback
    conn = sqlite3.connect("payments.db")
    cursor = conn.cursor()
    
    # DB Operation
    cursor.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, "user_1"))
    
    # External Dependency (Single Point of Failure)
    # CRITICISM EXPECTED: No timeout, no circuit breaker, blocking call
    response = requests.post("https://payment-gateway.com/charge", json={"id": order_id})
    
    if response.status_code == 200:
        cursor.execute("UPDATE orders SET status = 'PAID' WHERE id = ?", (order_id,))
        conn.commit()
    else:
        # CRITICISM EXPECTED: Inconsistent State (User balance deducted but order not paid)
        print("Payment failed")
        # conn.close() without commit/rollback leaves potential locks or partial state depending on isolation level
    
    conn.close()

def batch_process(items):
    # CRITICISM EXPECTED: Infinite loop risk if items never empty
    processed = []
    while len(items) > 0:
        item = items[0]
        try:
            # CRITICISM EXPECTED: Empty except block (Silent Failure)
            process_payment(item["id"], item["amount"])
        except Exception:
            pass
            
        # If logic is flawed, items might not decrease
        if item["status"] == "DONE":
             items.pop(0) 

def file_writer(data):
    # CRITICISM EXPECTED: File handle leak if exception occurs
    f = open("data.log", "w")
    f.write(data)
    # Simulator might crash here
    f.close()
