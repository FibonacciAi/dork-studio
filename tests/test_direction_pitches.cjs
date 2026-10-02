const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../app/static/js/direction-pitches.js'), 'utf8');
const image = 'data:image/png;base64,synthetic-selected-image';
function fixture() {
    const requests = [], staged = [], panels = [], overlays = [], elements = new Map();
    let ready;
    function element() {
        const handlers = new Map(), children = [], selectors = new Map();
        let text = '';
        return {
            value: '', innerHTML: '', disabled: false, children, handlers,
            set textContent(value) { text = value; children.length = 0; }, get textContent() { return text; },
            addEventListener(type, fn) { handlers.set(type, fn); },
            appendChild(child) { children.push(child); },
            querySelector(selector) {
                if (!selectors.has(selector)) { const child = element(); if (selector === '.pitch-provider') child.value = 'grok'; selectors.set(selector, child); }
                return selectors.get(selector);
            },
            focus() { this.focused = true; }, remove() { this.removed = true; },
        };
    }
    const get = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
    const context = {
        document: {
            addEventListener(type, fn) { ready = fn; }, getElementById: get,
            createElement: element, querySelector(selector) { return selector === '.prompt-suggest-overlay' ? overlays.at(-1) : { src: image }; },
            body: { appendChild(overlay) { overlays.push(overlay); } },
        },
        state: { imagineImages: [{ url: '/images/selected.png', prompt: 'The source direction' }], imagineSource: 'synthetic-selected-image', imagineSourceUrl: image, videoSource: 'synthetic-selected-image', videoSourceUrl: 'stale-image-url', directorDraft: { image_prompt: 'Directed still', video_prompt: 'Directed motion' }, videoFromFreeze: true, videoNarrative: ['one', 'two', 'three', 'four', 'five', 'six'], chatMessages: ['private history'], chatVoiceMemories: ['private memory'] },
        assetLibActiveChars: () => [{ name: 'Selected Cast', data: 'must-not-copy-private-asset' }],
        assetLibActiveStyles: () => [{ name: 'Selected Look' }],
        assetLibDataUrlForSource: raw => `data:image/png;base64,${raw}`,
        DEFAULT_CHAT_MODEL: 'test-chat-model', escapeAttr: value => String(value).replaceAll('"', '&quot;'), toast() {}, savePersistence() {},
        async fetchAsDataUrl(url) { return image; },
        async loadImageAsEditSource(url) { staged.push({ mode: 'edit', url }); },
        async loadImageAsVideoSource(url) { staged.push({ mode: 'video', url }); },
        switchPanel(panel) { panels.push(panel); },
        DorkMedia: { guides: new Map(), refreshEstimates() {} },
        async fetch(url, options) { requests.push({ url, body: JSON.parse(options.body) }); return { ok: true, async json() { return { content: '["Subtle direction","Bold direction","Unexpected direction"]' }; } }; },
        generateImage() { throw new Error('Opening or selecting directions must not render'); },
        generateVideo() { throw new Error('Opening or selecting directions must not render'); },
    };
    context.window = context; vm.createContext(context); vm.runInContext(source, context); ready();
    return { context, get, requests, staged, panels, overlays };
}
const click = target => target.handlers.get('click')({ target });

test('opening the three-direction card discloses billing and makes no provider request', () => {
    const f = fixture(); f.context.DorkPitches.open(image, 'edit');
    assert.equal(f.requests.length, 0); assert.equal(f.staged.length, 0);
    assert.match(f.overlays[0].innerHTML, /billed separately/);
    assert.match(f.overlays[0].innerHTML, /Suggest 3 directions/);
});

test('explicit pitch request sends the exact source and bounded creative context once', async () => {
    const f = fixture(); f.context.state.imagineSourceOrigin = { url: '/images/selected.png', raw: 'synthetic-selected-image' };
    f.get('director-vision').value = 'A shared creative brief'; f.get('imagine-prompt').value = 'Current edit';
    f.get('director-interests').value = 'Practical sci-fi'; f.context.state.directorStylePreset = { prompt: 'Motivated teal lighting' };
    f.context.DorkPitches.open(image, 'edit'); const overlay = f.overlays[0];
    await click(overlay.querySelector('.pitch-request'));
    assert.equal(f.requests.length, 1); assert.equal(f.requests[0].url, '/api/chat/sync');
    assert.equal(f.requests[0].body.messages[0].content[1].image_url.url, image);
    const context = JSON.parse(f.requests[0].body.messages[0].content[0].text);
    assert.equal(context.source_direction, 'The source direction'); assert.equal(context.creative_brief, 'A shared creative brief');
    assert.equal(context.director_direction, 'Directed still'); assert.equal(context.current_direction, 'Current edit');
    assert.equal(context.creative_taste.interests, 'Practical sci-fi'); assert.equal(context.creative_taste.selected_style, 'Motivated teal lighting');
    assert.deepEqual(context.active_cast, ['Selected Cast']); assert.deepEqual(context.active_looks, ['Selected Look']);
    assert.deepEqual(context.preceding_scenes, []); assert.ok(!JSON.stringify(context).includes('private'));
    assert.equal(overlay.querySelector('.pitch-options').children.length, 3);
    assert.equal(f.staged.length, 0);
});

test('choosing a pitch stages an editable image direction without submitting a render', async () => {
    const f = fixture(); f.context.DorkPitches.open(image, 'edit'); const overlay = f.overlays[0];
    await click(overlay.querySelector('.pitch-request'));
    await click(overlay.querySelector('.pitch-options').children[1]);
    assert.deepEqual(f.staged, [{ mode: 'edit', url: image }]); assert.deepEqual(f.panels, ['imagine']);
    assert.equal(f.get('imagine-prompt').value, 'Bold direction'); assert.equal(f.get('imagine-prompt').focused, true);
    assert.equal(overlay.removed, true); assert.equal(f.requests.length, 1);
});

test('own direction stages the selected video frame without any AI request or render', async () => {
    const f = fixture(); f.get('video-prompt').value = 'My direction';
    await click(f.get('video-suggest-directions')); const overlay = f.overlays[0];
    await click(overlay.querySelector('.pitch-custom'));
    assert.deepEqual(f.staged, [{ mode: 'video', url: image }]); assert.equal(f.get('video-prompt').value, 'My direction');
    assert.equal(f.requests.length, 0); assert.deepEqual(f.panels, ['video']);
});

test('next-scene context uses five recent scenes and the exact guide, without stale source metadata', () => {
    const f = fixture(); f.context.state.videoSourceOrigin = { url: '/images/selected.png', raw: 'a-different-frame' };
    f.context.DorkMedia.guides.set('unrelated-guide', 'Unrelated guidance');
    let context = f.context.DorkPitches.contextFor(image, 'video');
    assert.equal(context.source_direction, ''); assert.equal(context.source_role, 'Selected source image');
    assert.deepEqual(Array.from(context.preceding_scenes), ['two', 'three', 'four', 'five', 'six']);
    f.context.DorkMedia.guides.set('synthetic-selected-image', 'Use composition only');
    context = f.context.DorkPitches.contextFor(image, 'video'); assert.equal(context.source_role, 'Use composition only');
    f.get('director-vision').value = 'x'.repeat(2000); assert.equal(f.context.DorkPitches.contextFor(image, 'video').creative_brief.length, 1600);
});

test('OpenAI selection uses its explicit provider route with the same exact image', async () => {
    const f = fixture(); await f.context.DorkPitches.requestDirections(image, 'video', 'chatgpt', {});
    assert.equal(f.requests.length, 1); assert.equal(f.requests[0].url, '/api/chat/sync-openai');
    assert.equal(f.requests[0].body.messages[0].content[1].image_url.url, image);
});

test('provider errors and malformed pitches are visible without an automatic retry', async () => {
    for (const reply of [{ error: 'Provider unavailable' }, { content: 'not JSON' }, { content: '["only one"]' }]) {
        const f = fixture(); f.context.fetch = async () => { f.requests.push({}); return { ok: false, async json() { return reply; } }; };
        if (!reply.error) f.context.fetch = async () => { f.requests.push({}); return { ok: true, async json() { return reply; } }; };
        f.context.DorkPitches.open(image, 'video'); const overlay = f.overlays[0];
        await click(overlay.querySelector('.pitch-request'));
        assert.equal(f.requests.length, 1); assert.equal(f.staged.length, 0);
        assert.match(overlay.querySelector('.pitch-options').textContent, /Provider unavailable|No retry/);
        assert.equal(overlay.querySelector('.pitch-request').disabled, false);
    }
});

test('unsupported providers and missing sources do not call a provider', async () => {
    const f = fixture(); await assert.rejects(f.context.DorkPitches.requestDirections(image, 'edit', 'other', {}), /Choose Grok or OpenAI/);
    f.context.state.imagineSource = null; click(f.get('imagine-suggest-directions'));
    assert.equal(f.requests.length, 0); assert.equal(f.overlays.length, 0);
});
