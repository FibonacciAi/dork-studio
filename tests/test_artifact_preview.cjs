const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'app/static/js/media-upgrade.js'), 'utf8');
const context = { window: {}, document: { addEventListener() {} } };
vm.createContext(context);
vm.runInContext(source, context);
const sandbox = context.sandboxArtifactDocument;

function directives(html) {
    const match = /^<meta http-equiv="Content-Security-Policy" content="([^"]+)">/.exec(html);
    assert.ok(match, 'trusted policy must be first, before generated content');
    return new Map(match[1].split(';').filter(value => value.trim()).map(value => {
        const [name, ...tokens] = value.trim().split(/\s+/);
        return [name, tokens];
    }));
}

test('preview permits self-contained executable HTML, inline CSS and data/blob images/media', () => {
    const html = '<!doctype html><style>body{color:teal}</style><img src="data:image/png;base64,example"><script>document.body.dataset.rendered="yes"</script>';
    const result = sandbox(html), policy = directives(result);
    assert.deepEqual(policy.get('script-src'), ["'unsafe-inline'"]);
    assert.deepEqual(policy.get('style-src'), ["'unsafe-inline'"]);
    assert.deepEqual(policy.get('img-src'), ['data:', 'blob:']);
    assert.deepEqual(policy.get('media-src'), ['data:', 'blob:']);
    assert.ok(result.endsWith(html), 'artifact code is retained for execution, not replaced with a screenshot');
});

test('preview denies network, forms and base URL changes; artifact markup cannot replace the first policy', () => {
    const hostile = '<meta http-equiv="Content-Security-Policy" content="default-src *"><base href="https://example.invalid/"><form action="https://example.invalid/"></form>';
    const result = sandbox(hostile), policy = directives(result);
    for (const name of ['default-src', 'connect-src', 'form-action', 'base-uri']) {
        assert.deepEqual(policy.get(name), ["'none'"]);
    }
    assert.ok(!policy.get('script-src').some(value => ['*', "'self'", "'unsafe-eval'", 'http:', 'https:'].includes(value)));
    assert.ok(result.endsWith(hostile));
    assert.equal(result.indexOf('default-src *') > result.indexOf("default-src 'none'"), true);
});

test('undefined and null documents retain a restrictive policy without literal null content', () => {
    const empty = sandbox('');
    assert.equal(sandbox(undefined), empty);
    assert.equal(sandbox(null), empty);
    assert.deepEqual(directives(empty).get('default-src'), ["'none'"]);
});

test('all live and popped-out previews use the CSP helper in opaque script-enabled sandboxed iframes', () => {
    const app = fs.readFileSync(path.join(root, 'app/static/js/app.js'), 'utf8');
    const template = fs.readFileSync(path.join(root, 'app/templates/index.html'), 'utf8');
    assert.match(template, /id="artifact-frame"[^>]*sandbox="allow-scripts allow-modals"/);
    assert.match(app, /frame\.srcdoc\s*=\s*sandboxArtifactDocument\(artifact\.combined\)/);
    assert.match(app, /iframe\.srcdoc\s*=\s*sandboxArtifactDocument\(htmlContent\)/);
    const frames = [...app.matchAll(/<iframe\b[^>]*sandbox="([^"]+)"[^>]*>/g)];
    assert.equal(frames.length, 3, 'overlay and two new-tab preview paths are all covered');
    for (const [, flags] of frames) {
        assert.ok(flags.split(/\s+/).includes('allow-scripts'));
        assert.ok(!flags.split(/\s+/).includes('allow-same-origin'));
        assert.ok(!flags.split(/\s+/).includes('allow-forms'));
        assert.ok(!flags.split(/\s+/).includes('allow-top-navigation'));
    }
    assert.equal([...app.matchAll(/escapeAttr\(sandboxArtifactDocument\(/g)].length, 2);
});
