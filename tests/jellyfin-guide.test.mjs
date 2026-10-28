import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { preferredGuideHash, channelLabel } = require('../integrations/jellyfin/guide.js');

test('Live TV opens the guide without redirecting deliberate tab selections', () => {
    assert.equal(preferredGuideHash('#/livetv?collectionType=livetv'), '#/livetv?collectionType=livetv&tab=1');
    assert.equal(preferredGuideHash('#!/livetv.html'), '#!/livetv.html?tab=1');
    assert.equal(preferredGuideHash('#/livetv?tab=0'), null);
    assert.equal(preferredGuideHash('#/livetv?tab=2'), null);
    assert.equal(preferredGuideHash('#/movies'), null);
});

test('Channel labels keep their names and remove only the actual channel-number prefix', () => {
    assert.equal(channelLabel('1 BBC One', '1'), 'BBC One');
    assert.equal(channelLabel('10001 [UK] BBC One London', '10001'), '[UK] BBC One London');
    assert.equal(channelLabel('5STAR', '32'), '5STAR');
    assert.equal(channelLabel('3 <img onerror=bad()>', '3'), '<img onerror=bad()>');
});
