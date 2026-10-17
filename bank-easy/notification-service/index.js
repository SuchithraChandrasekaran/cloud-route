const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

const TYPES = ['payment', 'loan', 'fraud-alert', 'general'];
const notifications = [];

app.post('/notifications', (req, res) => {
  const { to, message, type = 'general' } = req.body;
  if (!to) return res.status(400).json({ error: 'to required' });
  if (!message) return res.status(400).json({ error: 'message required' });
  if (!TYPES.includes(type)) {
    return res.status(400).json({ error: 'type must be one of: ' + TYPES.join(', ') });
  }

  const notification = {
    id: crypto.randomUUID(),
    to, message, type,
    status: 'sent',
    at: new Date().toISOString(),
  };
  notifications.push(notification);
  res.status(201).json({ notification });
});

app.get('/notifications', (req, res) => {
  const { to } = req.query;
  const list = to ? notifications.filter(n => n.to === to) : notifications;
  res.json({ notifications: list });
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

const PORT = process.env.PORT || 4007;
app.listen(PORT, () => console.log(`notification-service running on port ${PORT}`));
