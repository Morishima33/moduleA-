// 真实客户端隔离测试：并发GET合并、容器隔离、失败重试和写操作前后失效。
// 使用轻量tasks读入口；inbox会等待workspace，不再假定它同步开始fetch。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8')
  .replaceAll('import.meta.env.VITE_API_BASE', 'undefined').replaceAll('import.meta.env.DEV', 'false');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
let sequence = 0;
const fresh = () => import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}#${sequence++}`);
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const response = (data, status = 200) => new Response(JSON.stringify(data), { status });

test('同时读取只发一次；调用者独立，完成后重新取数', async () => {
  const { api } = await fresh();
  const gate = deferred(); let calls = 0;
  globalThis.fetch = () => { calls++; return gate.promise; };
  const a = api.tasks({ active: true }), b = api.tasks({ active: true });
  assert.equal(calls, 1);
  gate.resolve(response({ items: [{ value: 1 }] }));
  const [x, y] = await Promise.all([a, b]);
  x.items[0].value = 2;
  assert.equal(y.items[0].value, 1);
  globalThis.fetch = async () => { calls++; return response({ items: [] }); };
  await api.tasks({ active: true }); assert.equal(calls, 2);
});

test('网络失败不留缓存，可重新读取', async () => {
  const { api } = await fresh(); let calls = 0;
  globalThis.fetch = async () => { calls++; throw Error('offline'); };
  await assert.rejects(Promise.all([api.tasks({ active: true }), api.tasks({ active: true })]));
  assert.equal(calls, 1);
  globalThis.fetch = async () => { calls++; return response({ items: [] }); };
  await api.tasks({ active: true }); assert.equal(calls, 2);
});

test('写请求开始和结束均隔离旧GET，旧响应不会清除新请求', async () => {
  const { api, loadSession } = await fresh();
  globalThis.fetch = async () => response({ token: 'fixture-token' });
  await loadSession();
  const reads = [], writeGate = deferred(); let writes = 0;
  globalThis.fetch = (url, opts) => {
    if (opts.method === 'POST') { writes++; return writeGate.promise; }
    const gate = deferred(); reads.push(gate); return gate.promise;
  };
  const old = api.tasks({ active: true });
  const write = api.createStudy({});
  const during = api.tasks({ active: true });
  assert.equal(reads.length, 2);
  reads[0].resolve(response({ items: ['old'] })); await old;
  const duringAgain = api.tasks({ active: true }); assert.equal(reads.length, 2);
  writeGate.resolve(response({ created: true })); await write;
  const after = api.tasks({ active: true }); assert.equal(reads.length, 3);
  reads[1].resolve(response({ items: ['during'] })); await Promise.all([during, duringAgain]);
  const afterAgain = api.tasks({ active: true }); assert.equal(reads.length, 3);
  reads[2].resolve(response({ items: ['after'] }));
  assert.deepEqual(await after, { items: ['after'] }); await afterAgain;
  assert.equal(writes, 1);
});

test('令牌失效仍只更新一次并重试一次，独立POST不合并', async () => {
  const { api } = await fresh(); let sessions = 0, posts = 0;
  globalThis.fetch = async (url, opts) => {
    if (url.endsWith('/session')) return response({ token: `fixture-${++sessions}` });
    posts++;
    if (posts === 1) return response({ error: { code: 'BAD_TOKEN', message_zh: 'expired' } }, 403);
    assert.equal(opts.headers['X-ModuleA-Token'], 'fixture-2');
    return response({ created: true });
  };
  await api.createStudy({}); assert.equal(sessions, 2); assert.equal(posts, 2);
  await Promise.all([api.createStudy({}), api.createStudy({})]); assert.equal(posts, 4);
});
