# Headroom

이 맥에 로그인된 ChatGPT, Claude, Grok, Gemini의 구독 사용량을 메뉴 막대와 작은 창에 모읍니다.

요금제는 토큰 개수를 알려 주지 않습니다. 각 CLI가 보는 것과 같은 **사용량 %** 를 보여 줍니다. 프롬프트를 보내지 않으므로 할당량을 쓰지 않습니다.

## 화면

순서는 ChatGPT, Claude, Grok, Gemini입니다.

메뉴 막대에는 회사 로고 아래 사용량 %가 붙습니다. 한 회사에 한도가 여러 개면 그중 가장 많이 쓴 값을 표시합니다. 80% 이상이면 창의 숫자와 막대가 붉은색이 됩니다. 로그인이 없으면 `–`입니다.

창에는 이름, 가장 빠른 리셋 시각, 요금제, 크레딧, 한도별 사용량이 나옵니다. 예: `5h`, `wk`, `Fable`, Gemini의 `Pro` / `Flash`. Gemini 모델이 많으면 가장 많이 쓴 4개만 표시합니다.

클릭하면 창이 열립니다. 창이 앞에 있을 때 한 번 더 누르면 창만 닫히고, 메뉴 막대와 서버는 그대로입니다. 오른쪽 클릭은 열기 / 종료입니다. 창의 닫기 버튼도 앱을 종료하지 않습니다.

## 준비

각 회사 CLI로 이 맥에 한 번 로그인합니다. Headroom은 그 로그인을 읽습니다. Claude는 키체인에 있는 최신 로그인을 먼저 보고, 액세스 토큰이 만료되면 Claude CLI와 같은 방식으로만 갱신합니다. Grok과 Gemini 토큰은 갱신하지 않습니다.

| 회사 | 로그인 | Headroom이 읽는 파일 |
| --- | --- | --- |
| ChatGPT | Codex (`codex`) | `~/.codex/auth.json` |
| Claude | Claude Code (`claude`) | 키체인의 `Claude Code-credentials`, 없으면 `~/.claude/.credentials.json` |
| Grok | `grok` | `~/.grok/auth.json` |
| Gemini | `gemini`로 Google 로그인 | `~/.gemini/oauth_creds.json` |

Gemini API 키(`GEMINI_API_KEY`)만으로는 구독 한도를 조회할 수 없습니다. Google 계정 로그인이 필요합니다. `~/.config/gemini/oauth_creds.json`도 봅니다. 키체인에만 있는 Gemini 로그인은 읽지 않습니다.

## 맥 앱

```bash
python3 scripts/make_icon.py
./scripts/build_mac_app.sh
open Headroom.app
```

메뉴 막대, 다른 상태 아이콘들 사이에 붙습니다. 종료는 오른쪽 클릭의 종료입니다. 앱이 직접 띄운 서버는 종료할 때 같이 끝납니다.

터미널만 쓰려면:

```bash
python3 server.py
```

브라우저에서 http://127.0.0.1:8737 을 엽니다.

## 로그인이 없거나 만료되면

Grok과 Gemini 토큰은 Headroom이 갱신하지 않습니다. 그 둘은 각 CLI를 한 번 실행하면 그 CLI가 로그인을 다시 씁니다.

- ChatGPT: Codex를 한 번 실행합니다. 창에는 `Open Codex once`.
- Claude: 만료되면 Headroom이 갱신합니다. 갱신이 거절되면 `claude`를 한 번 실행합니다. 창에는 `Open Claude once`.
- Grok: 터미널에서 `grok`를 한 번 실행합니다. Grok 토큰을 Headroom이 갱신하면 CLI 로그인이 풀릴 수 있어, Headroom은 그 파일을 쓰지 않습니다.
- Gemini: `gemini`를 한 번 실행합니다. 창에는 `Run gemini once`.

로그인 파일 자체가 없으면 `No ChatGPT login on this Mac`처럼 표시됩니다.

## 폰

기본값은 이 맥의 `127.0.0.1`만 엽니다. 같은 와이파이의 폰에서는 열리지 않습니다.

폰에서 보려면 비밀번호 없는 주소를 집 안에만 열어야 합니다. 공유기를 통해 인터넷으로 열지 마세요. 응답에는 사용량, 요금제 이름, 리셋 시각, 크레딧 잔액이 있고 로그인 토큰은 없습니다. 그래도 집 밖에서는 열 이유가 없습니다.

맥 앱으로 쓰려면 앱을 종료한 뒤:

```bash
mkdir -p "$HOME/Library/Application Support/Headroom"
touch "$HOME/Library/Application Support/Headroom/lan"
open Headroom.app
```

끄려면 그 `lan` 파일을 지우고 앱을 다시 엽니다.

터미널로 쓰려면:

```bash
python3 server.py --lan
```

`HEADROOM_LAN=1`도 같습니다. 창 아래에 `호스트:8737`이 나오면, 폰이 같은 와이파이에 있는 동안 Safari로 열고 공유 → 홈 화면에 추가합니다. 맥 앱이 꺼지면 폰에서도 열리지 않습니다.

## 보안

- 서버는 기본적으로 `127.0.0.1:8737`만 듣습니다. 폰 접근은 `--lan`, `HEADROOM_LAN=1`, 또는 위의 `lan` 파일로만 켭니다.
- Grok, Gemini 자격 증명에는 쓰지 않습니다. Claude 액세스 토큰이 만료됐을 때만 갱신하고, 키체인 항목과 `~/.claude/.credentials.json`에 다시 씁니다.
- Google OAuth 클라이언트 비밀은 저장소에 없습니다. Gemini 토큰도 갱신하지 않습니다.
- API 응답과 화면에는 토큰, 이메일, 계정 ID, Google Cloud 프로젝트 ID를 넣지 않습니다.
- 로고 주소는 `chatgpt.png`, `claude.png`, `grok.png`, `gemini.png`만 허용합니다.
- 오류 본문은 화면에 그대로 올리지 않습니다. 만료는 `Login expired`로만 처리한 뒤 위의 안내 문구로 바꿉니다.

## 테스트

네트워크를 호출하지 않습니다.

```bash
python3 -m unittest tests/test_usage.py
```

## 로고

메뉴 막대와 창의 마크는 각 회사를 구분하기 위한 것입니다. ChatGPT, Claude, Grok, Gemini 로고는 OpenAI, Anthropic, xAI, Google의 상표이며 이 프로젝트의 소유가 아닙니다.
