<div align="center">

<a id="olga-companion"></a>

<picture>
  <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="./docs/assets/readme/cover-dark.png" />
  <source media="(prefers-reduced-motion: reduce)" srcset="./docs/assets/readme/cover-light.png" />
  <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/readme/cover-dark.webp" />
  <img src="./docs/assets/readme/cover-light.webp" width="100%" alt="OLGA Companion. 앱의 다섯 단계(사례 만들기, 조건 수정, 실행 전 확인, 승인·실행, 결과 분석)가 차례로 켜지고, 옆의 승인 카드가 채워지고 확인되고 승인되어 실행된 뒤 압력 곡선이 그려집니다." />
</picture>

<h1>OLGA Companion</h1>

<p><b>다상 배관을 평소 말로 설명하고, 단계마다 승인하고, OLGA를 돌리고, 답을 읽습니다.</b></p>

<p><a href="./README.md">English</a> · <b>한국어</b></p>

<p>
  <a href="https://github.com/wjgoarxiv/olga-companion/releases/latest"><img src="https://img.shields.io/github/v/release/wjgoarxiv/olga-companion?label=release&color=7aa2f7" alt="최신 릴리스" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20x64-0a7ea4" alt="Windows x64" />
  <img src="https://img.shields.io/badge/tested%20with-OLGA%202022.1-2ac3de" alt="OLGA 2022.1에서 시험함" />
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0" /></a>
  <img src="https://img.shields.io/badge/UI-English%20%7C%20%ED%95%9C%EA%B5%AD%EC%96%B4-9ece6a" alt="영어와 한국어 화면" />
</p>

<p>
  <a href="#quick-start">빠른 시작</a> ·
  <a href="#try-the-tutorial">튜토리얼</a> ·
  <a href="https://wjgoarxiv.github.io/olga-companion/intro.html">소개 슬라이드</a> ·
  <a href="#five-steps">다섯 단계</a> ·
  <a href="#features">기능</a> ·
  <a href="#safety-model">안전 장치</a> ·
  <a href="#faq">자주 묻는 질문</a> ·
  <a href="#documentation">문서</a> ·
  <a href="#contributing">참여하기</a>
</p>

</div>

OLGA Companion은 OLGA를 쓰는 엔지니어와 OLGA를 배우는 사람을 위한 Windows 데스크톱 앱입니다. AI 어시스턴트와 대화하면 어시스턴트가 내 PC에서 실제 OLGA 사례를 만들고, 검증하고, 실행합니다. **파일 쓰기, 사례 저장, 시뮬레이션 시작처럼 결과가 남는 일은 모두 승인 카드에서 멈추고 사용자의 클릭을 기다립니다. 어시스턴트가 대신 승인할 수는 없습니다.**

<a id="quick-start"></a>

## 빠른 시작

1. [최신 릴리스](https://github.com/wjgoarxiv/olga-companion/releases/latest)에서 Windows 설치 파일(`_x64-setup.exe` 또는 `.msi`)을 내려받습니다.
2. 설치 파일을 실행합니다. WebView2가 없으면 설치 중에 함께 받습니다.
3. **OLGA Companion**을 열고 **설정**에서 AI 공급자를 연결한 뒤, 사례를 둘 폴더를 고릅니다.
4. 제목 표시줄의 **튜토리얼**을 누르면 첫 사례를 일곱 단계로 안내합니다.

> [!IMPORTANT]
> 설치 파일에는 아직 코드 서명이 없어서 Windows SmartScreen이 경고할 수 있습니다. 실행하기 전에 릴리스에 첨부된 `SHA256SUMS.txt`와 SHA-256 값을 비교하세요.

<a id="try-the-tutorial"></a>

## 튜토리얼 체험하기

<a href="https://wjgoarxiv.github.io/olga-companion/tutorial/">
  <picture>
    <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="./docs/assets/readme/tutorial-preview-dark.png" />
    <source media="(prefers-reduced-motion: reduce)" srcset="./docs/assets/readme/tutorial-preview-light.png" />
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/readme/tutorial-preview-dark.webp" />
    <img src="./docs/assets/readme/tutorial-preview-light.webp" width="100%" alt="체험용 튜토리얼 페이지. 강조 표시가 작업 공간 막대, 데모 사례, 검증 버튼, 문제 패널, 실행 미리보기와 승인, 진행 막대, 결과 그래프로 차례로 옮겨 갑니다." />
  </picture>
</a>

**[브라우저에서 튜토리얼 열기](https://wjgoarxiv.github.io/olga-companion/tutorial/)**. 앱 화면을 그대로 옮긴 연습용 페이지라 직접 눌러 보며 따라갈 수 있습니다. 화면 배치, 색, 단계 막대, 승인 카드, 움직임이 앱과 같고, 두 길 모두 앱 안의 **튜토리얼** 버튼과 같은 일곱 단계를 따라갑니다. OLGA나 AI 공급자에는 연결하지 않으며, 나오는 값은 모두 연습용으로 만든 값입니다.

- **두 가지 길.** “데모로 둘러보기”는 연습용 공기–물 수평관을 설치해 검증부터 결과까지 이어 갑니다. “내 배관표로 시작”은 배관표 마법사(표 고르기 → 내용 확인 → 끝점 값 → 요청 넣기)로 요청을 보내고, 저장 카드를 승인한 뒤, 표에 적힌 이름 그대로 검증·실행하고 분리기 유량을 읽습니다.
- **앱에만 있는 세 번째 길.** 앱 안의 **튜토리얼** 버튼에는 “따라 하기: 값 하나 바꾸기”도 있습니다. 데모 사례의 끝 시간을 수정 표에서 바꾸고, 사본을 승인해 실행한 뒤 결과를 읽는 여섯 단계 수업입니다. 검증 단계가 없고 웹 페이지에는 없습니다.
- **오프라인 사본.** 같은 페이지가 [`docs/tutorial/index.html`](./docs/tutorial/index.html)에 있습니다. 저장소를 내려받아 이 파일을 브라우저로 열면 서버나 네트워크 없이 동작합니다.
- **밝은 화면, 어두운 화면, 움직임 끄기.** 페이지 위쪽에 테마 전환과 움직임 설정(끔 / 은은함 / 전체)이 있습니다. 직접 고르기 전까지는 시스템 설정을 따릅니다.
- 튜토리얼 문구는 앱의 한국어 화면에서 그대로 가져왔습니다.

<a id="five-steps"></a>

## 다섯 단계로 끝내는 첫 시뮬레이션

앱 위쪽의 단계 막대가 지금 어디에 있고 다음에 무엇을 할지 늘 보여 줍니다.

| 단계 | 할 일 | 끝나면 보이는 것 |
|---|---|---|
| **1. 사례 만들기** | 대화로 배관을 설명하거나, 데모를 설치하거나, 배관표로 사례를 만듭니다. | 사례가 작업 공간에 저장되고 열립니다. |
| **2. 조건 수정** | 작업 공간 화면에서 **값 고치기**를 눌러 숫자를 직접 바꾸거나, 채팅으로 평소 쓰는 단위로 요청합니다. 어느 쪽이든 바뀐 부분을 확인하고 저장을 승인합니다. | 검토를 거친 새 사본이 생깁니다. 원래 `.genkey`는 그 자리에서 바뀌지 않습니다. |
| **3. 실행 전 확인** | 제목 표시줄의 **검증**을 누릅니다. 실행 전에 사례를 점검합니다. | 문제 패널에 이 사례의 오류와 경고가 나옵니다. |
| **4. 승인·실행** | 실행 화면에서 실제로 실행될 명령을 미리 보고, **승인하고 실행**을 직접 누릅니다. | 진행 상황, 제한 시간, 중지 버튼이 보입니다. |
| **5. 결과 분석** | **결과**를 엽니다. | 실행에서 나온 `.tpl`, `.ppl` 파일의 시간 추이와 배관 길이 방향 분포를 그래프와 CSV로 볼 수 있습니다. |

실제 대화를 줄여서 옮겼습니다. 숫자는 앱과 OLGA가 낸 값 그대로입니다.

```text
나        OLGA는 처음입니다. 물 4 kg/s와 공기 0.05 kg/s가 수평 강관을 흐릅니다.
          길이 1.5 km, 내경 120 mm, 출구 4 bar(a), 30 °C입니다.
          압력은 얼마나 떨어지나요?

어시스턴트  닫힌 입구에 질량 유량 공급 하나(4.05 kg/s, 물 분율 4/4.05 = 0.987654),
          강관 거칠기 4.5e-5 m, 50개 구간, 3600 s, 범용 공기-물 표 사본을
          제안합니다. 그리고 사용자의 승인을 기다립니다.

나        네, 제안대로 해 주세요.

          [승인: 표 쓰기]  [승인: 사례 저장]  [승인: OLGA 실행]

어시스턴트  첫 구간 447 916.6 Pa, 마지막 구간 400 423.8 Pa이므로 압력 강하는
          47 492.8 Pa(0.475 bar)입니다. 범용 표를 썼으니 첫 추정치로 보세요.
```

<a id="features"></a>

## 기능

<table>
<tr>
<td width="50%" valign="top">

**대화로 사례 만들기**<br />
배관, 유량, 출구 조건을 평소 쓰는 단위로 말하면 됩니다. 어시스턴트가 단위를 바꾸고, 빠진 값(거칠기, 구간 수, 종료 시간)은 이유와 함께 제안하며, 채우기 전에 먼저 묻습니다.

</td>
<td width="50%" valign="top">

**승인 카드**<br />
쓰기, 저장, 실행마다 압력, 유량, 분율, 좌표 같은 입력값을 그대로 보여 줍니다. **승인**을 누르기 전에는 아무 일도 일어나지 않습니다. 승인은 한 번만 쓸 수 있고 10분이 지나면 만료됩니다.

</td>
</tr>
<tr>
<td><img src="./assets/screens/01-chat.png" alt="사례를 저장하기 전에 모든 입력값을 보여 주는 승인 카드" /></td>
<td><img src="./assets/screens/04-run.png" alt="실행 조작부와 끝난 실행의 기록" /></td>
</tr>
<tr>
<td valign="top">

**실제 OLGA 실행**<br />
내 PC의 OLGA를 앱이 관리하는 별도 작업 폴더에서 실행합니다. 진행 상황, 제한 시간, 취소를 지원합니다. 단일 실행과 파라미터 스윕 모두 사용자의 승인을 기다립니다.

</td>
<td valign="top">

**확인할 수 있는 결과**<br />
`.tpl`의 시간 추이, `.ppl`의 배관 길이 방향 분포, 그래프, 원본 파일이 표시된 CSV 내보내기를 제공합니다. 어시스턴트는 실행 파일에서 읽은 값을 근거로 답합니다.

</td>
</tr>
<tr>
<td><img src="./assets/screens/02-workspace.png" alt=".genkey에서 그린 사례 네트워크" /></td>
<td><img src="./assets/screens/03-results.png" alt="배관 길이에 따른 압력과, 양 끝 압력을 담은 어시스턴트의 답" /></td>
</tr>
<tr>
<td valign="top">

**배관표와 사례 살펴보기**<br />
`.csv`나 `.xlsx` 배관표로 네 단계 마법사를 거쳐 네트워크를 만듭니다. 표에 없는 끝점 값만 묻고, 요청은 대화 입력창에 넣어 두기만 하고 보내지는 않습니다. OLGA를 열지 않고도 `.genkey`의 네트워크, 형상, 유체 표를 살펴볼 수 있습니다.

</td>
<td valign="top">

**유체 표와 내가 고른 AI**<br />
사례 옆의 `.mfl`로 OLGA에 함께 설치된 Multiflash 엔진을 써서 빠진 `.tab`을 만들거나, 이미 가진 물성값으로 `.tab`을 쓰거나, 함께 들어 있는 범용 공기–물 표로 시작합니다. OpenAI(Codex), GitHub Copilot, Antigravity(Gemini), xAI(Grok)를 연결하거나, OpenAI 호환 주소에 API 키를 추가할 수 있습니다. HD AIC는 미리 준비된 항목이 있어 주소를 채우고 내 키로 쓸 수 있는 모델 목록을 불러옵니다.

</td>
</tr>
<tr>
<td valign="top">

**어느 화면에서나 보이는 실행 진행 표시줄**<br />
OLGA가 도는 동안 단계 막대 아래 표시줄에 진행률, 계산된 시간, 걸린 시간, 남은 시간 추정이 나오고, 실행 화면 열기와 중지 버튼이 함께 있습니다. 다른 화면으로 옮겨도 그대로 남아 있고, 실행이 끝나면 **결과 열기**가 나옵니다.

</td>
<td valign="top">

**예제 모음**<br />
바로 돌려 볼 수 있는 공기-물 사례 11개입니다. 수평관 하나부터, 유정 세 곳이 매니폴드 두 개에서 합쳐져 라이저로 올라가는 사례까지 있습니다. 카드마다 사례의 배관 구성을 그림으로 보여 주고, 정해진 기준에 따른 난이도와 구성 요소 수, 기준 PC에서 실제로 돌려 잰 실행 시간을 함께 보여 줍니다.

</td>
</tr>
<tr>
<td><img src="./assets/screens/06-run-strip.png" alt="단계 막대 아래의 실행 진행 표시줄. 진행률, 계산된 시간, 걸린 시간, 중지 버튼" /></td>
<td><img src="./assets/screens/07-examples.png" alt="예제 모음. 카드마다 배관 구성 그림, 난이도, 구성 요소 수, 측정한 실행 시간이 있습니다" /></td>
</tr>
<tr>
<td colspan="2" valign="top">

**값을 직접 고치기**<br />
열린 사례에서 **값 고치기**를 누르면 어시스턴트 없이 종료 시간, 경계 압력과 온도, 질량 유량, 밸브 열림, 관 거칠기를 bar, °C, kg/s, %, mm 단위로 바꿀 수 있습니다. 어시스턴트가 고칠 때와 같은 검사를 거칩니다. 바꾼 사례를 컴파일하고 검증한 뒤 바뀌는 내용을 보여 주고, **승인하고 저장**을 눌러야 저장합니다. 결과는 원본 옆의 새 파일이고, 원본은 바뀌지 않습니다. 이 앱이 만들지 않은 사례는 표에서 끝 시간만 바꿀 수 있으니, 다른 값은 어시스턴트에게 요청하세요.

</td>
</tr>
<tr>
<td colspan="2"><img src="./assets/screens/08-edit-values.png" alt="값 고치기 표의 확인 화면. OUTLET 경계 압력이 5 bar에서 6 bar로 바뀌고, 검사를 통과한 사본과 승인하고 저장 버튼이 보인다" /></td>
</tr>
</table>

사례, 대화, 실행 기록은 내 PC에 저장됩니다. 대화창에 입력한 내용은 연결한 AI 공급자에게 전송됩니다. 화면은 영어와 한국어를 지원하고, 밝은/어두운 테마, 움직임 설정, 글자 크기 설정이 있습니다.

<a id="safety-model"></a>

## 안전 장치

OLGA Companion은 시뮬레이션 파일과 모델 출력을 믿을 수 없는 입력으로 다룹니다.

| 경계 | 동작 |
|---|---|
| OLGA 실행 | 실제로 실행될 명령을 미리 보여 주고 승인을 받아야 합니다. |
| 사례 저장 | 승인이 필요합니다. 원본 `.genkey`는 그 자리에서 바뀌지 않습니다. |
| 파일 쓰기 | 고른 작업 공간이나 앱 전용 작업 폴더 안에서만 씁니다. |
| 승인 | 한 번만 쓸 수 있고 10분 동안 유효하며, 대화 모델에는 보이지 않습니다. 어시스턴트는 승인 버튼을 누를 수 없습니다. |
| 네트워크 | 사이드카는 루프백 주소에서만 받으며, `/api/*`는 실행할 때마다 새로 만드는 세션 토큰이 있어야 합니다. AI 도구 연결(`/api/bridge/*`)은 그 대신 연결한 도구마다 따로 만든 비밀 값을 씁니다. |
| 결과 파일 | 읽기 전후에 해시를 비교하고, 읽는 사이에 바뀐 파일은 거부합니다. |
| 업데이트 | 기본값으로 앱이 시작한 직후 새 버전을 한 번 확인해 상태 표시줄에 알립니다. **설정 → 업데이트**에서 끌 수 있습니다. 내려받기와 설치는 각각 따로 눌러야 하며, 모든 릴리스는 앱에 들어 있는 공개 키로 검증합니다. |

전체 규칙은 [Safety Gates](docs/SAFETY_GATES.md)에 있습니다.

## AI 도구 연결

**설정 → AI 도구 연결**에서 Claude Code, Codex, Gemini CLI가 이 앱의 도구를 쓰게 할 수 있습니다. 사례와 결과는 바로 읽고, 쓰기·실행·중지는 앱의 승인 카드를 눌러야 진행됩니다.

- Codex와 Gemini CLI는 **연결**을 누르면 그 도구의 설정 파일에 항목 하나(`olga-companion`)만 추가하고, 원래 파일은 옆에 백업합니다. 연결한 뒤 도구를 다시 시작하세요.
- Claude Code는 **연결**을 누르면 터미널에 붙여 넣을 명령어를 보여 줍니다.
- 명령어에는 그 연결 전용 비밀 값이 들어 있으니 비밀번호처럼 다루세요. **다시 연결**하면 새 비밀 값이 생기고 이전 명령어는 더는 통하지 않습니다.

## 로컬 CLI 연결

이 PC(Windows)에 Claude Code가 설치되어 있고 로그인되어 있다면, 채팅의 AI로 그대로 쓸 수 있습니다. **설정 → AI 공급자**에서 **이 PC의 로컬 CLI**를 고르세요.

- **로그인은 Claude Code에 그대로 둡니다.** 앱은 `claude` 프로그램을 실행할 뿐 로그인 정보를 보지 않습니다. 토큰이나 키를 묻지도, 읽지도, 저장하지도 않습니다. 사용량은 본인 요금제나 키로 계산되고, 어느 쪽인지 패널에 표시됩니다.
- **로그인 방법.** PowerShell을 열고 `claude`를 실행해 로그인한 뒤 종료하세요. 그다음 패널에서 **확인**을 누릅니다.
- **확인 비용.** **확인**은 Claude Code로 아주 짧은 요청을 한 번 보내므로 요금제나 키 사용량이 조금 듭니다. 프로그램을 찾고 버전을 보여 주는 데는 비용이 없습니다.
- **안전 장치는 내장 어시스턴트와 같습니다.** Claude Code에는 이 앱의 도구만 주고, Claude Code 자체의 파일·셸 도구는 끕니다. 사례와 결과는 읽을 수 있지만, 쓰기·실행·중지는 대화를 멈추고 평소처럼 승인 카드를 띄웁니다. 직접 추가한 Claude Code 플러그인은 이 앱이 확인할 수 없습니다. 대화 중에 플러그인 도구가 나타나면 `isolation_failed`로 대화를 멈춥니다.
- **WSL은 지원하지 않습니다.** Claude Code를 Windows에 직접 설치하세요. WSL 안에만 설치된 것은 찾지 못합니다.

프로그램을 찾을 때 패널에 나올 수 있는 문제:

| 코드 | 뜻 |
|---|---|
| `not_installed` | 이 PC에서 Claude Code를 찾지 못했습니다. Windows에 설치한 뒤 **다시 찾기**를 누르세요. |
| `override_missing` | 저장해 둔 실행 파일 위치에 프로그램이 없습니다. 다시 설치한 뒤 **다시 찾기**를 누르세요. |
| `not_executable` | 실행 파일을 실행하지 못했습니다. 보안 프로그램이 막고 있을 수 있습니다. |
| `probe_timeout` | 버전 확인에 응답하지 않았습니다. 잠시 뒤 다시 확인하세요. |
| `version_too_old` | 버전이 너무 오래되었습니다. `claude update`로 업데이트하세요. |
| `flags_missing` | 이 버전에는 앱에 필요한 옵션이 없습니다. `claude update`로 업데이트하세요. |
| `cmd_shim_unsafe` | 설치 경로에 안전하게 넘길 수 없는 문자가 있습니다. 네이티브 설치(`claude.exe`)를 쓰세요. |

대화나 **확인** 중에 나올 수 있는 문제:

| 코드 | 뜻 |
|---|---|
| `not_logged_in` | 로그인되어 있지 않습니다. PowerShell에서 `claude`를 실행해 로그인하세요. |
| `login_expired` | 로그인이 만료되었습니다. 같은 방법으로 다시 로그인하세요. |
| `rate_limited` | 사용 한도에 도달했습니다. 한도가 풀린 뒤 다시 시도하세요. |
| `org_policy` | 조직 정책 때문에 요청이 거부되었습니다. 조직 관리자에게 문의하세요. |
| `network` | 인터넷에 연결하지 못했습니다. 네트워크나 프록시(설정 → 네트워크)를 확인하세요. |
| `timeout` | 제시간에 응답이 없어 대화를 멈췄습니다. |
| `cancelled` | 요청을 취소했습니다. |
| `crashed` | Claude Code가 예기치 않게 종료되었습니다. `claude --version`으로 설치를 확인하세요. |
| `output_too_large` | 응답이 너무 커서 멈췄습니다. 질문을 좁혀 보세요. |
| `bad_output` | 출력을 읽지 못했습니다. Claude Code를 업데이트하세요. |
| `isolation_failed` | Claude Code가 이 앱의 도구가 아닌 도구를 쓰려 해서 대화를 멈췄습니다. |
| `tools_unavailable` | 이 앱의 도구를 시작하지 못해 대화를 멈췄습니다. 앱을 다시 시작하고, 계속되면 보안 프로그램이 앱을 막고 있는지 확인하세요. |
| `unknown` | Claude Code에서 그 밖의 오류가 났습니다. |

## 앱 없이 쓰기 (Claude Code 플러그인)

앱을 띄우지 않고 Claude Code 안에서만 작업하고 싶다면 OLGA Companion을 플러그인으로 설치하세요. 앱과 같은 엔진, 같은 버전이 데스크톱 창 없이 돌아갑니다. Claude Code는 앱의 도구와 그 사용법을 담은 짧은 스킬을 받습니다.

Claude Code와 [uv](https://docs.astral.sh/uv/)가 필요합니다. 플러그인은 처음 시작할 때 `uvx`로 이 릴리스를 받아 옵니다.

```
claude plugin marketplace add wjgoarxiv/olga-companion
claude plugin install olga-companion@olga-companion
```

Claude Code 세션 안에서는 `/plugin marketplace add wjgoarxiv/olga-companion`, `/plugin install olga-companion@olga-companion`으로 같은 일을 합니다. 설치하지 않고 한 세션만 써 보려면 이 저장소를 받은 폴더에서 `claude --plugin-dir ./plugin`을 실행하세요.

- **파일은 작업하는 폴더에 생깁니다.** 도구는 Claude Code를 시작한 폴더에서 읽고 씁니다.
- **Claude Code의 권한 확인이 곧 승인입니다.** 쓰기, 실행, 중지를 하는 도구는 부를 때마다 권한을 묻습니다. 다른 확인을 건너뛰는 모드에서도 마찬가지입니다. 대화 없이 도는 `claude -p`에서는 승인할 방법이 없으므로 이 도구들이 거절됩니다.
- **쓰기는 언제나 새 파일입니다.** 기존 사례, 표, 결과는 덮어쓰지 않습니다. 실행은 사본을 새 폴더에서 돌립니다.
- **운영체제별로 되는 일.** 사례와 표를 읽고, 검사하고, 초안을 만드는 일은 Windows, macOS, Linux에서 됩니다. `.mfl`에서 PVT 표(`.tab`)를 만들고, OLGA를 실행하고, Multiflash를 여는 일은 두 프로그램이 설치된 Windows에서만 됩니다.
- **앱과 같은 엔진입니다.** 플러그인 버전은 항상 같은 앱 릴리스와 맞춰 나가므로, 한쪽에서 만든 사례가 다른 쪽에서도 똑같이 열립니다.

<a id="genuine-download"></a>

## 진짜 설치 파일인지 확인하기

OLGA Companion은 오픈소스라서 누구나 복사하고 다시 빌드할 수 있습니다. 만든 사람이 확인한 파일은 여기에 올린 것뿐입니다.

1. [릴리스 페이지](https://github.com/wjgoarxiv/olga-companion/releases)에서만 내려받으세요. 메일 첨부, 공유 드라이브, 다른 웹사이트에서 받은 파일은 바뀌었을 수 있습니다.
2. 설치 파일을 실행하기 전에 SHA-256 값을 같은 릴리스의 `SHA256SUMS.txt`에 적힌 값과 비교하세요. PowerShell에서:
   ```powershell
   Get-FileHash .\OLGA-Companion_<version>_x64-setup.exe -Algorithm SHA256
   ```
   두 값이 다르면 파일을 지우세요.
3. 설치한 뒤의 업데이트는 앱이 직접 검증합니다. 릴리스 키로 서명하지 않은 업데이트는 설치하지 않습니다.
   0.1.25부터는 앱이 스스로 업데이트합니다. 그보다 오래된 버전은 업데이트 키가 바뀌어 지금 릴리스를 검증할 수 없으니, 릴리스 페이지에서 최신 설치 파일을 받아 한 번 직접 실행하세요. 사례와 설정은 그대로 남습니다. 자세한 내용은 [Updater signing key](docs/UPDATER-KEY.md)에 있습니다.
4. **정보**(왼쪽 막대 맨 아래, 또는 `Ctrl+K` → 정보)에서 버전과 만든 사람, 그리고 이 앱이 SLB와 관계없다는 안내를 볼 수 있습니다. OLGA는 SLB의 제품이며, 이 앱은 SLB와 관계가 없고 SLB의 승인이나 후원을 받지 않았습니다.

이 페이지에서 받지 않았는데 OLGA Companion이라고 하는 파일을 보면 이슈로 알려 주세요.

## 필요한 것

| 항목 | 쓰이는 곳 | 비고 |
|---|---|---|
| Windows x64 | 전부 | OLGA가 Windows용 프로그램입니다 |
| OLGA | 실제 실행 | OLGA 2022.1에서 시험했습니다. 살펴보기와 결과 읽기는 OLGA 없이도 됩니다 |
| AI 공급자 | 대화 | OpenAI(Codex), GitHub Copilot, Antigravity(Gemini), xAI(Grok), 또는 API 키 |
| Multiflash | 선택 | 사례에 맞춘 유체 표. OLGA에 함께 들어 있는 Multiflash 엔진으로 앱이 `.mfl`에서 `.tab`을 만듭니다 |

<a id="faq"></a>

## 자주 묻는 질문과 문제 해결

<details>
<summary><b>Windows SmartScreen이 설치 파일을 막습니다.</b></summary>

지금은 서명하지 않은 설치 파일입니다. 릴리스 페이지의 `SHA256SUMS.txt`와 SHA-256 값을 비교한 뒤 **추가 정보 → 실행**을 고르세요.

</details>

<details>
<summary><b>이 PC에 OLGA가 없어도 앱을 쓸 수 있나요?</b></summary>

네. 사례를 만들고 검증하고, `.genkey`를 살펴보고, 이미 있는 `.tpl`/`.ppl` 결과를 읽을 수 있습니다. 시뮬레이션 실행에는 라이선스가 있는 OLGA가 PC에 설치되어 있어야 합니다. 앱이 OLGA를 찾지 못하면 앱 안의 튜토리얼은 실행 단계에서 멈춥니다.

</details>

<details>
<summary><b>어시스턴트가 멈추거나 빈 답을 보냈습니다.</b></summary>

AI 모델에서 가끔 생기는 일입니다. 앱이 다시 시도하라는 안내를 띄우고, 다시 물으면 하던 일을 이어 갑니다. 저장과 실행은 승인을 기다리므로 그 사이에 저장되거나 실행된 것은 없습니다.

</details>

<details>
<summary><b>회사 네트워크에서 답이 자꾸 끊깁니다.</b></summary>

**설정 → 네트워크**에서 관리자가 허용한 로컬 프록시로 공급자 통신을 보낼 수 있습니다. [Network](docs/NETWORK.md)를 참고하세요.

</details>

<details>
<summary><b>승인 카드가 만료되었다고 나옵니다.</b></summary>

카드는 10분 동안 유효하고 한 번만 쓸 수 있습니다. 어시스턴트에게 그 단계를 다시 제안해 달라고 한 뒤 새 카드를 승인하세요.

</details>

<details>
<summary><b>앱은 파일을 어디에 쓰나요?</b></summary>

사례와 표는 사용자가 고른 작업 공간 폴더에 씁니다. 실행은 앱이 관리하는 별도 작업 폴더의 사본에서 하므로 원본 사례는 그대로 남습니다.

</details>

<details>
<summary><b>소스에서 빌드하기와 Windows 패키지</b></summary>

Node.js 22.12 이상, Python 3.11 이상, `uv`가 필요합니다.

```bash
git clone https://github.com/wjgoarxiv/olga-companion.git
cd olga-companion
npm ci
uv sync --extra results --group dev
npm run verify         # 프론트엔드 테스트, 타입 검사, 빌드, 백엔드 테스트
npm run dev:app        # 프론트엔드 :5273, 사이드카 :8865
```

**Windows 패키지.** 설치 파일을 만들려면 Rust MSVC 도구 체인과 PyInstaller도 있어야 합니다. 설치 파일에는 데스크톱 셸, 묶어 놓은 Python 사이드카, OLGA 도구 스크립트가 들어 있고 OLGA는 들어 있지 않습니다. [Packaging Runbook](docs/PACKAGING.md)을 참고하세요.

</details>

<details>
<summary><b>알려진 한계</b></summary>

- **Windows 전용입니다.** OLGA 자체가 Windows용 프로그램입니다.
- **실제 실행에는 라이선스가 있는 OLGA 설치가 필요합니다.**
- **판정이 아니라 설명입니다.** 요약은 실행 결과가 보여 주는 내용을 설명할 뿐이고, 설계가 기준을 통과하는지는 엔지니어가 판단합니다.
- **함께 들어 있는 공기-물 표는 범용 표입니다**(공개 식으로 계산: IAPWS-95 물, Lemmon 공기, 0–80 °C, 0.5–20 bar). 학습과 빠른 확인용이니 실제 업무에는 사례에 맞춘 표를 쓰세요.
- **`.mfl`로 표를 만들려면 OLGA에 함께 들어 있는 Multiflash 엔진이 있어야 합니다** (OLGA 2022.1.0, Multiflash 7.3에서 확인). OLGA 표만 만들며, 하이드레이트·왁스 파일은 지금처럼 Multiflash에서 만듭니다.
- **독립 유체 표 생성기는 로컬 빌드에서만 쓸 수 있습니다.** 릴리스 빌드에는 빠져 있고, 이 생성기가 만든 표는 Multiflash 결과와 똑같지 않습니다.
- **AI 모델이 멈추거나 빈 답을 보낼 수 있습니다.** 앱이 다시 시도하라는 안내를 띄우고, 다시 물으면 하던 일을 이어 갑니다.
- **코드 서명 인증서를 갖추기 전까지 설치 파일은 서명되지 않습니다.**

</details>

## 동작 방식

```
  [ React UI ]  Tauri 2 WebView, English / 한국어
       |  인증된 로컬 HTTP + SSE (127.0.0.1)
       v
  [ Python 사이드카 ]  FastAPI, PyInstaller로 묶음
       +--> 대화 에이전트     도구, 승인 카드, 내가 연결한 AI 공급자
       +--> 사례 처리        .genkey 사양 / 검증 / 컴파일 / 저장
       +--> 실행 관리        별도 작업 폴더, 진행 상황, 취소, 제한 시간
       +--> 결과 읽기        .tpl / .ppl, 해시 확인
       v
  [ OLGA ]  사용자의 라이선스 OLGA 설치본. 앱에 포함하지 않고 수정하지도 않음
```

<a id="documentation"></a>

## 문서

| 문서 | 내용 |
|---|---|
| [체험용 튜토리얼](https://wjgoarxiv.github.io/olga-companion/tutorial/) | 연습 페이지: 데모 길과 배관표 길, 각각 일곱 단계 |
| [Architecture](docs/ARCHITECTURE.md) | 구성 요소와 저장 경계 |
| [Safety Gates](docs/SAFETY_GATES.md) | 파일, 실행, 결과 규칙 전체 |
| [Pipe tables](docs/PIPE_TABLE.md) | 배관표 가져오기의 열, 끝점, 분기점, 한계 |
| [Make a .tab from your values](docs/TAB_IMPORT.md) | 가진 값으로 OLGA PVT 표 쓰기 |
| [Network](docs/NETWORK.md) | 회사 네트워크용 프록시 설정 |
| [Packaging Runbook](docs/PACKAGING.md) | Windows 설치 파일 빌드 |
| [Updater signing key](docs/UPDATER-KEY.md) | 업데이트에 서명하는 키와 한 번 직접 설치해야 하는 경우 |

세부 문서는 영어로 되어 있습니다.

<a id="contributing"></a>
## 참여하기

이슈와 풀 리퀘스트를 환영합니다. `master`에서 브랜치를 만들고, 변경은 작게 유지하고, 동작이 바뀌면 회귀 테스트를 추가하고, 무엇을 확인했는지 풀 리퀘스트에 적어 주세요.

- [참여 안내](./CONTRIBUTING.md): 개발 환경, 테스트, 커밋과 풀 리퀘스트 규칙
- [보안 정책](./SECURITY.md): 취약점은 비공개로 알려 주세요
- [행동 강령](./CODE_OF_CONDUCT.md): Contributor Covenant 2.1
- [라이선스](./LICENSE): Apache 2.0

안내 문서는 영어로 되어 있습니다.

## 라이선스

소스 코드는 [Apache License 2.0](./LICENSE)입니다. Windows 설치 파일에는 [pyfas](https://github.com/gpagliuca/pyfas)(GPL-3.0)와 easydict(LGPL-3.0)도 들어 있어, 설치 파일 전체는 [GPL-3.0](./licenses/GPL-3.0.txt) 조건으로 배포합니다. [NOTICE](./NOTICE)와 [THIRD-PARTY-LICENSES.txt](./THIRD-PARTY-LICENSES.txt)를 참고하세요. 엔진 폴더 [`src/olga_companion/pvt_engine/`](src/olga_companion/pvt_engine/LICENSE)는 MIT 라이선스입니다. 튜토리얼 페이지에는 Pretendard(SIL OFL 1.1)와 Meslo LGS NF(Apache 2.0)가 들어 있으며, 라이선스 전문은 [`docs/tutorial/assets/fonts/`](docs/tutorial/assets/fonts/)에 있습니다.

OLGA는 SLB의 제품입니다. 이 앱은 독립적으로 만든 보조 앱이며 SLB와 제휴하거나 SLB의 보증·후원을 받지 않았습니다.

<div align="center">

만든 사람 **[Woojin Go](https://github.com/wjgoarxiv)** · <a href="#olga-companion">맨 위로 ↑</a>

</div>
