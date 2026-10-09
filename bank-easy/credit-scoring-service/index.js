const express = require('express');

const app = express();
app.use(express.json());

// Simple deterministic rule: start at 300, add points for balance and
// deposit count, subtract if the account has been mostly drained.
function score(transactions) {
  let deposited = 0;
  let withdrawn = 0;
  let depositCount = 0;
  for (const t of transactions) {
    if (t.type === 'deposit') {
      deposited += t.amount;
      depositCount += 1;
    } else {
      withdrawn += t.amount;
    }
  }
  const balance = deposited - withdrawn;

  let s = 300;
  s += Math.min(300, Math.floor(Math.max(balance, 0) / 500));
  s += Math.min(200, depositCount * 20);
  if (deposited > 0 && withdrawn > deposited * 0.9) s -= 100;
  s = Math.max(300, Math.min(850, s));

  const band = s >= 650 ? 'low risk' : s >= 500 ? 'medium risk' : 'high risk';
  return { score: s, band };
}

app.post('/score', (req, res) => {
  const { transactions } = req.body;
  if (!Array.isArray(transactions)) {
    return res.status(400).json({ error: 'transactions must be an array' });
  }
  for (const t of transactions) {
    if (!t || !['deposit', 'withdrawal'].includes(t.type) ||
        !Number.isInteger(t.amount) || t.amount <= 0) {
      return res.status(400).json({ error: 'each transaction needs a valid type and positive integer amount (cents)' });
    }
  }
  res.json(score(transactions));
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

const PORT = process.env.PORT || 4004;
app.listen(PORT, () => console.log(`credit-scoring-service running on port ${PORT}`));
