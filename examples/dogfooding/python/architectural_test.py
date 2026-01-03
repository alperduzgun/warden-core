"""
Architectural Frame Test - Code structure and patterns.

This file demonstrates architectural anti-patterns that the
Architectural Frame should detect.
"""

import os
import json
import requests


# 🔴 GOD CLASS - Too many responsibilities
class UserManager:
    """
    Anti-pattern: God class with too many responsibilities.
    Should be split into UserRepository, UserValidator, NotificationService, etc.
    """
    
    def __init__(self):
        self.db_connection = None
        self.cache = {}
        self.email_client = None
    
    # Database operations
    def connect_database(self):
        pass
    
    def create_user(self, data: dict):
        pass
    
    def update_user(self, user_id: str, data: dict):
        pass
    
    def delete_user(self, user_id: str):
        pass
    
    # Validation
    def validate_email(self, email: str) -> bool:
        return "@" in email
    
    def validate_password(self, password: str) -> bool:
        return len(password) >= 8
    
    # Caching
    def cache_user(self, user_id: str, data: dict):
        self.cache[user_id] = data
    
    def get_cached_user(self, user_id: str):
        return self.cache.get(user_id)
    
    # Notifications
    def send_welcome_email(self, email: str):
        pass
    
    def send_password_reset(self, email: str):
        pass
    
    # Reporting
    def generate_user_report(self):
        pass
    
    def export_to_csv(self):
        pass


# 🔴 TIGHT COUPLING - Direct dependency on concrete implementation
class OrderService:
    """Anti-pattern: Tightly coupled to specific implementations."""
    
    def __init__(self):
        # 🔴 Should use dependency injection
        self.payment = StripePayment()  # Hardcoded dependency
        self.shipping = FedexShipping()  # Hardcoded dependency
    
    def process_order(self, order: dict):
        self.payment.charge(order["amount"])
        self.shipping.ship(order["address"])


class StripePayment:
    def charge(self, amount: float):
        pass


class FedexShipping:
    def ship(self, address: str):
        pass


# 🔴 CIRCULAR DEPENDENCY POTENTIAL
class ServiceA:
    def __init__(self, service_b: "ServiceB"):
        self.service_b = service_b


class ServiceB:
    def __init__(self, service_a: "ServiceA"):
        self.service_a = service_a


# ✅ GOOD PATTERN - Single responsibility, dependency injection
class UserRepository:
    """Clean pattern: Single responsibility."""
    
    def __init__(self, db_client):
        self.db = db_client
    
    def find(self, user_id: str):
        pass
    
    def save(self, user: dict):
        pass


if __name__ == "__main__":
    manager = UserManager()
