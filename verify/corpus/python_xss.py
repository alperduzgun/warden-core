"""Vulnerable: XSS via render_template_string and Markup."""

from flask import Flask, Markup, render_template_string, request

app = Flask(__name__)


@app.route("/greet")
def greet():
    name = request.args.get("name")
    return render_template_string(f"<h1>Hello {name}</h1>")


@app.route("/profile")
def profile():
    bio = request.form.get("bio")
    safe_bio = Markup(bio)
    return f"<div class='bio'>{safe_bio}</div>"
