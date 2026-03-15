/**
 * Vulnerable: Prototype pollution via dynamic property assignment.
 */

function merge(target, source) {
    for (const key in source) {
        // No __proto__ check - prototype pollution
        target[key] = source[key];
    }
    return target;
}

function setNestedProperty(obj, path, value) {
    const keys = path.split('.');
    let current = obj;
    for (let i = 0; i < keys.length - 1; i++) {
        // No prototype chain guard
        if (!current[keys[i]]) current[keys[i]] = {};
        current = current[keys[i]];
    }
    current[keys[keys.length - 1]] = value;
}

const express = require('express');
const app = express();
app.use(express.json());

app.post('/config', (req, res) => {
    const config = {};
    merge(config, req.body); // User-controlled merge
    res.json(config);
});
