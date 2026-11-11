import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';
import { currentLocale, loadLocale, saveLocale, setLocale, translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function throwingStorage() {
  return {
    getItem() { throw new Error('denied'); },
    setItem() { throw new Error('denied'); },
  };
}

function memoryStorage(initial) {
  const store = new Map(Object.entries(initial ?? {}));
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => { store.set(key, String(value)); },
  };
}

test('every ko dictionary key exists in en', async () => {
  const koKeys = Object.keys(ko).sort();
  const enKeys = Object.keys(en).sort();
  assert.ok(koKeys.length > 0, 'ko dictionary is not empty');
  assert.deepEqual(enKeys, koKeys, 'en must cover every ko key');
});

test('locale defaults to ko and survives broken storage', async () => {
  assert.equal(loadLocale(memoryStorage()), 'ko');
  assert.equal(loadLocale(throwingStorage()), 'ko');
  assert.equal(loadLocale(memoryStorage({ 'olga-companion.locale.v1': 'xx' })), 'ko');
  assert.equal(loadLocale(memoryStorage({ 'olga-companion.locale.v1': JSON.stringify({ version: 1, locale: 'en' }) })), 'en');
});

test('switching locale persists and reloads', async () => {
  const storage = memoryStorage();
  assert.equal(saveLocale('en', storage), true);
  assert.equal(loadLocale(storage), 'en');
  assert.equal(saveLocale('ko', storage), true);
  assert.equal(loadLocale(storage), 'ko');
  assert.equal(saveLocale('en', throwingStorage()), false);
});

test('t() interpolates {vars} and falls back ko then key', async () => {
  assert.equal(translate('en', 'settings.digits', { count: 5 }), '5 digits');
  assert.equal(translate('ko', 'settings.digits', { count: 5 }), '5자리');
  assert.equal(translate('xx', 'nav.chat'), ko['nav.chat']);
});

test('final polish strings follow the chosen language', async () => {
  const [panel, settings] = await Promise.all([
    read('../src/ProviderPanel.tsx'),
    read('../src/SettingsView.tsx'),
  ]);
  assert.equal(translate('ko', 'settings.current'), '현재');
  assert.equal(translate('en', 'settings.current'), 'Current');
  assert.match(settings, /t\('settings\.current'\)/, 'workspace card label reads from the dictionary');
  assert.equal(translate('ko', 'sidebar.sectionMenu'), '메뉴');
  assert.equal(translate('en', 'sidebar.sectionMenu'), 'Menu');
  assert.equal(translate('ko', 'provider.apikeyName'), 'API 키');
  assert.equal(translate('en', 'provider.apikeyName'), 'API key');
  assert.match(panel, /providerDisplayLabel\(p\.provider, locale\)/, 'provider select passes the live locale');
  assert.match(settings, /providerDisplayLabel\(candidate\.provider, locale\)/, 'account rows pass the live locale');
  assert.match(panel, /if \(providerId === 'apikey'\) return translate\(locale, 'provider\.apikeyName'\)/, 'apikey label resolves per locale');
});

test('switching locale renders approval buttons in the chosen language', async () => {
  const storage = memoryStorage();
  assert.equal(saveLocale('en', storage), true);
  assert.equal(loadLocale(storage), 'en');
  setLocale('en');
  try {
    assert.equal(currentLocale(), 'en');
    assert.equal(translate('en', 'approval.approveRun'), 'Approve and run');
    assert.equal(translate('en', 'approval.previewCommand'), 'Preview command');
  } finally {
    setLocale('ko');
  }
  assert.equal(currentLocale(), 'ko');
  assert.equal(saveLocale('ko', storage), true);
  assert.equal(loadLocale(storage), 'ko');
  assert.equal(translate('ko', 'approval.approveRun'), '승인하고 실행');
  assert.equal(translate('ko', 'approval.previewCommand'), '명령 미리보기');
});

test('settings exposes a language card that re-renders on switch', async () => {
  const [settings, koSource, enSource] = await Promise.all([
    read('../src/SettingsView.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(settings, /settings-card language-card/, 'language card exists');
  assert.match(settings, /t\('language\.title'\)/, 'language card title comes from the dictionary');
  assert.match(settings, /useLocale/, 'settings reads the locale');
  assert.match(settings, /id="ui-language"/, 'language select has a stable label target');
  assert.match(settings, /t\(option\.labelKey\)/, 'both language options render from the dictionary');
  assert.match(settings, /setLocale\(next\)/, 'switching calls setLocale');
  assert.match(settings, /parseLocale\(event\.target\.value\)/, 'unknown option values cannot corrupt the locale');
  assert.match(koSource, /'language\.title': '언어 \/ Language'/, 'ko keeps the bilingual card title');
  assert.match(koSource, /'language\.korean': '한국어'/, 'ko option label exists');
  assert.match(enSource, /'language\.english': 'English'/, 'en option label exists');
  assert.doesNotMatch(settings, />한국어<\/option>|>English<\/option>/, 'option labels are not hardcoded');
});

test('app shell sets document language and reads the locale', async () => {
  const [app, index] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/i18n/index.ts'),
  ]);
  assert.match(app, /useLocale/, 'app re-renders on locale change');
  assert.match(index, /document\.documentElement\.lang/, 'document language follows the locale');
  assert.match(index, /currentLocale/, 'non-React helper is exposed');
});

test('nav and status labels come from the dictionary', async () => {
  const [app, bar, rail, status, koSource, enSource] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/WorkspaceBar.tsx'),
    read('../src/shell/ActivityBar.tsx'),
    read('../src/shell/StatusBar.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(rail, /t\(`nav\.\$\{view\}`\)/, 'activity bar reads every view label from the dictionary');
  assert.match(app, /t\('status\.disconnected'\)/, 'unavailable model reads from the dictionary');
  assert.match(app, /t\('status\.skipLink'\)/, 'skip link reads from the dictionary');
  assert.match(status, /t\('status\.aiModel'\)/, 'status-bar model kicker reads from the dictionary');
  assert.match(bar, /t\('status\.caseContext'\)/, 'status bar case context is translated');
  assert.match(koSource, /채팅/, 'ko nav labels exist');
  assert.match(koSource, /'status\.caseContext': '케이스 맥락'/, 'ko case context exists');
  assert.match(enSource, /Conversation/, 'en chat header copy exists');
  assert.doesNotMatch(app, /label: 'Chat'|label: 'Workspace'|label: 'Results'|label: 'Run'|label: 'Settings'/, 'nav labels are not hardcoded');
});

test('chat header, composer, provider panel and env drawer read from the dictionary', async () => {
  const [chat, panel, drawer, settings] = await Promise.all([
    read('../src/ChatView.tsx'),
    read('../src/ProviderPanel.tsx'),
    read('../src/EnvDrawer.tsx'),
    read('../src/SettingsView.tsx'),
  ]);
  for (const key of ['chat.conversation', 'chat.conversationActions', 'chat.newChat', 'chat.startNewChat']) {
    assert.match(chat, new RegExp(`t\\('${key.replace('.', '\\.')}'\\)`), `chat header uses ${key}`);
  }
  for (const key of ['composer.question', 'composer.questionLabel', 'composer.placeholderReady', 'composer.placeholderConnecting', 'composer.hint', 'composer.clear', 'composer.clearAction', 'composer.send']) {
    assert.match(chat, new RegExp(`t\\('${key.replace('.', '\\.')}'\\)`), `composer uses ${key}`);
  }
  for (const key of ['provider.provider', 'provider.model', 'provider.connection', 'provider.effort', 'provider.notConnectedSuffix', 'provider.disconnectedNotice']) {
    assert.match(panel, new RegExp(`t\\('${key.replace('.', '\\.')}'\\)`), `provider panel uses ${key}`);
  }
  for (const key of ['env.systemStatus', 'env.closeTitle', 'env.openTitleConnected', 'env.openTitleOffline', 'env.ariaOpen', 'env.ariaClose', 'env.runtime', 'env.aiModel', 'env.available', 'env.gated', 'env.hint']) {
    assert.match(drawer, new RegExp(`t\\('${key.replace('.', '\\.')}'`), `env drawer uses ${key}`);
  }
  for (const key of ['settings.title', 'settings.lede', 'settings.providerTitle', 'settings.accounts', 'settings.apikeyTitle', 'settings.workspaceTitle', 'settings.numericTitle']) {
    assert.match(settings, new RegExp(`t\\('${key.replace('.', '\\.')}'\\)`), `settings view uses ${key}`);
  }
  assert.doesNotMatch(chat, />Conversation<|>New chat<|질문 비우기|>전송</, 'moved chat strings are not hardcoded');
  assert.doesNotMatch(panel, /이 공급자는 연결되어 있지 않습니다/, 'moved provider notice is not hardcoded');
  assert.doesNotMatch(drawer, />System status<|>Available<|>Gated</, 'moved drawer labels are not hardcoded');
  assert.doesNotMatch(settings, />AI 공급자<|>계정 연결<|>유효 숫자</, 'moved settings strings are not hardcoded');
});

test('approval, tool, history, native, update, apikey and xai surfaces read from the dictionary', async () => {
  const [card, tool, menu, actions, update, apikey, outcomes, xai, run] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/ToolUnit.tsx'),
    read('../src/SessionMenu.tsx'),
    read('../src/NativeContextActions.tsx'),
    read('../src/UpdatePanel.tsx'),
    read('../src/ApiKeyConnections.tsx'),
    read('../src/apiKeyOutcomes.ts'),
    read('../src/XaiConnectPanel.tsx'),
    read('../src/RunSingleCasePanel.tsx'),
  ]);
  const uses = (source, keys) => {
    for (const key of keys) {
      assert.match(source, new RegExp(`t\\('${key.replace('.', '\\.')}'`), `uses ${key}`);
    }
  };
  uses(card, ['approval.title', 'approval.headPublish', 'approval.publishRefused', 'approval.runRefused',
    'approval.resolvedTitle', 'approval.resolvedContextExpired', 'approval.resolvedRejected', 'approval.resolvedClosed',
    'approval.expiredTitle', 'approval.expiredLine', 'approval.validUntil', 'approval.lifecycleFinalizing',
    'approval.lifecycleWorking', 'approval.fieldCase', 'approval.fieldTransaction', 'approval.fieldTimeout',
    'approval.timeoutSeconds', 'approval.hintNoDisplay', 'approval.hintPublish', 'approval.hintRun',
    'approval.hintHuman', 'approval.inputsTitle', 'approval.inputsNote', 'approval.stickyTarget',
    'approval.stickyAsIs', 'approval.approvePublish', 'approval.approveRun', 'approval.reject',
    'approval.retryContinuation']);
  uses(tool, ['approval.expiredTitle']);
  for (const key of ['tool.ariaOpen', 'tool.ariaClosed', 'tool.ariaPlain']) {
    assert.match(tool, new RegExp(`'${key.replace('.', '\\.')}'`), `tool uses ${key}`);
  }
  uses(menu, ['chat.chats', 'history.openHistory', 'history.closeHistory', 'history.historyTitle',
    'history.searchResults', 'history.savedConversations', 'history.searchAria', 'history.searchPlaceholder',
    'history.noPastChats', 'history.noChatsMatch', 'history.tryTitleOrId', 'history.loadMore',
    'history.cannotDeleteActive', 'history.deleteChat', 'history.deleteChatTitle', 'history.untitled']);
  for (const key of ['native.actions', 'native.pickWorkspace', 'native.openCase', 'native.choosingWorkspace',
    'native.openingCase', 'native.completeDialog', 'native.cancel', 'native.cancelling', 'native.dialogFailed',
    'native.workspaceSelected', 'native.caseOpened', 'native.workspaceWord', 'native.caseWord',
    'native.selectionCancelled', 'native.noContextChanged', 'native.casesAvailableOne', 'native.casesAvailableOther',
    'native.activeCase', 'native.dialogUnavailable', 'native.cancelUnavailable', 'native.cancelFailed', 'native.dialogClosed']) {
    assert.match(actions, new RegExp(`'${key.replace('.', '\\.')}'`), `actions uses ${key}`);
  }
  uses(update, ['update.title', 'update.note', 'update.installed', 'update.check', 'update.checking',
    'update.downloadVersion', 'update.installRestart', 'update.progressAria', 'update.readyToInstall',
    'update.installing', 'update.idle', 'update.connecting', 'update.current', 'update.available',
    'update.unsupported', 'update.backendStopped']);
  for (const key of ['update.checkFailed', 'update.downloadStale', 'update.installStale']) {
    assert.match(update, new RegExp(`'${key.replace('.', '\\.')}'`), `update uses ${key}`);
  }
  uses(apikey, ['apikey.label', 'apikey.listFailed',
    'apikey.savedMeta', 'apikey.verified', 'apikey.verifyAction', 'apikey.verifying',
    'apikey.deleteConfirm', 'apikey.deleteAction', 'apikey.nameLabel', 'apikey.protocolLabel',
    'apikey.baseUrlLabel', 'apikey.modelLabel', 'apikey.keyLabel', 'apikey.save', 'apikey.saving']);
  for (const key of ['apikey.saveFailed', 'apikey.verifyFailed', 'apikey.deleteFailed']) {
    assert.match(apikey, new RegExp(`'${key.replace('.', '\\.')}'`), `apikey uses ${key}`);
  }
  assert.match(outcomes, /translate\(locale/, 'outcome sentences resolve through the dictionary');
  uses(xai, ['xai.aria', 'xai.codeAria', 'xai.openBrowser', 'xai.starting', 'xai.loginFailed',
    'xai.logoutFailed']);
  for (const key of ['xai.titleIdle', 'xai.titleStarting', 'xai.titlePending', 'xai.titleConnected',
    'xai.titleDenied', 'xai.titleExpired', 'xai.titleError', 'xai.actionConnect', 'xai.actionRestart',
    'xai.actionDisconnect']) {
    assert.match(xai, new RegExp(`'${key.replace('.', '\\.')}'`), `xai uses ${key}`);
  }
  uses(run, ['approval.previewCommand', 'approval.approveRun']);
  assert.doesNotMatch(card, /Approve &(?:amp;)? (?:publish|run)|>Reject<|Retry continuation/, 'moved approval buttons are not hardcoded');
  assert.doesNotMatch(card, /승인 필요 —|입력값 확인<\/strong>|어시스턴트가 대신/, 'moved approval copy is not hardcoded');
  assert.doesNotMatch(tool, /'Collapse'|'Expand'|presentation\.label/, 'moved tool labels are not hardcoded');
  assert.doesNotMatch(menu, />Chats<|Chat history|No past chats/, 'moved history copy is not hardcoded');
  assert.doesNotMatch(actions, />Open case…<|작업 공간 고르기…<|Native dialog failed/, 'moved native copy is not hardcoded');
  assert.doesNotMatch(update, /업데이트 확인<|설치 후 다시 시작<|아직 확인 안 함/, 'moved update copy is not hardcoded');
  assert.doesNotMatch(apikey, /연결 확인<|삭제 확인<|저장됨 · 끝/, 'moved apikey copy is not hardcoded');
  assert.doesNotMatch(xai, /브라우저에서 열기<|xaiConnectCopy/, 'moved xai copy is not hardcoded');
  assert.doesNotMatch(run, />Preview command<|>Approve and run</, 'moved run approval buttons are not hardcoded');
});

test('sweep surfaces (evidence, workbench chrome, offline boundary) read from the dictionary', async () => {
  const [app, bar, chat, artifact, casespec, inspect, lifecycle, empty, sim, stepbar, intake, sidebar, resize, queue, runtime, offline] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/TitleBar.tsx'),
    read('../src/ChatView.tsx'),
    read('../src/ArtifactCard.tsx'),
    read('../src/CaseSpecEvidence.tsx'),
    read('../src/InspectionEvidence.tsx'),
    read('../src/LifecycleEvidence.tsx'),
    read('../src/EmptyState.tsx'),
    read('../src/SimulationGuide.tsx'),
    read('../src/shell/StepBar.tsx'),
    read('../src/NewCaseChecklist.tsx'),
    read('../src/Sidebar.tsx'),
    read('../src/PanelResizeHandle.tsx'),
    read('../src/QueuedMessages.tsx'),
    read('../src/RuntimeNavStatus.tsx'),
    read('../src/RuntimeUnavailableView.tsx'),
  ]);
  const uses = (source, keys) => {
    for (const key of keys) {
      assert.match(source, new RegExp(`t\\('${key.replace('.', '\\.')}'`), `uses ${key}`);
    }
  };
  uses(app, ['app.workbench']);
  uses(bar, ['app.homeAria']);
  uses(chat, ['chat.thinking']);
  uses(artifact, ['artifact.unavailable']);
  uses(casespec, ['casespec.summary', 'casespec.conn', 'casespec.nodesPipes', 'casespec.shape',
    'casespec.pipesSections', 'casespec.syntax', 'casespec.values', 'casespec.pass', 'casespec.review',
    'casespec.unknown', 'casespec.errors', 'casespec.warnings', 'casespec.audit']);
  uses(inspect, ['inspect.genkeyReview', 'inspect.techBasis', 'inspect.pvtLine', 'inspect.pvtComposition',
    'inspect.techEvidence']);
  uses(lifecycle, ['lifecycle.audit']);
  uses(empty, ['empty.title', 'empty.lede', 'empty.quickTitle', 'empty.quickNote', 'empty.startersAria']);
  uses(sim, ['sim.title', 'sim.subtitle', 'sim.detailAria', 'sim.checkTitle', 'sim.note']);
  uses(stepbar, ['sim.stepsAria']);
  uses(intake, ['intake.title', 'intake.lede']);
  uses(sidebar, ['sidebar.navAria', 'sidebar.creditAria', 'sidebar.creditLabel', 'sidebar.githubAria',
    'sidebar.resizeLabel', 'sidebar.sectionMenu']);
  uses(resize, ['resize.hint']);
  uses(queue, ['queue.title', 'queue.upNext', 'queue.count']);
  uses(runtime, ['runtime.label', 'runtime.retryAria', 'runtime.retry', 'runtime.retrying']);
  for (const key of ['runtime.connectingTitle', 'runtime.offlineTitle', 'runtime.connectingState', 'runtime.offlineState']) {
    assert.match(runtime, new RegExp(`'${key.replace('.', '\\.')}'`), `runtime uses ${key}`);
  }
  uses(offline, ['offline.boundaryAria', 'offline.navAvailable', 'offline.navAvailableDetail',
    'offline.pauseTitle', 'offline.pauseDetail', 'offline.retry', 'offline.stillOpen', 'offline.connectionState',
    'offline.offline', 'offline.connecting']);
  for (const key of ['offline.kickerWorkspace', 'offline.titleWorkspace', 'offline.descWorkspace',
    'offline.kickerResults', 'offline.titleResults', 'offline.descResults',
    'offline.kickerRun', 'offline.titleRun', 'offline.descRun',
    'offline.kickerSettings', 'offline.titleSettings', 'offline.descSettings']) {
    assert.match(offline, new RegExp(`'${key.replace('.', '\\.')}'`), `offline view uses ${key}`);
  }
  assert.doesNotMatch(app, /aria-label="Return to OLGA home"|\{view\} workbench/, 'moved app chrome is not hardcoded');
  assert.doesNotMatch(chat, /<summary>Thinking<\/summary>/, 'moved thinking label is not hardcoded');
  assert.doesNotMatch(artifact, /Artifact receipt is unavailable/, 'moved artifact notice is not hardcoded');
  assert.doesNotMatch(casespec, /사례 명세 요약|문법 검사|값 검사|감사 기록/, 'moved casespec copy is not hardcoded');
  assert.doesNotMatch(inspect, /GENKEY 검토|기술 근거|Technical evidence/, 'moved inspection copy is not hardcoded');
  assert.doesNotMatch(empty, /처음부터 결과까지|빠른 작업 <span>|Starter commands/, 'moved empty-state copy is not hardcoded');
  assert.doesNotMatch(sim, /시뮬레이션 시작 안내|작업 선택|확인할 근거/, 'moved guide copy is not hardcoded');
  assert.doesNotMatch(sidebar, /aria-label="Workspaces"|>Designed by<|Resize primary navigation/, 'moved sidebar copy is not hardcoded');
  assert.match(sidebar, /className="sidebar-nav-heading"[^>]*>\{t\('sidebar\.sectionMenu'\)\}</, 'section heading renders from the dictionary');
  assert.doesNotMatch(sidebar, /content:\s*'WORKSPACE'|>WORKSPACE</, 'no hardcoded English section heading remains');
  assert.doesNotMatch(queue, /Up next|Queued messages/, 'moved queue copy is not hardcoded');
  assert.doesNotMatch(runtime, />Runtime<|>Retry<\/Button>/, 'moved runtime copy is not hardcoded');
  assert.doesNotMatch(offline, /Navigation stays available|Sidecar-backed actions pause|Retry sidecar<\/Button>/, 'moved offline copy is not hardcoded');
});
