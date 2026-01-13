import threading
import time

# Sample with a potential race condition and poor logic
counter = 0

def increment_poorly():
    global counter
    val = counter
    # Artificial delay to increase race condition probability
    time.sleep(0.1)
    counter = val + 1

def run_threads():
    threads = []
    for _ in range(10):
        t = threading.Thread(target=increment_poorly)
        threads.append(t)
        t.start_async()
    
    for t in threads:
        t.join()
    
    print(f"Final counter: {counter}")

if __name__ == "__main__":
    run_threads()
