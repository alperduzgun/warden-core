"""
Vulnerable: XSS via render_template_string and Markup.

corpus_labels:
  xss: 1
"""

from django.utils.safestring import mark_safe
from flask import Flask, render_template_string, request

app = Flask(__name__)


@app.route("/greet")
def greet():
    name = request.args.get("name")
    return render_template_string(f"<h1>Hello {name}</h1>")


@app.route("/profile")
def profile():
    bio = request.form.get("bio")
    safe_bio = mark_safe(bio)  # XSS: user input marked safe without sanitization
    return f"<div class='bio'>{safe_bio}</div>"
