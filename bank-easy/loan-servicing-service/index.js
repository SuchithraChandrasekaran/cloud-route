const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

const LEDGER_URL = process.env.LEDGER_URL || 'http://localhost:4002';
const SCORING_URL = process.env.SCORING_URL || 'http://localhost:4004';

const RATES = { 'low risk': 0.05, 'medium risk': 0.10 }; // yearly, high risk is denied
const loans = new Map();

async function call(name, url, options) {
  try {
    const res = await fetch(url, options);
    const body = await res.json();
    return { ok: res.ok, status: res.status, body };
  } catch (err) {
    return { unreachable: name };
  }
}

app.post('/loans', async (req, res) => {
  const { accountId, amount, termMonths } = req.body;
  if (!accountId) return res.status(400).json({ error: 'accountId required' });
  if (!Number.isInteger(amount) || amount <= 0) {
    return res.status(400).json({ error: 'amount must be a positive integer (cents)' });
  }
  if (!Number.isInteger(termMonths) || termMonths < 1 || termMonths > 60) {
    return res.status(400).json({ error: 'termMonths must be a whole number from 1 to 60' });
  }

  // 1. transaction history from account-ledger
  const history = await call('account-ledger', `${LEDGER_URL}/accounts/${accountId}/transactions`);
  if (history.unreachable) return res.status(502).json({ error: 'account-ledger unreachable' });
  if (!history.ok) return res.status(history.status).json({ error: history.body.error });

  // 2. score from credit-scoring
  const scored = await call('credit-scoring', `${SCORING_URL}/score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transactions: history.body.transactions }),
  });
  if (scored.unreachable) return res.status(502).json({ error: 'credit-scoring unreachable' });
  if (!scored.ok) return res.status(502).json({ error: 'credit-scoring failed' });

  const { score, band } = scored.body;
  const rate = RATES[band];
  if (rate === undefined) {
    return res.status(422).json({ status: 'denied', score, band, reason: 'credit risk too high' });
  }

  // 3. pay out the loan through account-ledger
  const payout = await call('account-ledger', `${LEDGER_URL}/accounts/${accountId}/transactions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: 'deposit', amount }),
  });
  if (payout.unreachable) return res.status(502).json({ error: 'account-ledger unreachable' });
  if (!payout.ok) return res.status(502).json({ error: 'payout failed' });

  // 4. simple repayment schedule, whole cents
  const total = Math.round(amount * (1 + rate * termMonths / 12));
  const installment = Math.ceil(total / termMonths);
  const loan = {
    id: crypto.randomUUID(),
    accountId, amount, termMonths, score, band,
    yearlyRate: rate, total, installment,
    status: 'active',
    at: new Date().toISOString(),
  };
  loans.set(loan.id, loan);
  res.status(201).json({ loan });
});

app.get('/loans/:id', (req, res) => {
  const loan = loans.get(req.params.id);
  if (!loan) return res.status(404).json({ error: 'loan not found' });
  res.json({ loan });
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

const PORT = process.env.PORT || 4006;
app.listen(PORT, () => console.log(`loan-servicing-service running on port ${PORT}`));
