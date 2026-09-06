#!/usr/bin/env node
'use strict';
const {spawnSync, spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

function candidates(env = process.env, platform = process.platform) {
  if (env.SF_PYTHON) return [[env.SF_PYTHON, []]];
  return platform === 'win32' ? [['py', ['-3']], ['python', []]] : [['python3', []], ['python', []]];
}
function findPython(run = spawnSync) {
  for (const [exe, prefix] of candidates()) {
    const result = run(exe, [...prefix, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'],
      {stdio: 'ignore', windowsHide: true, timeout: 10000, shell: false});
    if (!result.error && result.status === 0) return [exe, prefix];
  }
  throw new Error('Python 3.10+ is required. Install Python or set SF_PYTHON to its executable path.');
}
function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) {
    console.log('salesoptecs-mcp setup | doctor | review PLAN_ID | status PLAN_ID | report PLAN_ID\nNo arguments: start MCP over stdio. Python 3.10+ required. No credentials belong on the command line.');
    return;
  }
  const base = path.resolve(process.env.SF_RUNTIME_DIR || path.join(os.homedir(), '.salesoptecs-mcp', 'runtime-v02'));
  const python = path.join(base, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (args[0] === 'setup') {
    const [exe, prefix] = findPython();
    for (const [command, commandArgs] of [
      [exe, [...prefix, '-m', 'venv', base]],
      [python, ['-m', 'pip', 'install', 'mcp>=1,<2', 'simple-salesforce>=1.12,<2', 'truststore>=0.10,<1']]
    ]) {
      const r = spawnSync(command, commandArgs, {stdio: ['inherit', 2, 2], windowsHide: true, shell: false});
      if (r.error || r.status !== 0) throw new Error('Setup failed. Check Python/venv availability and network access.');
    }
    console.error('Isolated runtime ready. Configure Salesforce credentials in your MCP client environment.');
    return;
  }
  if (!fs.existsSync(python)) throw new Error('Runtime is not installed. Run salesoptecs-mcp setup first.');
  if (args[0] === 'doctor') {
    const r = spawnSync(python, ['-c', 'import mcp, simple_salesforce, truststore; print("Runtime dependencies OK; Salesforce connection was not tested.")'],
      {stdio: 'inherit', windowsHide: true, shell: false});
    process.exitCode = r.status || (r.error ? 1 : 0);
    return;
  }
  const runtime = path.join(__dirname, '../runtime/salesforce_mcp_server.py');
  if (!fs.existsSync(runtime)) throw new Error('Packaged runtime missing. Build the package before running it.');
  const child = spawn(python, [runtime, ...args], {stdio: 'inherit', windowsHide: true, shell: false,
    env: {...process.env, SF_NO_AUTO_INSTALL: '1'}});
  child.on('error', () => {console.error('Could not start Python runtime.'); process.exitCode = 1;});
  child.on('exit', (code) => {process.exitCode = code === null ? 1 : code;});
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
}
module.exports = {candidates, findPython};
if (require.main === module) {
  try {main();} catch (err) {console.error(err.message); process.exitCode = 1;}
}
