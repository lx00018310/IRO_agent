# IRO_agent — Feishu Gateway Migration Plan

## 1. Goal

Replace the current WeChat-oriented demo gateway with a real **Feishu application bot gateway**.

V0.1 should no longer implement or prioritize WeChat.

The production-facing interaction path becomes:

```text
Feishu Group / Feishu Private Chat
            |
            v
     Feishu Application Bot
            |
            v
   WebSocket Long Connection
            |
            v
      FeishuGateway
            |
            v
       IRO_agent Core
            |
            v
   Diagnostic Orchestrator
```

The existing HTTP gateway may remain only as a local development/test adapter.

---

# 2. Final Gateway Decision

Use:

> **Feishu Custom Application + Bot Capability + Event Subscription + WebSocket Long Connection**

Do not use a simple incoming-webhook group bot as the primary gateway.

IRO_agent needs:

- receive group @ mentions
- receive private messages
- identify chat/session/user
- receive text
- receive images
- reply to the originating message/chat
- maintain multi-turn session context

An application bot is the correct gateway for these requirements.

---

# 3. SDK Direction

Prefer the official Feishu/Lark Python SDK.

Preferred high-level implementation:

```text
lark-channel-sdk
```

with:

```python
from lark_channel import FeishuChannel
```

If the current environment or dependency constraints make that impractical, use the official:

```text
lark-oapi
```

direct WebSocket/event APIs.

Do not introduce unofficial bot frameworks unless the official SDK cannot meet a required function.

---

# 4. Remove WeChat from V0.1

Remove WeChat from:

- README
- config examples
- CLI help text
- environment-variable documentation
- tests
- production gateway startup
- package dependencies
- V0.1 feature list

Remove/deprecate configuration such as:

```text
wechat.enabled
wechat.token
wechat.aes_key
wechat.*
```

Do not spend time implementing:

- WeChat signature verification
- WeChat AES
- WeChat group @ parsing
- WeChat image handling
- iLink
- WeCom

These are outside current scope.

---

# 5. Gateway Abstraction

Keep the gateway isolated from the diagnostic core.

Create or retain a small common interface:

```text
GatewayAdapter
├─ start()
├─ stop()
├─ send_message()
├─ receive_message()
├─ download_resource()
└─ health()
```

Implement:

```text
FeishuGateway
HttpGateway
```

Where:

- `FeishuGateway` = production gateway
- `HttpGateway` = development/testing only

The diagnostic engine must not contain Feishu-specific code.

---

# 6. Feishu Configuration

Add configuration:

```yaml
gateway:
  type: feishu

feishu:
  enabled: true
  app_id: ${FEISHU_APP_ID}
  app_secret: ${FEISHU_APP_SECRET}
  receive_group_at: true
  receive_private: true
```

Secrets must come from environment variables or the existing secure credential mechanism.

Do not print `app_secret` in:

```text
iro-agent config
logs
exceptions
audit records
LLM context
```

---

# 7. Feishu Application Setup Requirements

Document the required setup in README.

The operator should:

1. Create a Feishu custom application.
2. Enable Bot capability.
3. Configure message/event permissions required for:
   - receiving messages
   - receiving group @ messages
   - receiving private messages
   - sending messages as the bot
4. Subscribe to:
   - `im.message.receive_v1`
5. Select:
   - WebSocket / long-connection event delivery
6. Publish/install the application in the tenant.
7. Add the bot to the required Feishu group.

Do not require a public HTTP callback URL for the default deployment.

---

# 8. Normalized Incoming Message Model

Feishu events must be normalized before entering IRO_agent.

Create:

```text
GatewayMessage
├─ gateway
├─ event_id
├─ message_id
├─ chat_id
├─ chat_type
├─ user_id
├─ timestamp
├─ message_type
├─ text
├─ image_refs
└─ raw_metadata
```

Example:

```json
{
  "gateway": "feishu",
  "event_id": "...",
  "message_id": "...",
  "chat_id": "...",
  "chat_type": "group",
  "user_id": "...",
  "timestamp": "2026-09-10T10:15:20+08:00",
  "message_type": "text",
  "text": "今天订单为什么卡住？",
  "image_refs": []
}
```

Only normalized data should enter the diagnostic core.

---

# 9. Group @ Behavior

In group chats:

```text
User @IRO_agent + question
           |
           v
      FeishuGateway
           |
           v
 remove bot mention from text
           |
           v
       IRO_agent
```

Example input:

```text
@IRO_agent 今天订单为什么又卡住了？
```

Normalized diagnostic question:

```text
今天订单为什么又卡住了？
```

Default behavior:

- respond to group messages only when the bot is @mentioned
- ignore unrelated group chatter
- private chat does not require @mention

This prevents IRO_agent from analyzing every message in the group.

---

# 10. Session Mapping

Session continuity must use stable Feishu identifiers.

Recommended:

```text
Group:
session_id = feishu:group:<chat_id>

Private:
session_id = feishu:p2p:<chat_id>
```

Keep user identity separately:

```text
user_id = Feishu sender open_id/user_id
```

Do not use display names as stable identifiers.

---

# 11. Project Mapping

IRO_agent may initially use one default project.

For V0.1:

```text
Feishu group A
    -> TASK-013
```

Configuration example:

```yaml
project_mapping:
  feishu:
    oc_xxxxxxxxx:
      project: TASK-013
```

If no mapping exists:

```text
use configured default project
```

Do not build a complex multi-tenant permission system in V0.1.

---

# 12. Text Message Flow

Implement:

```text
Feishu Event
    |
    v
Deduplicate by event/message ID
    |
    v
Check group @ rule
    |
    v
Normalize message
    |
    v
Record conversation timestamp
    |
    v
Resolve project/session
    |
    v
Agent Engine
    |
    v
Diagnostic Orchestrator
    |
    v
Business Language Interpreter
    |
    v
Reply through Feishu
```

The reply should preferably reply to the triggering message/thread when supported.

---

# 13. Image Message Flow

Do not create a separate image-diagnosis system.

Flow:

```text
Feishu image message
       |
       v
obtain resource/image key
       |
       v
FeishuGateway downloads resource
       |
       v
store in controlled temporary directory
       |
       v
GLM-5.3-Flash multimodal input
       |
       v
normal diagnostic workflow
       |
       v
delete temporary file
```

Security requirements:

- external users cannot specify arbitrary local paths
- downloaded files must go to an application-controlled temp directory
- enforce size limit
- only allow expected image types
- clean up after processing

---

# 14. Event Deduplication

Feishu events may be retried.

Store processed:

```text
event_id
message_id
processed_at
```

Before processing:

```text
if event_id already processed:
    ignore
```

This is required to prevent:

- duplicate replies
- duplicate Incident records
- duplicate historical statistics

SQLite is sufficient.

---

# 15. Long-Running Gateway Runtime

Add CLI commands:

```text
iro-agent gateway start
iro-agent gateway status
iro-agent gateway doctor
```

`gateway start` should:

1. load configuration
2. validate Feishu credentials exist
3. initialize IRO_agent
4. initialize active VersionReader
5. initialize Readers/Memory
6. connect to Feishu through WebSocket
7. show connection status
8. reconnect after recoverable disconnects
9. shut down gracefully

No GUI and no EXE are required.

---

# 16. Gateway Doctor

Implement a simple diagnostic command:

```text
iro-agent gateway doctor
```

Checks:

```text
[OK] FEISHU_APP_ID configured
[OK] FEISHU_APP_SECRET configured
[OK] GLM API reachable
[OK] TASK-013 project configured
[OK] Version provider: WReleaseReader
[OK] LogReader path readable
[OK] Database read-only connection
[OK] Incident database writable
[OK] Feishu WebSocket connection
```

Do not print actual secrets.

---

# 17. Security Boundaries

Feishu must remain only an input/output channel.

A Feishu user must never gain:

```text
shell
terminal
file write
git write
database write
service restart
PLC control
robot control
arbitrary local-file access
```

All existing IRO_agent read-only guarantees remain unchanged.

Never expose Feishu credentials to GLM.

Never put raw credentials in prompts.

---

# 18. Remove Local image_path Injection

The current HTTP demo must not allow an external request to provide:

```text
C:\...
D:\...
/etc/...
```

as an arbitrary `image_path`.

If HttpGateway remains:

- accept uploaded bytes or controlled resource IDs only
- save to controlled temp storage
- reject arbitrary local paths

This fix should be completed during the gateway migration.

---

# 19. Required Tests

## Test 1 — Gateway startup

Expected:

```text
Feishu WebSocket connected
```

---

## Test 2 — Private text

User privately sends:

```text
TASK-013今天有什么异常？
```

Expected:

- event received
- correct session created
- diagnostic engine invoked
- reply returned

---

## Test 3 — Group without @

User sends:

```text
TASK-013今天有什么异常？
```

Expected:

```text
no reply
```

---

## Test 4 — Group with @

User sends:

```text
@IRO_agent TASK-013今天有什么异常？
```

Expected:

- mention removed
- agent invoked
- reply sent to same chat

---

## Test 5 — Follow-up

```text
@IRO_agent 那这个问题以前发生过吗？
```

Expected:

- same group session context reused
- historical incident search works

---

## Test 6 — Image

User sends an image and asks:

```text
@IRO_agent 这个报错是什么意思？
```

Expected:

- resource downloaded through Feishu API
- image sent to GLM-5.3-Flash
- normal diagnostic context can also be queried
- temporary file removed afterward

---

## Test 7 — Duplicate event

Replay the same Feishu event.

Expected:

```text
second event ignored
no duplicate reply
no duplicate Incident
```

---

## Test 8 — Secret leakage

Expected:

No response/log contains:

```text
FEISHU_APP_SECRET
GLM_API_KEY
database password
tokens
```

---

# 20. End-to-End Acceptance Test

The key V0.1 demo should be:

```text
Feishu Group

User:
@IRO_agent 今天订单为什么又卡住了？是不是刚刚更新导致的？

IRO_agent:
1. receives the real Feishu @ message
2. resolves TASK-013
3. selects GitReader or WReleaseReader
4. checks version events
5. checks logs
6. checks database if necessary
7. checks Incident Memory
8. builds Incident Timeline
9. judges Fault Domain
10. judges Impact Scope
11. counts historical similar incidents
12. answers in business language
13. replies to the Feishu group
```

This is the primary V0.1 product demonstration.

---

# 21. Explicit Non-Goals

Do not add:

- WeChat
- WeCom
- Feishu dashboards
- Feishu interactive cards
- approval workflows
- Feishu Base/Bitable
- Feishu Docs integration
- automatic remediation
- shell execution
- GUI
- EXE packaging
- additional agent frameworks

Keep Feishu strictly as the communication gateway.

---

# 22. Recommended Commit Sequence

```text
01 refactor: replace wechat config with feishu gateway config
02 refactor: rename current http gateway as development adapter
03 feat: add gateway message normalization model
04 feat: integrate official feishu websocket channel
05 feat: handle group mention and private messages
06 feat: add feishu session and project mapping
07 feat: add feishu outbound reply
08 feat: add feishu image resource handling
09 feat: add event deduplication
10 fix: remove arbitrary local image path input
11 feat: add gateway doctor command
12 test: add feishu gateway integration tests
13 docs: add feishu application setup guide
14 test: add real task013 feishu end-to-end validation
```

---

# 23. Definition of Done

The Feishu migration is complete when:

- WeChat is removed from V0.1.
- Feishu application bot is the production gateway.
- WebSocket long connection works without a public callback server.
- Private text messages work.
- Group @ messages work.
- Non-@ group messages are ignored.
- Multi-turn group context works.
- Images can reach GLM-5.3-Flash safely.
- Duplicate events do not create duplicate replies/incidents.
- Feishu secrets never enter model context.
- Existing IRO_agent read-only restrictions remain intact.
- TASK-013 can be diagnosed through a real Feishu group.
- The existing HTTP adapter remains only for local tests if retained.

---

# 24. Final Product Path

```text
Feishu User
    |
    v
Feishu Application Bot
    |
    v
WebSocket
    |
    v
FeishuGateway
    |
    v
IRO_agent
    |
    +-> VersionReader
    +-> CodeReader
    +-> LogReader
    +-> DatabaseReader
    +-> Incident Memory
    |
    v
Incident Timeline
    |
    v
Fault Domain + Impact Scope
    |
    v
Business Language Interpreter
    |
    v
Feishu Reply
```

The next milestone is not another internal feature.

The milestone is:

> A real user @mentions IRO_agent in a real Feishu group and receives a TASK-013 diagnosis based on real evidence.
