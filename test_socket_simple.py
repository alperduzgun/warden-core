#!/usr/bin/env python3
"""Simple socket test - just ping"""
import socket
import json

socket_path = "/tmp/warden-ipc.sock"

print(f"Connecting to {socket_path}...")
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(socket_path)
print("Connected!")

# Send ping
request = {
    "jsonrpc": "2.0",
    "method": "ping",
    "id": 1
}

message = json.dumps(request) + "\n"
print(f"Sending: {message.strip()}")
sock.sendall(message.encode('utf-8'))

# Read response
print("Waiting for response...")
response_data = b""
while True:
    chunk = sock.recv(1024)
    print(f"Received chunk ({len(chunk)} bytes): {chunk}")

    if not chunk:
        print("Connection closed by server")
        break

    response_data += chunk

    # Check if we have complete JSON
    try:
        response_str = response_data.decode('utf-8').strip()
        response = json.loads(response_str)
        print(f"Successfully parsed response: {response}")
        break
    except json.JSONDecodeError:
        # Not complete yet, keep reading
        print("Incomplete JSON, continuing...")
        continue

sock.close()
print("Done!")
