"""
Vulnerable: Command injection via os.system and subprocess shell=True.

corpus_labels:
  command-injection: 3
"""

import os
import subprocess

from flask import Flask, request

app = Flask(__name__)


@app.route("/ping")
def ping():
    host = request.args.get("host")
    os.system(f"ping -c 1 {host}")
    return "OK"


@app.route("/convert")
def convert():
    filename = request.args.get("file")
    subprocess.run(f"convert {filename} output.png", shell=True)
    return "Done"


@app.route("/exec")
def run_command():
    cmd = request.form.get("cmd")
    result = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    return result.stdout.read()
