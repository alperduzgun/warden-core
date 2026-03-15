/**
 * Clean code: no vulnerabilities expected. False positive test.
 */

const express = require('express');
const { body, validationResult } = require('express-validator');

const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
    res.json({ status: 'ok', uptime: process.uptime() });
});

app.post('/users',
    body('email').isEmail().normalizeEmail(),
    body('name').trim().escape(),
    (req, res) => {
        const errors = validationResult(req);
        if (!errors.isEmpty()) {
            return res.status(400).json({ errors: errors.array() });
        }
        res.status(201).json({ message: 'User created' });
    }
);

function sum(numbers) {
    return numbers.reduce((acc, n) => acc + n, 0);
}

module.exports = { sum };
