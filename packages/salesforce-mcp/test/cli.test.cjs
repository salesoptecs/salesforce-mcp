const {test} = require('node:test');
const assert = require('node:assert/strict');
const {candidates, findPython} = require('../bin/cli.cjs');
test('explicit Python path stays a single executable, including spaces', () => {
  assert.deepEqual(candidates({SF_PYTHON: 'C:/Program Files/Python/python.exe'}, 'win32'),
    [['C:/Program Files/Python/python.exe', []]]);
});
test('Windows Python launcher has a separate -3 argument', () => {
  assert.deepEqual(candidates({}, 'win32')[0], ['py', ['-3']]);
});
test('Python discovery fails clearly and never invokes a shell', () => {
  assert.throws(() => findPython((exe, args, opts) => {
    assert.equal(opts.shell, false); return {status: 1};
  }), /Python 3.10/);
});
test('Python discovery accepts a compatible runtime', () => {
  assert.equal(findPython(() => ({status: 0})).length, 2);
});
