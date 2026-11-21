import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';

const scratch = process.argv[2];
const profile = path.join(scratch, 'edge');
const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const base = 'http://127.0.0.1:8390';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const browser = spawn(edge, ['--headless=new', '--disable-gpu', '--disable-extensions',
  '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
  '--user-data-dir=' + profile, 'about:blank'], {windowsHide: true, stdio: 'ignore'});
let launchError;
browser.on('error', error => { launchError = error; });
const exited = new Promise(resolve => browser.once('close', resolve));
let ws;

async function until(check, label) {
  for (let i = 0; i < 60; i++) {
    if (launchError) throw launchError;
    const result = await check();
    if (result) return result;
    await delay(100);
  }
  throw new Error('Timeout: ' + label);
}

try {
  const port = await until(async () => {
    const file = await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8').catch(() => '');
    return file.split(/\r?\n/)[0];
  }, 'Edge debugger');
  const tabs = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  ws = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
  const pending = new Map();
  const errors = [];
  let seq = 0;
  ws.addEventListener('message', ({data}) => {
    const reply = JSON.parse(data);
    if (reply.method === 'Runtime.exceptionThrown') {
      errors.push(reply.params.exceptionDetails.exception?.description || reply.params.exceptionDetails.text);
    }
    const callback = pending.get(reply.id);
    if (callback) {
      pending.delete(reply.id);
      callback(reply);
    }
  });
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, {once:true});
    ws.addEventListener('error', reject, {once:true});
  });
  function call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(new Error('CDP timeout: ' + method));
      }, 8000);
      pending.set(id, reply => {
        clearTimeout(timeout);
        if (reply.error) reject(new Error(reply.error.message));
        else resolve(reply.result);
      });
      ws.send(JSON.stringify({id, method, params}));
    });
  }
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, returnByValue:true});
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Network.enable');
  await call('Network.setBlockedURLs', {urls:['https://*']});
  const pages = [
    ['/', 'window._ws?.readyState === 1 && typeof S !== "undefined" && S.admin === true'],
    ['/obs', 'typeof showDm === "function" && typeof myVer !== "undefined" && !!myVer'],
    ['/obs-songs', 'typeof draw === "function" && document.querySelector("#box").textContent.includes("未被限流的另一个连接")'],
  ];
  for (const [route, expression] of pages) {
    await call('Page.navigate', {url:base + route});
    await until(async () => evaluate('location.pathname === ' + JSON.stringify(route) +
      ' && document.readyState === "complete" && (' + expression + ')'), route);
  }
  assert.deepEqual(errors, []);
  console.log('Browser: main page and both OBS pages connected without JavaScript errors.');
  await call('Browser.close').catch(() => {});
} finally {
  ws?.close();
  if (browser.exitCode === null && !browser.killed) browser.kill();
  await exited;
}
