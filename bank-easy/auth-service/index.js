const express = require('express');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
require('dotenv').config();

const app = express();
app.use(express.json());

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-change-me';
const users = []; // in-memory for now, swap for DynamoDB later

app.post('/signup', async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) {
    return res.status(400).json({ error: 'email and password required' });
  }
  if (users.find(u => u.email === email)) {
    return res.status(409).json({ error: 'user already exists' });
  }
  const hashed = await bcrypt.hash(password, 10);
  users.push({ email, password: hashed });
  res.status(201).json({ message: 'user created', email });
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

const PORT = process.env.PORT || 4001;
app.listen(PORT, () => console.log(`auth-service running on port ${PORT}`));
