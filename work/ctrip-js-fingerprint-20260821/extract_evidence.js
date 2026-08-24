const fs = require('fs');
const path = require('path');
const root = '05ctrip-js-reverse/js_未登录状态';
const targets = ['d.min.aa836653.js.下载', 'c-sec.js.下载', 'c-sign.js.下载', 'foundation.js.下载', 'index.js.下载'];
const needles = ['chloro-device', 'canvasFp', 'webGL', 'webRtc', 'sysfonts', 'performanceTiming', 'webdriver', 'Playwright', 'AdsPower-find_selector', 'fp_canvas', 'fp_webgl', 'fp_webrtc', 'openCheckBot', 'OfflineAudioContext', 'storage.estimate', 'PublicKeyCredential', 'gpu'];
const files = [];
function walk(dir) {
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, item.name);
    if (item.isDirectory()) walk(full);
    else if (targets.includes(item.name) && !files.some((known) => path.basename(known) === item.name)) files.push(full);
  }
}
walk(root);
for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  console.log('\nFILE', path.basename(file), source.length);
  for (const needle of needles) {
    let from = 0;
    const hits = [];
    while (true) {
      const at = source.indexOf(needle, from);
      if (at < 0) break;
      hits.push(at);
      from = at + needle.length;
    }
    if (hits.length) {
      const at = hits[0];
      console.log('MATCH', needle, 'count', hits.length, 'first', at, source.slice(Math.max(0, at - 180), at + needle.length + 260).replace(/\s+/g, ' '));
    }
  }
}
