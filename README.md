# 🎙️ AstrBot 口语练习插件

英语口语练习插件，集成 Azure 发音评估、Azure Speech-to-Text 和 Azure Text-to-Speech，并复用 AstrBot 已配置的 LLM 提供商，提供专业级口语训练体验。

## ✨ 功能特点

| 模式 | 说明 | 核心技术 |
|------|------|---------|
| 🗣️ 自由对话 | 与 AI 伙伴 Alex 自然英语对话 | Azure STT + LLM + Azure TTS |
| 📖 朗读练习 | 朗读句子获得发音评分 | Azure 发音评估 + LLM 反馈 |
| 🎭 场景练习 | 5 个真实场景角色扮演 | Azure STT + Azure 评估 + LLM |
| 🔤 单词操练 | 60 个分级单词逐词练习 | Azure 评估 + IPA 音标 |

### 其他特性
- 📊 **进度追踪** — SQLite 存储练习数据、发音错误
- 🔄 **间隔重复** — 自动推荐需要复习的单词
- 📈 **练习报告** — 可视化统计和趋势分析
- 🎯 **CEFR 分级** — A1/A2/B1/B2 四级难度
- 🛡️ **会话隔离** — 群聊中按用户隔离练习状态

## 📋 前置要求

1. **AstrBot** 已安装并运行
2. **Azure Speech Services** API Key（发音评估 + STT）
3. AstrBot WebUI 中已配置好的 LLM 提供商
4. 可选：**小米 MiMo** API Key（仅作为 STT/TTS 直连 fallback）

## 🔧 安装

### 方法 1: AstrBot WebUI 安装
1. 打开 AstrBot WebUI（默认 http://127.0.0.1:6185）
2. 导航到 **插件管理** → **安装插件**
3. 搜索 `astrbot_plugin_oral_practice` 或输入仓库地址

### 方法 2: 手动安装
```bash
# 将插件目录复制到 AstrBot 插件目录
cp -r astrbot_plugin_oral_practice/ <AstrBot安装目录>/data/plugins/

# 安装依赖
pip install -r astrbot_plugin_oral_practice/requirements.txt
```

## ⚙️ 配置

### 1. Azure Speech Services API Key

1. 访问 [Azure Portal](https://portal.azure.com)
2. 创建 **Speech Services** 资源：
   - 搜索 "Speech" → 创建 "Speech Services"
   - **区域**：建议选择离 AstrBot 服务器近的区域，例如美国服务器可用 `eastus`
   - **定价层**：选择 `S0`（标准）
3. 进入资源 → **Keys and Endpoint**
4. 复制 **Key 1** 和 **Region**

> 建议关闭 AstrBot 全局 STT。朗读评估必须先拿到原始音频交给 Azure Pronunciation Assessment；如果全局 STT 在插件前把语音替换成文本，插件将无法完成发音评估。

### 2. AstrBot 模型提供商

在 AstrBot WebUI 中先配置好：

- 大语言模型提供商：用于自由对话、场景回复和反馈生成

插件内 STT/TTS 默认使用 Azure Speech，不依赖 AstrBot 全局 STT/TTS。

### 3. 小米 MiMo API Key（可选 fallback）

1. 访问小米 MiMo 开放平台
2. 创建应用获取 API Key
3. 需要的模型：
   - `mimo-v2-omni` — 语音识别（STT）
   - `mimo-v2-tts` — 语音合成（TTS）

### 4. 在 AstrBot 中配置

1. AstrBot WebUI → **插件管理** → **口语练习助手** → **配置**
2. 填入以下配置项：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `llm_provider_id` | AstrBot 大语言模型提供商 | 留空使用默认 |
| `stt_backend` | STT 后端 | `azure` |
| `stt_provider_id` | AstrBot 语音识别提供商 | 仅 `stt_backend=astrbot` 时使用 |
| `tts_backend` | TTS 后端 | `azure` |
| `azure_tts_voice` | Azure TTS 声音 | `en-US-JennyMultilingualNeural` |
| `tts_provider_id` | AstrBot 语音合成提供商 | 仅 `tts_backend=astrbot` 时使用 |
| `azure_speech_key` | Azure Speech API Key | `xxxxxxxxxxxxxxxx` |
| `azure_speech_region` | Azure 区域 | `eastus` |
| `mimo_api_key` | MiMo 直连 fallback API Key | 可选 |

## 📖 使用方法

### 命令一览

| 命令 | 功能 |
|------|------|
| `/oral` | 显示主菜单 |
| `/oral talk` | 开始自由对话 |
| `/oral read` | 开始朗读练习 |
| `/oral scene` | 场景练习（选择场景） |
| `/oral scene restaurant` | 直接进入餐厅场景 |
| `/oral drill` | 单词发音操练 |
| `/oral level B1` | 设置难度等级 |
| `/oral report` | 查看练习报告 |
| `/oral stop` | 结束当前练习 |

### 练习中命令

在练习模式中，直接发送语音消息即可练习。文本命令：
- `下一个` / `next` — 跳到下一题
- `再来` / `again` — 重试当前题目
- `换难度 B1` / `level B1` — 更改难度

### 可用场景

| 编号 | 场景 | 英文 |
|------|------|------|
| 1 | 🍽️ 在餐厅点餐 | Ordering at a Restaurant |
| 2 | ✈️ 机场值机 | Airport Check-in |
| 3 | 💼 工作面试 | Job Interview |
| 4 | 🛍️ 商场购物 | Shopping at a Store |
| 5 | 🏨 酒店入住 | Hotel Check-in |

## 🏗️ 项目结构

```
astrbot_plugin_oral_practice/
├── main.py                  # 插件入口 (Star 子类)
├── metadata.yaml            # 插件元数据
├── _conf_schema.json        # 配置 schema
├── requirements.txt         # Python 依赖
│
├── core/                    # 核心服务层
│   ├── astrbot_services.py  # AstrBot STT/TTS 提供商适配
│   ├── azure_stt_service.py # Azure Speech-to-Text
│   ├── azure_tts_service.py # Azure Text-to-Speech
│   ├── stt_service.py       # MiMo-V2-Omni 直连 fallback
│   ├── tts_service.py       # MiMo-V2-TTS 直连 fallback
│   ├── pronunciation.py     # Azure 发音评估
│   ├── conversation.py      # AstrBot LLM 对话引擎
│   ├── feedback.py          # 反馈报告生成
│   ├── progress.py          # SQLite 进度追踪
│   ├── session.py           # 会话状态机
│   └── audio_utils.py       # 音频格式转换
│
├── modes/                   # 练习模式
│   ├── base_mode.py         # 模式抽象基类
│   ├── free_talk.py         # 自由对话模式
│   ├── read_aloud.py        # 朗读练习模式
│   ├── scenario.py          # 场景练习模式
│   └── word_drill.py        # 单词操练模式
│
└── prompts/                 # LLM Prompt 模板
    └── tutor_system.py      # 系统 prompt 定义
```

## 🔌 技术架构

```
用户语音 → AstrBot 平台适配器 → 口语练习插件
                                      │
                 ┌────────────────────┼────────────────────┐
                 │                    │                    │
          AstrBot STT          Azure 评估          AstrBot LLM
         (语音→文字)          (发音评分)           (对话/反馈)
                  │                    │                    │
                  └────────────────────┼────────────────────┘
                                       │
                                  AstrBot TTS
                                (文字→语音)
                                      │
                              回复用户 (文字+语音)
```

## 📄 License

MIT
