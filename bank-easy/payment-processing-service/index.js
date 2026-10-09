const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

const LEDGER_URL = process.env.LEDGER_URL || 'http://localhost:4002';
const payments = [];

async function ledgerTxn(accountId, type, amount) {
  const res = await fetch(`${LEDGER_URL}/accounts/${accountId}/transactions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, amount }),
  });
  const body = await res.json();
  return { ok: res.ok, status: res.status, body };
}

app.post('/payments', async (req, res) => {
  const { from, to, amount } = req.body;
  if (!from || !to) return res.status(400).json({ error: 'from and to required' });
  if (from === to) return res.status(400).json({ error: 'cannot pay the same account' });
  if (!Number.isInteger(amount) || amount <= 0) {
    return res.status(400).json({ error: 'amount must be a positive integer (cents)' });
  }

  const payment = { id: crypto.randomUUID(), from, to, amount, at: new Date().toISOString() };

  let debit;
  try {
    debit = await ledgerTxn(from, 'withdrawal', amount);
  } catch (err) {
    return res.status(502).json({ error: 'ledger unreachable' });
  }
  if (!debit.ok) return res.status(debit.status).json({ error: debit.body.error });

  let credit;
  try {
    credit = await ledgerTxn(to, 'deposit', amount);
  } catch (err) {
    credit = { ok: false, status: 502, body: { error: 'ledger unreachable' } };
  }
  if (!credit.ok) {
    // refund the sender
    await ledgerTxn(from, 'deposit', amount).catch(() => {});
    payments.push({ ...payment, status: 'failed' });
    return res.status(credit.status).json({ error: credit.body.error, refunded: true });
  }

  payments.push({ ...payment, status: 'completed' });
  res.status(201).json({ payment: { ...payment, status: 'completed' } });
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

const PORT = process.env.PORT || 4003;
app.listen(PORT, () => console.log(`payment-processing-service running on port ${PORT}`));
