export const INSTALL_STORAGE_KEY = 'olga-companion.example-install.v1';

const EXAMPLE_ERROR_KEYS = {
  'Unknown example.': 'examples.unknown',
  'Example topology is not available.': 'examples.unknown',
  'The bundled air-water table is missing.': 'examples.tableMissing',
  'Example file name is not safe.': 'examples.nameUnsafe',
  'No free file name left in the workspace.': 'examples.noFreeName',
  'Installed example failed the validator.': 'examples.rejected',
  'Example case spec did not validate.': 'examples.rejected',
  'Example case spec did not compile.': 'examples.rejected',
  'Example topology did not validate.': 'examples.rejected',
  'The workspace folder is not writable.': 'examples.notWritable',
};

let exampleWorkspaceRoot = '';
let exampleInstallBusy = null;
const exampleInstallListeners = new Set();

function browserStorage() {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

function notifyExampleInstall() {
  for (const listener of exampleInstallListeners) listener();
}

export function setExampleWorkspaceRoot(root) {
  exampleWorkspaceRoot = root;
}

export function claimExampleInstall(id) {
  if (exampleInstallBusy !== null) return false;
  exampleInstallBusy = id;
  notifyExampleInstall();
  return true;
}

export function releaseExampleInstall(id) {
  if (exampleInstallBusy !== null && exampleInstallBusy !== id) return;
  exampleInstallBusy = null;
  notifyExampleInstall();
}

export function getExampleInstallBusy() {
  return exampleInstallBusy;
}

export function subscribeExampleInstallBusy(listener) {
  exampleInstallListeners.add(listener);
  return () => { exampleInstallListeners.delete(listener); };
}

export function exampleErrorKey(message) {
  return EXAMPLE_ERROR_KEYS[message] ?? 'examples.installFailed';
}

export function rememberExampleInstall(installed, storage = browserStorage(), workspaceRoot = exampleWorkspaceRoot) {
  try {
    storage?.setItem(INSTALL_STORAGE_KEY, JSON.stringify({
      version: 2,
      id: installed.id,
      caseName: installed.case_name,
      demo: installed.demo === true,
      workspaceRoot,
    }));
  } catch {
    return;
  }
}

export function loadRememberedExample(storage = browserStorage(), workspaceRoot = exampleWorkspaceRoot) {
  try {
    const raw = storage?.getItem(INSTALL_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed.version !== 2 || typeof parsed.id !== 'string' || typeof parsed.caseName !== 'string') return null;
    if (typeof parsed.workspaceRoot !== 'string' || parsed.workspaceRoot !== workspaceRoot) return null;
    return { id: parsed.id, caseName: parsed.caseName, demo: parsed.demo === true };
  } catch {
    return null;
  }
}
