'use strict';

const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');

module.exports = {
  ROOT,
  VAK_CLIENT: path.join(ROOT, 'VakClient'),
  VAK_DEEPGRAM: path.join(ROOT, 'VakDeepGram'),
  VAK_INFRA: path.join(ROOT, 'VakInfra'),
};
