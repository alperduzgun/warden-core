/**
 * Vulnerable: XSS via innerHTML and document.write.
 */

const express = require('express');
const app = express();

app.get('/search', (req, res) => {
    const query = req.query.q;
    // Direct HTML injection
    res.send('<h1>Results for: ' + query + '</h1>');
});

app.get('/render', (req, res) => {
    const name = req.query.name;
    const html = `<div class="greeting">Hello ${name}</div>`;
    res.send(html);
});

function updateDOM(userInput) {
    document.getElementById('output').innerHTML = userInput;
    document.write('<p>' + userInput + '</p>');
}
