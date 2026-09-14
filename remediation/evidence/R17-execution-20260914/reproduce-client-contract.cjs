// Offline replay only: no network and no changes to the running application.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const ts = require(path.join(root, 'web/node_modules/typescript'));
const cache = new Map();
function load(file) {
  const filename = path.resolve(file);
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = { exports: {} };
  cache.set(filename, mod);
  const source = fs.readFileSync(filename, 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  }}).outputText;
  const localRequire = id => {
    if (!id.startsWith('.')) throw new Error('Unexpected runtime import');
    return load(path.resolve(path.dirname(filename), id + '.ts'));
  };
  new Function('require', 'module', 'exports', compiled)(localRequire, mod, mod.exports);
  return mod.exports;
}
const { createAIPlanApi } = load(path.join(root, 'web/src/api/ai.ts'));
const responses = JSON.parse(fs.readFileSync(path.join(__dirname, 'observed-extractions.json'), 'utf8'));
async function replay(body) {
  const api = createAIPlanApi(async () => new Response(JSON.stringify(body), {
    status: 200, headers: { 'content-type': 'application/json' },
  }));
  try {
    const result = await api.getExtraction(body.id);
    return { accepted: true, status: result.status };
  } catch (error) {
    return { accepted: false, code: error.code, httpStatus: error.status };
  }
}
(async () => {
  const results = [];
  for (const body of responses) {
    const counterfactual = { ...body };
    delete counterfactual.diagnosticStatus;
    results.push({ operationId: body.id,
      actualResponse: await replay(body),
      offlineCounterfactualWithoutDiagnosticStatus: await replay(counterfactual),
    });
  }
  const report = { mode: 'OFFLINE_REAL_RESPONSE_REPLAY_NO_NETWORK', results };
  fs.writeFileSync(path.join(__dirname, 'client-contract-replay.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  if (results.some(x => x.actualResponse.accepted || !x.offlineCounterfactualWithoutDiagnosticStatus.accepted)) process.exitCode = 1;
})();
