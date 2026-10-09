const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

const accounts = new Map(); // id -> { id, owner, balance (cents), transactions: [] }

app.post('/accounts', (req, res) => {
  const { owner } = req.body;
  if (!owner) return res.status(400).json({ error: 'owner required' });
  const id = crypto.randomUUID();
  accounts.set(id, { id, owner, balance: 0, transactions: [] });
  res.status(201).json({ id, owner, balance: 0 });
});

app.get('/accounts/:id/balance', (req, res) => {
  const acct = accounts.get(req.params.id);
  if (!acct) return res.status(404).json({ error: 'account not found' });
  res.json({ id: acct.id, balance: acct.balance });
});

app.post('/accounts/:id/transactions', (req, res) => {
  const acct = accounts.get(req.params.id);
  if (!acct) return res.status(404).json({ error: 'account not found' });

  const { type, amount } = req.body;
  if (!['deposit', 'withdrawal'].includes(type)) {
    return res.status(400).json({ error: 'type must be deposit or withdrawal' });
  }
  if (!Number.isInteger(amount) || amount <= 0) {
    return res.status(400).json({ error: 'amount must be a positive integer (cents)' });
  }
  if (type === 'withdrawal' && amount > acct.balance) {
    return res.status(422).json({ error: 'insufficient funds' });
  }

  acct.balance += type === 'deposit' ? amount : -amount;
  const txn = { id: crypto.randomUUID(), type, amount, at: new Date().toISOString() };
  acct.transactions.push(txn);
  res.status(201).json({ transaction: txn, balance: acct.balance });
});

app.get('/accounts/:id/transactions', (req, res) => {
  const acct = accounts.get(req.params.id);
  if (!acct) return res.status(404).json({ error: 'account not found' });
  res.json({ transactions: acct.transactions });
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

const PORT = process.env.PORT || 4002;
app.listen(PORT, () => console.log(`account-ledger-service running on port ${PORT}`));
