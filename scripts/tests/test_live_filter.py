import sys, asyncio
sys.argv = ['test', '2.0', '0.003', '120', '15']
sys.path.insert(0, 'scripts')
import live_sniper_filtered as m

m.WAIT_S = 5
m.TICK_S = 1
m.HOLD_S = 2

class FakeTS:
    def __init__(self, api_key, on_new_token=None):
        self.stats = {}
        self.subscribed = set()
    async def start(self):
        pass
    async def stop(self):
        pass
    async def subscribe_token(self, mint):
        self.subscribed.add(mint)
    async def unsubscribe_token(self, mint):
        self.subscribed.discard(mint)
    def stats_for(self, mint):
        return self.stats.get(mint)

calls = {'buy': [], 'sell': [], 'logs': []}

def fake_buy(mint):
    calls['buy'].append(mint)
    return 'FAKE_BUY_' + mint[:8]

def fake_sell(mint):
    calls['sell'].append(mint)
    return 'FAKE_SELL_' + mint[:8]

def fake_get_sol():
    return 0.02

def fake_log(rec):
    act = rec.get('action')
    mn = rec.get('mint')
    calls['logs'].append(act)
    print('    [mock-log] ' + str(act) + ' ' + mn[:8])

m.TradeStream = FakeTS
m.buy = fake_buy
m.sell = fake_sell
m.get_sol = fake_get_sol
m.log = fake_log

async def inject():
    await asyncio.sleep(0.3)
    m._ts.stats['BADtokenxxxxxxxxxx'] = {'net_pressure': 0.1, 'unique_buyers': 1, 'buy_sol': 0.1, 'sell_sol': 0.05}
    m._ts.stats['GOODtokenxxxxxxxxx'] = {'net_pressure': 0.5, 'unique_buyers': 5, 'buy_sol': 1.2, 'sell_sol': 0.1}
    await m._on_new_async({'txType': 'create', 'mint': 'BADtokenxxxxxxxxxx', 'solAmount': 3.0})
    await m._on_new_async({'txType': 'create', 'mint': 'GOODtokenxxxxxxxxx', 'solAmount': 5.0})
    print('  [test] injected BAD and GOOD')

async def runner():
    t = asyncio.create_task(inject())
    try:
        await m.main()
    finally:
        t.cancel()

asyncio.run(runner())

print()
print('=== TEST RESULT ===')
print('buy calls:  ' + repr(calls['buy']))
print('sell calls: ' + repr(calls['sell']))
print('logs:       ' + repr(calls['logs']))
ok = calls['buy'] == ['GOODtokenxxxxxxxxx'] and calls['sell'] == ['GOODtokenxxxxxxxxx']
print('PASS: ' + str(ok))
