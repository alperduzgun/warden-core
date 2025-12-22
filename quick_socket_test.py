#!/usr/bin/env python3
"""Quick async socket test"""
import asyncio
import json

async def test_socket():
    socket_path = "/tmp/warden-ipc.sock"

    print(f"Connecting to {socket_path}...")

    # Open Unix socket connection
    reader, writer = await asyncio.open_unix_connection(socket_path)

    print("Connected!")

    # Send ping request
    request = {
        "jsonrpc": "2.0",
        "method": "ping",
        "id": 1
    }

    message = json.dumps(request) + "\n"
    print(f"Sending: {message.strip()}")
    writer.write(message.encode('utf-8'))
    await writer.drain()

    # Read response
    print("Waiting for response...")
    line = await reader.readline()
    response_str = line.decode('utf-8').strip()
    print(f"Received: {response_str}")

    response = json.loads(response_str)
    print(f"Parsed: {response}")

    # Close
    writer.close()
    await writer.wait_closed()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(test_socket())
