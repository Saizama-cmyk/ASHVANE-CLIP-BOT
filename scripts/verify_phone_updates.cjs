const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const source = fs.readFileSync(path.join(__dirname, '../phone/updates.js'), 'utf8');
  const {releaseVersion, isNewerVersion} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  assert.equal(releaseVersion({tag_name: 'phone-latest', name: 'Ashvane 1.0.21'}), '1.0.21');
  assert.equal(releaseVersion({tag_name: 'phone-v1.0.22', name: 'Ashvane'}), '1.0.22');
  assert.equal(releaseVersion({message: 'Not Found'}), '');
  assert.equal(isNewerVersion('1.0.21', '1.0.20'), true);
  assert.equal(isNewerVersion('1.0.20', '1.0.21'), false);
  assert.equal(isNewerVersion('1.0.21', '1.0.21'), false);
  assert.equal(isNewerVersion('1.0.10', '1.0.9'), true);
  assert.equal(isNewerVersion('', '1.0.20'), false);
  assert.equal(isNewerVersion('1.0.21', undefined), false);
  console.log('Phone update checks passed: latest release alias, numbered tags, numeric comparison, no downgrade.');
})();
