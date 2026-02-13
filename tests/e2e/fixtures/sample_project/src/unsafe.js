// Deliberately vulnerable JavaScript for multi-language testing
const express = require('express');
const app = express();

// XSS vulnerability
app.get('/search', (req, res) => {
    const query = req.query.q;
    res.send('<h1>Results for: ' + query + '</h1>');
});

// Eval usage
function calculate(expression) {
    return eval(expression);
}

// SQL-like injection
function findUser(db, username) {
    return db.query("SELECT * FROM users WHERE name = '" + username + "'");
}
