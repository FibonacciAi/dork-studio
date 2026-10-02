const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../app/static/js/app.js'), 'utf8');
function section(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
function fixture() {
    const requests = [], elements = new Map();
    const get = id => { if (!elements.has(id)) elements.set(id, { value: '', innerHTML: '', disabled: false }); return elements.get(id); };
    const context = {
        state: { videoSource: 'actual-last-frame', videoContinuationSource: { raw: 'actual-last-frame', filename: 'previous.mp4' }, videos: [], videoNarrative: [] },
        assetLib: { autoAttach: true }, assetLibActiveChars: () => [{ name: 'Synthetic Cast', id: 'cast' }], assetLibActiveStyles: () => [],
        document: { getElementById: get, querySelector() { return null; } },
        DorkMedia: { instructionFor() { return ''; } },
        escapeAttr: x => x, async fetchAsDataUrl(url) { return url; },
        async assetLibBuildEffectiveSource() { throw new Error('Exact continuation frame must not become a reference board'); },
        async _assetLibOrigFetch() { throw new Error('Continuation must not submit a paid Cast edit'); },
        getVideoApiSettings() { return { model: 'selected-model', duration: 15, resolution: '720p', aspect_ratio: '16:9' }; },
        async fetch(url, options) { requests.push({ url, body: JSON.parse(options.body) }); return { async json() { return { id: 'existing-job' }; } }; },
        pollVideo() {}, toast() {},
    };
    context.window = context; vm.createContext(context);
    vm.runInContext(section('function composeVideoPrompt(', 'function getVideoApiSettings(')
        + section('async function createVideoCompositeSource(', 'function pollVideo(')
        + section('async function _assetLibTransformPayload(', 'const _assetLibOrigFetch ='), context);
    return { context, requests, get };
}

test('ordinary motion prompts stay unchanged and explicit dialogue is preserved without stock speech', () => {
    const f = fixture();
    assert.equal(f.context.composeVideoPrompt('A toy astronaut walks to the right.'), 'A toy astronaut walks to the right.');
    assert.equal(f.context.composeVideoPrompt('Say "This is the moment."'), 'Say "This is the moment."');
    f.context.DorkMedia.instructionFor = () => 'Use this drawing as composition only.';
    const once = f.context.composeVideoPrompt('Pan left');
    assert.equal(f.context.composeVideoPrompt(once), once);
});

test('Continue generates from the exact decoded frame with all chosen model settings and no Cast edit', async () => {
    const f = fixture(); f.get('video-prompt').value = 'Keep moving right, then look back';
    await f.context.generateVideo();
    assert.equal(f.requests.length, 1); assert.equal(f.requests[0].url, '/api/video/generate');
    assert.equal(f.requests[0].body.image, 'actual-last-frame');
    assert.equal(f.requests[0].body.prompt, 'Keep moving right, then look back');
    assert.equal(f.requests[0].body.model, 'selected-model'); assert.equal(f.requests[0].body.duration, 15);
    assert.equal(f.requests[0].body.asset_refs_precomposed, true);
    const transformed = await f.context._assetLibTransformPayload(f.requests[0].body, { kind: 'video' });
    assert.equal(transformed.payload.image, 'actual-last-frame'); assert.equal(transformed.payload.asset_refs_precomposed, undefined);
});

test('fetch wrapper and Cast compositor both preserve a matching continuation image', async () => {
    const f = fixture();
    assert.equal(await f.context.createVideoCompositeSource('Move right', 'actual-last-frame'), null);
    const transformed = await f.context._assetLibTransformPayload({ image: 'actual-last-frame', prompt: 'Move right', model: 'selected-model' }, { kind: 'video' });
    assert.equal(transformed.payload.image, 'actual-last-frame');
    assert.equal(transformed.payload.model, 'selected-model');
});

test('a newly selected image clears stale continuation context and keeps its exact pixels', async () => {
    const f = fixture();
    vm.runInContext(section('async function loadImageAsVideoSource(', 'async function loadImageAsEditSource('), f.context);
    await f.context.loadImageAsVideoSource('data:image/png;base64,new-selected-pixels');
    assert.equal(f.context.state.videoSource, 'new-selected-pixels');
    assert.equal(f.context.state.videoContinuationSource, null); assert.equal(f.context.state.videoFromFreeze, false);
    assert.equal(f.context.state.videoSourceLoading, false);
});

test('upload targets support keyboard, native button bubbling and dropping the exact selected file', () => {
    const f = fixture(); vm.runInContext(section('function wireImageUploadTarget(', 'function setupDirector('), f.context);
    const events = new Map(), inputEvents = new Map(), files = [], child = {}, drop = {
        addEventListener(name, fn) { events.set(name, fn); }, classList: { add() {}, remove() {} },
    };
    let opens = 0, prevented = 0;
    const input = { click() { opens++; }, addEventListener(name, fn) { inputEvents.set(name, fn); } };
    f.context.wireImageUploadTarget(drop, input, file => files.push(file));
    events.get('keydown')({ target: drop, key: 'Enter', preventDefault() { prevented++; } });
    events.get('keydown')({ target: drop, key: ' ', preventDefault() { prevented++; } });
    events.get('keydown')({ target: child, key: 'Enter', preventDefault() { throw new Error('Native child keyboard must not open twice'); } });
    events.get('click')({ target: child });
    const file = { name: 'synthetic.png' };
    events.get('drop')({ preventDefault() {}, dataTransfer: { files: [file] } });
    inputEvents.get('change')({ target: { files: [file] } });
    assert.equal(opens, 3); assert.equal(prevented, 2); assert.deepEqual(files, [file, file]);
});
