#!/usr/bin/env python3
"""
Password Reset Script for Nutrition Analyzer
Run this script to manually reset a user's password.
"""

import json
import os
from werkzeug.security import generate_password_hash

def reset_password():
    # Path to users.json
    users_file = os.path.join(os.path.dirname(__file__), 'users.json')

    # Load users
    with open(users_file, 'r', encoding='utf-8') as f:
        users = json.load(f)

    print("Current users:")
    for email in users:
        print(f"  - {email} ({users[email]['name']})")

    # Get user input
    email = input("\nEnter the email address to reset: ").strip().lower()
    if email not in users:
        print("User not found!")
        return

    new_password = input("Enter new password (min 6 characters): ").strip()
    if len(new_password) < 6:
        print("Password must be at least 6 characters!")
        return

    # Update password
    users[email]['password'] = generate_password_hash(new_password)

    # Save users
    with open(users_file, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)

    print(f"\n✅ Password reset successful for {email}")
    print("You can now login with the new password.")

if __name__ == "__main__":
    reset_password()