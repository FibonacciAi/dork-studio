const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fixture(destination = 'imagine', castCount = 0) {
    let ready, apply;
    const clicks = new Map(), requests = [], switches = [], boards = [];
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, { value: id === 'imagine-quality' ? 'low' : '', hidden: true, textContent: '', innerHTML: '', options: [], addEventListener(type, fn) { clicks.set(`${id}:${type}`, fn); } });
        return elements.get(id);
    };
    const context = {
        document: { addEventListener(name, fn) { ready = fn; }, getElementById: element },
        state: { imagineSource: null, imagineSourceUrl: null, videoSource: 'finished-original-frame', videoDuration: '6', videoResolution: '720p', videoModel: 'grok-imagine-video-1.5-lite', imagineModel: 'grok-imagine-image-2.0', imagineResolution: '2k', imagineCount: '1' },
        assetLib: { autoAttach: true }, assetLibActiveChars: () => Array(castCount).fill({}), assetLibActiveStyles: () => [],
        DorkSketch: { create(options) { apply = options.onApply; return { open() {} }; } },
        assetLibDataUrlForSource(raw) { return `data:image/png;base64,${raw}`; },
        renderDirectorSourceImage() {}, savePersistence() {}, toast() {}, loadKeyStatus() {},
        switchPanel(name) { switches.push(name); },
        async compositeRefs(sources, options) { boards.push({ sources, options }); return 'data:image/jpeg;base64,board'; },
        async fetch(url, options) { const body = JSON.parse(options.body); requests.push({ url, body }); return { async json() { return { estimate_usd: body.kind === 'video' ? (body.input_images ? .19 : .18) : .07 }; } }; },
    };
    context.window = context;
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(require.resolve('../app/static/js/media-upgrade.js'), 'utf8'), context);
    ready();
    clicks.get(`${destination}-draw:click`)();
    return { context, apply, element, requests, switches, boards };
}
const guide = { dataURL: 'data:image/png;base64,synthetic-guide', instruction: 'Use drawing as composition only.' };
const settle = () => new Promise(resolve => setImmediate(resolve));

test('video sketch stages a still, preserving its existing opening frame and avoiding paid submissions', async () => {
    const f = fixture('video');
    f.element('video-prompt').value = 'Toy astronaut waves';
    await f.apply(guide); await settle();
    assert.equal(f.context.state.videoSource, 'finished-original-frame');
    assert.equal(f.context.state.imagineSource, 'board');
    assert.equal(f.boards[0].sources[0], 'data:image/png;base64,finished-original-frame');
    assert.equal(f.element('imagine-prompt').value, 'Toy astronaut waves');
    assert.equal(f.element('sketch-video-note').hidden, false);
    assert.deepEqual(f.switches, ['imagine']);
    assert.equal(f.context.DorkMedia.instructionFor('video'), '');
    assert.match(f.context.DorkMedia.instructionFor('image'), /composition/);
    assert.ok(f.requests.every(r => r.url === '/api/media/estimate'));
});

test('director sketch retains the prior source appearance on a local board and passes a guide role', async () => {
    const f = fixture('director');
    f.context.state.directorSourceImage = { dataUrl: 'data:image/png;base64,synthetic-source' };
    await f.apply(guide); await settle();
    assert.equal(f.boards.length, 1);
    assert.deepEqual(Array.from(f.boards[0].sources), ['data:image/png;base64,synthetic-source', guide.dataURL]);
    assert.equal(f.context.state.directorSourceImage.dataUrl, 'data:image/jpeg;base64,board');
    assert.match(f.context.DorkMedia.instructionFor('director'), /SOURCE APPEARANCE/);
    f.context.state.imagineSource = 'board';
    assert.match(f.context.DorkMedia.instructionFor('image'), /layout only/);
    f.context.state.imagineSource = null;
    assert.equal(f.context.DorkMedia.instructionFor('image'), '');
    assert.ok(f.requests.every(r => r.url === '/api/media/estimate'));
});

test('video cost includes separate Cast/Looks preparation', async () => {
    const f = fixture('video', 2); await settle();
    assert.match(f.element('video-estimate').textContent, /\$0\.26 USD/);
    assert.match(f.element('video-estimate').textContent, /\$0\.07 for a Cast\/Looks still, then \$0\.19/);
});
