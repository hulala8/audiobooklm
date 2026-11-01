# SOP：用本地 TTS（CosyVoice）给音剪章节配音并挂载回段落

> 适用场景：不用音剪自带 AI，而是用本地 Cosy（http://localhost:50000/）生成旁白，
> 再上传到音剪（aigc.ximalaya.com）章节里对应的段落。
> 已验证：三侠剑 book_id=34665，第 70–78 集，共 156 段旁白，全链路打通。

---

## 0. 一次性准备

| 项 | 位置 | 说明 |
|---|---|---|
| API Token | `~/.workbuddy/skills/audiobooklm/.env` → `AUDIOBOOKLM_TOKEN` | 只能**读** ABS 内容，章节级写入不够 |
| 浏览器 Cookie | 工作区 `cookie.txt` | 章节级写入**必须**。F12 → Network → 任一 XHR → Request Headers → 复制 `Cookie:` 整串 |
| MCP 客户端 | `~/.workbuddy/skills/audiobooklm/mcp_client.py` | `python mcp_client.py call <工具名> <JSON 或 @文件>` |
| 门户客户端 | 工作区 `portal.py` | `portal.call(path, params, body)`，自带 Cookie |
| Cosy 客户端 | 工作区 `cosy_tts.py` | 参考音色「评书旁白1.wav」，3s极速复刻，speed=1.0 |

Cosy 服务必须先启动并加载参考音色：
```bash
curl -sS -X POST http://localhost:50000/gradio_api/api/load_prompt_from_library \
  -H "Content-Type: application/json" -d '{"data":["评书旁白1.wav"]}'
```

---

## 1. 主链路（四步，一步都不能少）

```
①  read_abs(章节)              → 拿 blocks，筛 character_name == '旁白'
②  本地 Cosy 合成               → audio/<集号>/NN_<blockId>.mp3
③  POST /voice-studio-chapter/paragraph/material/upload   multipart: paragraphId + characterId + file
                                 → 返回 materialId
④  POST /voice-studio-chapter/paragraph/material/update   {materialId, paragraphId, materialMode: 2}   ← A 选中生效
⑤  B 任务完成 —— **必须先判断任务类型，两套接口不通用**，见下方「B 的分流」
⑥  POST /voice-studio-chapter/paragraph/material/update   {materialId, paragraphId, materialMode: 2}   ← 再选中一次
```

### B 的分流（最容易漏的一步）

平台有**两套任务体系**，按角色的 `mixMode` 决定，用错接口会「返回 200000 但状态不变」：

```
GET /voice-studio-task/task/state/paragraph?paragraphId=&characterId=&bookId=
  → data.ttsTask    存在 → AI 任务   → POST /voice-studio-task/task/robot/finish  {paragraphId}
  → data.recordTask 存在 → 录音任务  → POST /voice-studio-task/task/record/finish {paragraphId}
  → data == {}           → 无任务    → 直接调 record/finish 即可（会自动创建并置完成）
```

判断依据：`taskState == 2` 即已完成；UI 上「任务完成」按钮的显示条件就是 `taskState !== 2`。
`beenFinished` 只控制「发布返音」按钮，与任务完成无关，不用管。

> 实测：三侠剑里旁白/林素梅是 `ttsTask`（AI 角色），林士佩/胜英等是 `recordTask`（录音角色）。
> 一律调 `robot/finish` 会让所有录音角色段落静默失败 —— 接口返回成功但 UI 按钮还在。
> `record/publish`（发布任务）需要 `taskDesc` + `hasTicket` 且**会扣星点**（报「星点不足」），
> 不必用它，`record/finish` 本身就能创建并完成。

一键校验+修复：`python finish_tasks.py [角色名]`（自动分流、回查 taskState、幂等）。

第 ⑥ 步不是多余：前端的真实顺序就是「选中 → 完成任务 → 再选中 → 刷新列表」，
少了最后一步，完成任务时可能把选中态覆盖掉。

一键跑（幂等，重跑自动跳过已完成项）：

```bash
cd work/sanxiajian
MSYS_NO_PATHCONV=1 python run_chapters.py 71-78        # 生成 + 上传 + A + B
MSYS_NO_PATHCONV=1 python run_chapters.py 71-78 --gen-only      # 只生成不上传
MSYS_NO_PATHCONV=1 python run_chapters.py 71-78 --refresh-prompt # 音色缓存失效时用
```

产出：`audio/<集号>/NN_<blockId>.mp3`、`manifest_<集号>.json`（含 materialId 与每步返回码）。

---

## 2. 踩坑清单（按被坑的严重程度排序）

### 2.1 章节下标 ≠ 集号 ★★★
`chapter_ids[i]` 的标题章号与 `i` **不对应**（实测 idx65→第070章，idx68→第073章）。
**必须按标题 `第0NN章` 正则匹配**，不能按下标取。脚本里 `resolve_chapter_ids()` 就是干这个的。

### 2.2 API Token 写不了章节 ★★★
- 不带 Cookie：`chapter detail raw error code=401000`
- 带空 Cookie：`cast list status=401`
- 但同一 Token 调 `move_chapter_content` 却完全正常 → 别被误导成「章节不可写」

**结论：章节维度写入强制要浏览器 Cookie。** Cookie 有效期有限，过期需重新抓。

### 2.3 `patch_abs` 这条路是死路 ★★★
别在它身上耗时间，它**静默丢弃** `status` / `audio` 字段（版本号照涨，字段不变）。
三个具体坑：
- `base_version` 要 **字符串且带 `v` 前缀**：`"v5"`，传 `5` 或 `"5"` 都不生效
- `op_id` 必须每次唯一，复用会报 `validation_failed`——错误信息长得像字段校验失败，实际是幂等冲突
- 即便全对，`status`/`audio` 也写不进去

### 2.4 本地路径不会自动变 CDN URL ★★
段落 `audio` 字段要的是 COS 地址。试过直接塞本地绝对路径，**会被序列化时丢弃**；
塞真实 http 地址同样不落库。正确做法是走 ③ 的 `material/upload` 拿 `materialId`。

### 2.5 `materialMode` 必传 ★★
`material/update` 不传会报「素材选中模式不能为空」。取值 `1`/`2` 合法，`3` 非法。
前端选中后传的是 `2`，沿用即可。

### 2.5b 「返回 200000」不等于生效 ★★★
端口接口很宽容，参数不对也常返回 `200000 处理成功`。**完成后必须用
`GET /voice-studio-task/task/state/paragraph` 回查 `taskState`**，别信返回码。
（教训：253 段调了 robot/finish 全部 200000，实际有 94 段录音任务根本没被置完成。）

### 2.6 `read_abs` 不能用来验证结果 ★★
ABS 内容层**不反映**编辑器层的素材与任务状态。即使门户接口全部返回 `200000`，
`read_abs` 仍显示 `status: draft`、`audio: null`。
→ **无法用 API 自证，必须让用户在 UI 上抽查**（音频行是否「已选」、状态是否「已」、试听是否是 Cosy 的声音）。

### 2.7 Git Bash 会把 `/` 开头的参数转成 Windows 路径 ★
`python portal.py "/voice-studio-..."` 会被改写。命令前加 `MSYS_NO_PATHCONV=1`。

### 2.8 前端中文是 Unicode 转义 ★
JS 分包里存的是 `\u5DF2\u9009`（已选）、`\u4EFB\u52A1\u5B8C\u6210`（任务完成）。
直接 grep 中文搜不到，要用转义串或用转义后匹配。逆向入口：
`main.js` + `chunks/index-BH6YabHd.js`（上传弹窗）、`chunks/index-Bg9bbOpK.js`（段落设置）。

### 2.9 Cosy 的 gradio temp 路径会失效 ★
`prompt_cache.json` 存的是 `C:\...\gradio\<hash>\评书旁白1.wav`，gradio 清理后失效。
生成全线失败时用 `--refresh-prompt` 重新加载。

### 2.10 用户在 UI 里同时编辑会造成版本冲突 ★
`chapter_version` 会不停变化，导致带 `base_version` 的写入失败。
批量跑之前让用户**不要开着那一集的编辑页**。

### 2.11 MCP 网关不返回 `mcp-session-id` ★
SKILL.md 里写的「先取 session id 再调用」在这个网关下**不成立**，硬等会一直卡住。
网关是无状态模式，直接 POST 即可。

### 2.12 工具清单以 `tools/list` 为准 ★
实测 67 个工具，SKILL.md 只记了 20 个。路由前先 `tools/list`，别硬编码工具名。

---

## 3. 逆向接口的方法（下次接口变了照这个来）

1. 打开 `https://aigc.ximalaya.com/` → 从 HTML 里找 `s1.xmcdn.com/yx/studio/last/dist/assets/index-*.js`
2. 下载入口 JS → 再下 `main-*.js`（3.4MB，含全部接口路径）
3. 下载 `assets/` 下所有分包（注意：**chunklist 要用 `\n` 写，CRLF 会导致下载全部失败**）
4. 按 Unicode 转义串（`ctx.py 已选/任务完成`）定位按钮 → 往上找它调用的函数
5. 函数在 main.js 的 export 表里，正则 `([A-Za-z0-9_$]+) as <别名>` 反查本地函数名，再看其定义里的路径常量

---

## 4. 已知常量（三侠剑 book_id=34665）

| 项 | 值 |
|---|---|
| team_id | 8511 |
| 旁白角色 character_id | 4987638 |
| 第070章 chapter_id | 7607697 |
| 第071–078章 | 7607698 / 7607699 / 7607700 / 7607701 / 7607702 / 7607704 / 7607731 / 7607732 |
| 专辑（若走发布） | 131632271「三侠剑 \| 经典短打评书 \| 神镖将胜英」 |
| 成功返回码 | `200000 处理成功` |

> 注意 `7607703` 缺失，第075→076 之间 ID 有跳号，再次印证「按标题匹配、别按 ID 推算」。
