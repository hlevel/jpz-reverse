const fs = require('fs');
const profiles = JSON.parse(fs.readFileSync('05ctrip-js-reverse/Virtual-Browser_0821_全量封号.json', 'utf8'));

console.log('profiles', profiles.length);
console.log('fields', [...new Set(profiles.flatMap((profile) => Object.keys(profile)))].join(','));

for (const field of ['os', 'chrome_version', 'core_version', 'ua', 'ua-full-version', 'sec-ch-ua', 'webrtc', 'canvas', 'webgl', 'webgl-img', 'webgpu', 'audio-context', 'fonts', 'client-rects', 'cpu', 'memory', 'screen']) {
  const values = profiles.map((profile) => JSON.stringify(profile[field]));
  console.log(field, 'present', values.filter((value) => value !== undefined).length, 'unique', new Set(values).size);
}

const mismatches = [];
profiles.forEach((profile, index) => {
  const version = String(profile.chrome_version);
  const ua = JSON.stringify(profile.ua || {});
  const full = JSON.stringify(profile['ua-full-version'] || {});
  const brands = JSON.stringify(profile['sec-ch-ua'] || {});
  if (!ua.includes(`Chrome/${version}.`)) mismatches.push([index, 'ua']);
  if (!full.includes(`${version}.`)) mismatches.push([index, 'ua-full-version']);
  if (!brands.includes(`"version":${version}`) && !brands.includes(`"version":"${version}"`)) mismatches.push([index, 'sec-ch-ua']);
});
console.log('version_mismatches', JSON.stringify(mismatches));

for (const [index, field] of mismatches) {
  const profile = profiles[index];
  console.log('version_mismatch_detail', index, field, profile.chrome_version, JSON.stringify(profile['sec-ch-ua']));
}

for (const field of ['webgl', 'webgpu', 'canvas', 'audio-context', 'fonts', 'client-rects', 'cpu', 'memory']) {
  console.log(`sample_${field}`, JSON.stringify(profiles[0][field]));
}

profiles.forEach((profile, index) => {
  console.log('gpu_pair', index, profile.webgl?.render, '=>', profile.webgpu?.vendor, profile.webgpu?.architecture);
});
