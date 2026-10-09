const express = require('express');

const app = express();
app.use(express.json());

const REVIEW_AMOUNT = 500000;   // 5,000.00 in cents
const BLOCK_AMOUNT = 1000000;   // 10,000.00 in cents
const BURST_LIMIT = 3;          // previous checks within the window
const WINDOW_MS = 60 * 1000;

const history = new Map(); // account id -> array of timestamps

app.post('/check', (req, res) => {
  const { from, amount } = req.body;
  if (!from) return res.status(400).json({ error: 'from required' });
  if (!Number.isInteger(amount) || amount <= 0) {
    return res.status(400).json({ error: 'amount must be a positive integer (cents)' });
  }

  const now = Date.now();
  const recent = (history.get(from) || []).filter(t => now - t < WINDOW_MS);
  history.set(from, [...recent, now]);

  const reasons = [];
  let decision = 'allow';

  if (recent.length >= BURST_LIMIT) {
    decision = 'review';
    reasons.push('burst of payments in the last minute');
  }
  if (amount >= REVIEW_AMOUNT) {
    decision = 'review';
    reasons.push('large amount');
  }
  if (amount >= BLOCK_AMOUNT) {
    decision = 'block';
    reasons.push('amount over block limit');
  }

  res.json({ decision, reasons });
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

const PORT = process.env.PORT || 4005;
app.listen(PORT, () => console.log(`fraud-detection-service running on port ${PORT}`));
